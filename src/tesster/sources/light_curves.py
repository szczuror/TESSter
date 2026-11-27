"""Light-curve measurements and the MAST TESS light-curve archive (Package B).

Split into two parts:
1. Pure measurement functions (``detrend_light_curve``, ``fold_phase``, ``measure_transits``) that
   take a ``LightCurve`` and compute the depths and errors of odd transits, even transits and the
   secondary eclipse without the network.
2. ``MastLightCurves``, which downloads SPOC light curves from MAST, measures the transit metrics
   and remembers the result per candidate so the odd-even and secondary-eclipse tests do not
   download or measure the same light curve twice.
"""

from __future__ import annotations

import io
import math
import threading
import warnings
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import urlencode

import numpy as np
import requests
from astropy.io import fits

from tesster.models import CatalogEntry, CentroidMeasurement, Source, TransitMetrics
from tesster.sources.base import LIGHT_CURVE_ARCHIVE_NAME, SourceUnavailableError
from tesster.sources.not_connected import NotConnected

MAST_DOWNLOAD_URL = "https://mast.stsci.edu/api/v0.1/Download/file"
TIME_LIMIT_SECONDS = 60.0
MAX_SECTORS = 4
"""Up to this many TESS sectors are combined per candidate."""

GAP_SPLIT_DAYS = 0.5
"""Time gap that starts a new continuous light-curve segment when removing trends."""

MEDIAN_VARIANCE_FACTOR = math.pi / 2
"""How much more the median of Gaussian samples varies than their mean (large-sample limit)."""


@dataclass(frozen=True)
class LightCurve:
    """Normalized time-series photometry in BTJD."""

    time: np.ndarray
    flux: np.ndarray
    flux_err: np.ndarray

    def __post_init__(self) -> None:
        if not (len(self.time) == len(self.flux) == len(self.flux_err)):
            raise ValueError("time, flux and flux_err must have the same length.")


def fold_phase(time: np.ndarray, period_days: float, center_btjd: float) -> np.ndarray:
    """Fold ``time`` on ``period_days`` around ``center_btjd`` into ``[-period/2, period/2)``."""
    half = 0.5 * period_days
    return ((np.asarray(time, dtype=float) - center_btjd + half) % period_days) - half


def detrend_light_curve(
    lc: LightCurve,
    *,
    period_days: float,
    epoch_btjd: float,
    duration_hours: float,
) -> LightCurve:
    """Remove slow stellar and instrumental trends while keeping primary and secondary dips."""
    if len(lc.time) == 0:
        return lc
    dur_days = duration_hours / 24.0
    order = np.argsort(lc.time)
    t = np.asarray(lc.time, dtype=float)[order]
    f = np.asarray(lc.flux, dtype=float)[order]
    e = np.asarray(lc.flux_err, dtype=float)[order]

    dt_pri = fold_phase(t, period_days, epoch_btjd)
    dt_sec = fold_phase(t, period_days, epoch_btjd + 0.5 * period_days)
    out_of_eclipse = (np.abs(dt_pri) >= 0.6 * dur_days) & (np.abs(dt_sec) >= 0.6 * dur_days)

    gaps = np.where(np.diff(t) > GAP_SPLIT_DAYS)[0] + 1
    segments = np.split(np.arange(len(t)), gaps)
    f_detrended = np.empty_like(f)
    e_detrended = np.empty_like(e)
    half_window = max(3.0 * dur_days, 0.5)
    step = max(dur_days, 0.1)

    for seg in segments:
        if len(seg) == 0:
            continue
        ts, fs, es, ms = t[seg], f[seg], e[seg], out_of_eclipse[seg]
        if not np.any(ms):
            med = float(np.median(fs))
            scale = med if med > 0 else 1.0
            f_detrended[seg] = fs / scale
            e_detrended[seg] = es / scale
            continue
        t_base, f_base = ts[ms], fs[ms]
        grid = np.arange(ts[0], ts[-1] + 0.5 * step, step)
        ctrl_t: list[float] = []
        ctrl_f: list[float] = []
        for g in grid:
            in_win = np.abs(t_base - g) <= half_window
            if np.any(in_win):
                val = float(np.median(f_base[in_win]))
                if val > 0:
                    ctrl_t.append(float(g))
                    ctrl_f.append(val)
        if len(ctrl_t) >= 2:
            trend = np.interp(ts, ctrl_t, ctrl_f)
        else:
            med = float(np.median(f_base))
            trend = np.full_like(fs, med if med > 0 else 1.0)
        f_detrended[seg] = fs / trend
        e_detrended[seg] = es / trend

    return LightCurve(time=t, flux=f_detrended, flux_err=e_detrended)


