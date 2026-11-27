"""Light-curve measurements on synthetic signals and the MAST light-curve archive (no network)."""

import io
from datetime import date

import numpy as np
import pytest
from astropy.io import fits
from helpers import SOURCE, make_entry

from tesster.models import CheckStatus
from tesster.sources import SourceNotConnectedError, SourceUnavailableError
from tesster.sources.base import LIGHT_CURVE_ARCHIVE_NAME
from tesster.sources.light_curves import (
    LightCurve,
    MastLightCurves,
    detrend_light_curve,
    fold_phase,
    mast_download_link,
    measure_transits,
    parse_fits_light_curve,
)
from tesster.vetting import checks

TODAY = date(2026, 11, 15)


def synthetic_light_curve(
    *,
    period_days: float = 3.0,
    epoch_btjd: float = 2000.0,
    duration_hours: float = 2.4,
    odd_depth_ppm: float = 2000.0,
    even_depth_ppm: float = 2000.0,
    secondary_depth_ppm: float = 0.0,
    noise_ppm: float = 40.0,
    trend_ppm: float = 0.0,
    span_days: float = 27.0,
) -> LightCurve:
    """A synthetic 2-minute cadence TESS light curve with known odd, even and secondary dips."""
    rng = np.random.default_rng(42)
    cadence_days = 2.0 / (24.0 * 60.0)
    time = np.arange(epoch_btjd - 1.0, epoch_btjd + span_days, cadence_days)
    dur_days = duration_hours / 24.0

    flux = np.ones_like(time)
    if trend_ppm:
        flux += (trend_ppm / 1e6) * np.sin(2.0 * np.pi * (time - epoch_btjd) / 9.0)

    cycles = np.round((time - epoch_btjd) / period_days).astype(int)
    dt = time - (epoch_btjd + cycles * period_days)
    in_primary = np.abs(dt) <= 0.45 * dur_days
    odd_mask = in_primary & (cycles % 2 != 0)
    even_mask = in_primary & (cycles % 2 == 0)
    flux[odd_mask] -= odd_depth_ppm / 1e6
    flux[even_mask] -= even_depth_ppm / 1e6

    dt_sec = fold_phase(time, period_days, epoch_btjd + 0.5 * period_days)
    in_secondary = np.abs(dt_sec) <= 0.45 * dur_days
    flux[in_secondary] -= secondary_depth_ppm / 1e6

    err = np.full_like(time, noise_ppm / 1e6)
    flux += rng.normal(0.0, noise_ppm / 1e6, size=len(time))
    return LightCurve(time=time, flux=flux, flux_err=err)


def test_planet_like_synthetic_light_curve_passes_odd_even_and_secondary_tests():
    lc = synthetic_light_curve(odd_depth_ppm=2400.0, even_depth_ppm=2400.0, secondary_depth_ppm=0.0)
    metrics = measure_transits(
        lc, period_days=3.0, epoch_btjd=2000.0, duration_hours=2.4, source=SOURCE
    )

    assert metrics is not None
    assert metrics.odd_transits >= 4
    assert metrics.even_transits >= 4
    assert metrics.odd_depth_ppm == pytest.approx(2400.0, abs=80.0)
    assert metrics.even_depth_ppm == pytest.approx(2400.0, abs=80.0)
    assert abs(metrics.secondary_depth_ppm) < 80.0
    assert checks.odd_even_check(metrics, "why").status is CheckStatus.PASSED
    assert checks.secondary_eclipse_check(metrics, "why").status is CheckStatus.PASSED


def test_alternating_odd_and_even_dips_are_detected():
    lc = synthetic_light_curve(odd_depth_ppm=3500.0, even_depth_ppm=1800.0)
    metrics = measure_transits(
        lc, period_days=3.0, epoch_btjd=2000.0, duration_hours=2.4, source=SOURCE
    )

    assert metrics is not None
    assert metrics.odd_depth_ppm == pytest.approx(3500.0, abs=100.0)
    assert metrics.even_depth_ppm == pytest.approx(1800.0, abs=100.0)
    assert checks.odd_even_check(metrics, "why").status is CheckStatus.FAILED


def test_secondary_eclipse_is_detected():
    lc = synthetic_light_curve(
        odd_depth_ppm=8000.0, even_depth_ppm=8000.0, secondary_depth_ppm=800.0
    )
    metrics = measure_transits(
        lc, period_days=3.0, epoch_btjd=2000.0, duration_hours=2.4, source=SOURCE
    )

    assert metrics is not None
    assert metrics.secondary_depth_ppm == pytest.approx(800.0, abs=80.0)
    assert checks.secondary_eclipse_check(metrics, "why").status is CheckStatus.FAILED


def test_slow_trend_is_removed_before_measuring_depths():
    lc = synthetic_light_curve(
        odd_depth_ppm=2000.0,
        even_depth_ppm=2000.0,
        secondary_depth_ppm=0.0,
        trend_ppm=5000.0,
    )
    detrended = detrend_light_curve(lc, period_days=3.0, epoch_btjd=2000.0, duration_hours=2.4)
    metrics = measure_transits(
        detrended, period_days=3.0, epoch_btjd=2000.0, duration_hours=2.4, source=SOURCE
    )

    assert metrics is not None
    assert metrics.odd_depth_ppm == pytest.approx(2000.0, abs=100.0)
    assert metrics.even_depth_ppm == pytest.approx(2000.0, abs=100.0)
    assert checks.odd_even_check(metrics, "why").status is CheckStatus.PASSED
    assert checks.secondary_eclipse_check(metrics, "why").status is CheckStatus.PASSED


def test_single_transit_gives_one_count_and_unclear_odd_even_result():
    lc = synthetic_light_curve(
        period_days=10.0,
        epoch_btjd=2002.0,
        odd_depth_ppm=3000.0,
        even_depth_ppm=3000.0,
        span_days=4.0,
    )
    metrics = measure_transits(
        lc, period_days=10.0, epoch_btjd=2002.0, duration_hours=2.4, source=SOURCE
    )

    assert metrics is not None
    assert (metrics.odd_transits, metrics.even_transits) == (0, 1)
    assert checks.odd_even_check(metrics, "why").status is CheckStatus.UNCLEAR


def test_mast_archive_caches_measurements_per_candidate():
    """The odd-even and secondary-eclipse tests both ask for transit_metrics; the archive
    downloads and measures the light curve only once per candidate."""
    calls: list[str] = []
    uri = "mast:TESS/product/tess2018263035959-s0003-0000000259377017-0123-s_lc.fits"
    lc = synthetic_light_curve(odd_depth_ppm=3400.0, even_depth_ppm=3400.0)

    def ask_uris(tic_id: int) -> list[str]:
        calls.append(f"uris:{tic_id}")
        return [uri]

    def fetch_curve(requested_uri: str) -> LightCurve:
        calls.append(f"fetch:{requested_uri}")
        return lc

    archive = MastLightCurves(ask_uris=ask_uris, fetch_curve=fetch_curve, today=lambda: TODAY)
    entry = make_entry(tic_id=259377017, period_days=3.0, epoch_btjd=2000.0, duration_hours=2.4)

    first = archive.transit_metrics(entry)
    second = archive.transit_metrics(entry)

    assert first is not None
    assert second == first
    assert calls == ["uris:259377017", f"fetch:{uri}"]
    assert first.source.name == LIGHT_CURVE_ARCHIVE_NAME
    assert first.source.url == mast_download_link(uri)
    assert first.source.retrieved == TODAY
    assert not set(first.source.url) & set(" ()<>")


def test_mast_archive_returns_none_when_no_light_curve_exists():
    archive = MastLightCurves(ask_uris=lambda tic_id: [], fetch_curve=lambda uri: pytest.fail())
    assert archive.transit_metrics(make_entry()) is None


def test_centroid_remains_not_connected_until_package_a_provides_it():
    archive = MastLightCurves(ask_uris=lambda tic_id: [])
    with pytest.raises(SourceNotConnectedError, match="Light-curve archive"):
        archive.centroid(make_entry())


def test_fits_parser_keeps_only_good_quality_rows():
    col_t = fits.Column(name="TIME", format="D", array=np.array([1.0, 2.0, 3.0]))
    col_f = fits.Column(name="PDCSAP_FLUX", format="D", array=np.array([100.0, 999.0, 100.0]))
    col_e = fits.Column(name="PDCSAP_FLUX_ERR", format="D", array=np.array([1.0, 1.0, 1.0]))
    col_q = fits.Column(name="QUALITY", format="J", array=np.array([0, 128, 0]))
    hdu = fits.BinTableHDU.from_columns([col_t, col_f, col_e, col_q])
    hdul = fits.HDUList([fits.PrimaryHDU(), hdu])
    buf = io.BytesIO()
    hdul.writeto(buf)

    lc = parse_fits_light_curve(buf.getvalue())

    assert list(lc.time) == [1.0, 3.0]
    assert list(lc.flux) == [1.0, 1.0]


def test_network_error_from_mast_is_reported_as_unavailable():
    def fail(tic_id: int) -> list[str]:
        raise SourceUnavailableError(LIGHT_CURVE_ARCHIVE_NAME, "MAST timeout")

    archive = MastLightCurves(ask_uris=fail)
    with pytest.raises(SourceUnavailableError, match="MAST timeout"):
        archive.transit_metrics(make_entry())