def measure_transits(
    lc: LightCurve,
    *,
    period_days: float,
    epoch_btjd: float,
    duration_hours: float,
    source: Source,
) -> TransitMetrics | None:
    """Measure odd-transit, even-transit and secondary-eclipse depths and errors from ``lc``."""
    if len(lc.time) == 0 or period_days <= 0 or duration_hours <= 0:
        return None

    clean = detrend_light_curve(
        lc,
        period_days=period_days,
        epoch_btjd=epoch_btjd,
        duration_hours=duration_hours,
    )
    t, f, e = clean.time, clean.flux, clean.flux_err
    dur_days = duration_hours / 24.0

    cycles = np.round((t - epoch_btjd) / period_days).astype(int)
    dt = t - (epoch_btjd + cycles * period_days)

    odd_depths: list[float] = []
    odd_vars: list[float] = []
    even_depths: list[float] = []
    even_vars: list[float] = []

    for cycle in sorted(set(cycles.tolist())):
        in_cycle = cycles == cycle
        dt_k, f_k, e_k = dt[in_cycle], f[in_cycle], e[in_cycle]
        in_tr = np.abs(dt_k) <= 0.3 * dur_days
        out_tr = (np.abs(dt_k) >= 0.75 * dur_days) & (np.abs(dt_k) <= 2.5 * dur_days)
        n_in, n_out = int(np.sum(in_tr)), int(np.sum(out_tr))
        if n_in < 2 or n_out < 4:
            continue
        depth_ppm, var_ppm = _window_depth_and_variance(
            f_k[in_tr], e_k[in_tr], f_k[out_tr], e_k[out_tr]
        )
        if cycle % 2 != 0:
            odd_depths.append(depth_ppm)
            odd_vars.append(var_ppm)
        else:
            even_depths.append(depth_ppm)
            even_vars.append(var_ppm)

    if not odd_depths and not even_depths:
        return None

    odd_depth, odd_err, odd_count = _combine_transits(odd_depths, odd_vars)
    even_depth, even_err, even_count = _combine_transits(even_depths, even_vars)

    dt_sec = fold_phase(t, period_days, epoch_btjd + 0.5 * period_days)
    in_sec = np.abs(dt_sec) <= 0.35 * dur_days
    out_sec = (np.abs(dt_sec) >= 0.75 * dur_days) & (np.abs(dt_sec) <= 2.0 * dur_days)
    if int(np.sum(in_sec)) >= 2 and int(np.sum(out_sec)) >= 4:
        sec_depth, sec_var = _window_depth_and_variance(
            f[in_sec], e[in_sec], f[out_sec], e[out_sec]
        )
        sec_err = math.sqrt(sec_var)
    else:
        sec_depth, sec_err = 0.0, 0.0

    return TransitMetrics(
        odd_depth_ppm=round(odd_depth, 1),
        odd_depth_err_ppm=round(odd_err, 1),
        odd_transits=odd_count,
        even_depth_ppm=round(even_depth, 1),
        even_depth_err_ppm=round(even_err, 1),
        even_transits=even_count,
        secondary_depth_ppm=round(sec_depth, 1),
        secondary_depth_err_ppm=round(sec_err, 1),
        source=source,
    )


def _window_depth_and_variance(
    f_in: np.ndarray,
    e_in: np.ndarray,
    f_out: np.ndarray,
    e_out: np.ndarray,
) -> tuple[float, float]:
    """Depth in ppm and variance in ppm^2 comparing ``f_in`` against baseline ``f_out``."""
    base = float(np.median(f_out))
    if base <= 0:
        base = 1.0
    dip = float(np.median(f_in))
    depth_ppm = (base - dip) / base * 1e6
    var_ppm = (_median_variance(f_in, e_in) + _median_variance(f_out, e_out)) / (base**2) * 1e12
    return depth_ppm, var_ppm


def _median_variance(flux: np.ndarray, flux_err: np.ndarray) -> float:
    """Variance of the median of ``flux``.

    The noise is estimated once: from the archive's flux errors or from the scatter of the points,
    whichever is larger, so underestimated archive errors or extra noise are not missed. Adding
    the two would count the same noise twice and let real odd-even differences and secondary
    eclipses pass (FR-06). The median of ``n`` points with Gaussian noise varies ``pi / 2`` times
    more than their mean.
    """
    n = len(flux)
    propagated = float(np.sum(flux_err**2)) / n**2
    scatter = float(np.var(flux, ddof=1)) / n if n > 1 else 0.0
    return MEDIAN_VARIANCE_FACTOR * max(propagated, scatter)


def _combine_transits(
    depths: Sequence[float], variances: Sequence[float]
) -> tuple[float, float, int]:
    """Mean depth, standard error in ppm and transit count across individual transits.

    The error is the one from the single-transit errors or from the scatter between transits,
    whichever is larger. They measure the same noise, so they are not added.
    """
    n = len(depths)
    if n == 0:
        return 0.0, 0.0, 0
    arr = np.asarray(depths, dtype=float)
    var_arr = np.asarray(variances, dtype=float)
    mean_depth = float(np.mean(arr))
    err_prop = math.sqrt(float(np.sum(var_arr))) / n
    err_scatter = float(np.std(arr, ddof=1)) / math.sqrt(n) if n > 1 else 0.0
    return mean_depth, max(err_prop, err_scatter), n


def mast_download_link(uri: str) -> str:
    """A browser-resolvable link to the MAST light-curve FITS file (FR-14)."""
    return f"{MAST_DOWNLOAD_URL}?{urlencode({'uri': uri})}"


def ask_mast_uris(tic_id: int) -> list[str]:
    """Return up to ``MAX_SECTORS`` MAST data URIs for a star's TESS light curves."""
    from astroquery import exceptions as astroquery_errors
    from astroquery.mast import Observations

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", astroquery_errors.NoResultsWarning)
            table = Observations.query_criteria(
                obs_collection="TESS",
                dataproduct_type="timeseries",
                target_name=str(int(tic_id)),
            )
    except (
        astroquery_errors.InvalidQueryError,
        astroquery_errors.RemoteServiceError,
        astroquery_errors.TimeoutError,
        requests.RequestException,
    ) as exc:
        raise SourceUnavailableError(LIGHT_CURVE_ARCHIVE_NAME, _summary(exc)) from exc

    if len(table) == 0 or "dataURL" not in table.colnames:
        return []
    urls = [str(row["dataURL"]) for row in table if not getattr(row["dataURL"], "mask", False)]
    spoc_2min = sorted(u for u in urls if u.endswith("-s_lc.fits"))
    if spoc_2min:
        return spoc_2min[:MAX_SECTORS]
    any_lc = sorted(u for u in urls if u.endswith("lc.fits"))
    return any_lc[:MAX_SECTORS]


def download_light_curve(uri: str, timeout: float = TIME_LIMIT_SECONDS) -> LightCurve:
    """Download one TESS light-curve FITS file from MAST and return its clean photometry."""
    try:
        response = requests.get(MAST_DOWNLOAD_URL, params={"uri": uri}, timeout=timeout)
        response.raise_for_status()
        return parse_fits_light_curve(response.content)
    except (requests.RequestException, OSError) as exc:
        raise SourceUnavailableError(LIGHT_CURVE_ARCHIVE_NAME, _summary(exc)) from exc


def parse_fits_light_curve(content: bytes) -> LightCurve:
    """Extract normalized ``(TIME, PDCSAP_FLUX, PDCSAP_FLUX_ERR)`` with ``QUALITY == 0``."""
    with fits.open(io.BytesIO(content)) as hdul:
        if len(hdul) < 2 or hdul[1].data is None:
            return LightCurve(np.array([]), np.array([]), np.array([]))
        data = hdul[1].data
        names = set(data.names or ())
        flux_col = "PDCSAP_FLUX" if "PDCSAP_FLUX" in names else "SAP_FLUX"
        err_col = "PDCSAP_FLUX_ERR" if "PDCSAP_FLUX_ERR" in names else "SAP_FLUX_ERR"
        if "TIME" not in names or flux_col not in names or err_col not in names:
            return LightCurve(np.array([]), np.array([]), np.array([]))

        t = np.asarray(data["TIME"], dtype=float)
        f = np.asarray(data[flux_col], dtype=float)
        e = np.asarray(data[err_col], dtype=float)
        q = np.asarray(data["QUALITY"], dtype=int) if "QUALITY" in names else np.zeros(len(t), int)

    valid = np.isfinite(t) & np.isfinite(f) & np.isfinite(e) & (q == 0) & (f > 0) & (e > 0)
    t, f, e = t[valid], f[valid], e[valid]
    if len(t) == 0:
        return LightCurve(t, f, e)
    med = float(np.median(f))
    return LightCurve(time=t, flux=f / med, flux_err=e / med)


def concat_light_curves(curves: Sequence[LightCurve]) -> LightCurve:
    non_empty = [c for c in curves if len(c.time) > 0]
    if not non_empty:
        return LightCurve(np.array([]), np.array([]), np.array([]))
    return LightCurve(
        time=np.concatenate([c.time for c in non_empty]),
        flux=np.concatenate([c.flux for c in non_empty]),
        flux_err=np.concatenate([c.flux_err for c in non_empty]),
    )


class MastLightCurves:
    """Implements LightCurveArchive for transit measurements from MAST, caching per candidate.

    Centroid measurements are passed to ``centroids``: ``SpocCentroidArchive`` in
    ``build_sources()``, ``NotConnected`` when none is given.
    """

    def __init__(
        self,
        ask_uris: Callable[[int], list[str]] | None = None,
        fetch_curve: Callable[[str], LightCurve] | None = None,
        today: Callable[[], date] = date.today,
        time_limit: float = TIME_LIMIT_SECONDS,
        centroids: Any = None,
    ) -> None:
        self._ask_uris = ask_uris
        self._fetch_curve = fetch_curve
        self._today = today
        self._time_limit = time_limit
        self._centroids = centroids if centroids is not None else NotConnected()
        self._cache: dict[str, TransitMetrics | None] = {}

    def transit_metrics(self, candidate: CatalogEntry) -> TransitMetrics | None:
        key = str(candidate.toi)
        if key not in self._cache:
            self._cache[key] = self._compute_metrics(candidate)
        return self._cache[key]

    def centroid(self, candidate: CatalogEntry) -> CentroidMeasurement | None:
        return self._centroids.centroid(candidate)

    def _compute_metrics(self, candidate: CatalogEntry) -> TransitMetrics | None:
        ask_uris = self._ask_uris if self._ask_uris is not None else ask_mast_uris
        fetch_curve = self._fetch_curve if self._fetch_curve is not None else download_light_curve
        try:
            uris = _within(self._time_limit, lambda: ask_uris(candidate.tic_id))
        except _TimeLimitError:
            raise SourceUnavailableError(
                LIGHT_CURVE_ARCHIVE_NAME, "it did not answer in time"
            ) from None
        if not uris:
            return None

        curves: list[LightCurve] = []
        for uri in uris:
            try:
                curve = _within(self._time_limit, lambda u=uri: fetch_curve(u))
            except _TimeLimitError:
                raise SourceUnavailableError(
                    LIGHT_CURVE_ARCHIVE_NAME, "it did not answer in time"
                ) from None
            curves.append(curve)

        combined = concat_light_curves(curves)
        source = Source(
            name=LIGHT_CURVE_ARCHIVE_NAME,
            url=mast_download_link(uris[0]),
            retrieved=self._today(),
        )
        return measure_transits(
            combined,
            period_days=candidate.period_days,
            epoch_btjd=candidate.epoch_btjd,
            duration_hours=candidate.duration_hours,
            source=source,
        )


def _summary(exc: Exception) -> str:
    lines = str(exc).strip().splitlines()
    return lines[0][:200] if lines else type(exc).__name__


class _TimeLimitError(Exception):
    pass


def _within[T](seconds: float, call: Callable[[], T]) -> T:
    outcome: list[tuple[bool, Any]] = []

    def run() -> None:
        try:
            outcome.append((True, call()))
        except BaseException as exc:
            outcome.append((False, exc))

    thread = threading.Thread(target=run, daemon=True, name="mast-light-curve-query")
    thread.start()
    thread.join(seconds)
    if not outcome:
        raise _TimeLimitError
    finished, value = outcome[0]
    if not finished:
        raise value
    return value
