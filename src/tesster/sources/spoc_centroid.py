"""Centroid measurements from TESS SPOC Data Validation (DV) reports at MAST."""

from __future__ import annotations

import re
import warnings
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import date
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from tesster.models import CatalogEntry, CentroidMeasurement, Source
from tesster.sources.base import LIGHT_CURVE_ARCHIVE_NAME, SourceUnavailableError
from tesster.sources.exoplanet_archive import (
    TIME_LIMIT_SECONDS,
    _number,
    _summary,
    _text,
    _TimeLimitError,
    _within,
)

if TYPE_CHECKING:
    from astropy.table import Table

MAST_DOWNLOAD_URL = "https://mast.stsci.edu/api/v0.1/Download/file"
_DVR_NAME_RE = re.compile(r"-s(\d{4})-s(\d{4})-\d+-(\d+)_dvr\.xml$")
_PERIOD_TOLERANCE = 0.05
MAX_DVR_FILES = 5
"""At most this many DV reports are read per candidate, best ranked first.

A star seen in many sectors can have dozens of reports. The multi-sector ones come first and
cover the same signals, so reading all of them would only make the check slow.
"""


def ask_spoc_dvr_uris(tic_id: int) -> list[str]:
    """Return MAST dataURIs of SPOC ``_dvr.xml`` files for ``tic_id``, best multi-sector first."""
    import requests
    from astroquery import exceptions as astroquery_errors
    from astroquery.mast import Observations

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", astroquery_errors.NoResultsWarning)
            obs = Observations.query_criteria(
                obs_collection="TESS",
                dataproduct_type="timeseries",
                target_name=str(tic_id),
                provenance_name="SPOC",
            )
            if obs is None or len(obs) == 0:
                return []
            products = Observations.get_product_list(obs)
    except (
        astroquery_errors.InvalidQueryError,
        astroquery_errors.RemoteServiceError,
        astroquery_errors.TimeoutError,
        requests.RequestException,
    ) as exc:
        raise SourceUnavailableError(LIGHT_CURVE_ARCHIVE_NAME, _summary(exc)) from exc

    return rank_dvr_uris(products)


def fetch_dvr_xml(data_uri: str) -> str:
    """Download one SPOC ``_dvr.xml`` report from MAST, or raise SourceUnavailableError."""
    import requests

    try:
        response = requests.get(dvr_download_link(data_uri), timeout=TIME_LIMIT_SECONDS)
        response.raise_for_status()
        return response.text
    except requests.RequestException as exc:
        raise SourceUnavailableError(LIGHT_CURVE_ARCHIVE_NAME, _summary(exc)) from exc


def rank_dvr_uris(products: Table | list[dict[str, Any]] | None) -> list[str]:
    """Filter ``_dvr.xml`` products and order them by largest sector span, then latest sector."""
    if products is None or len(products) == 0:
        return []
    found: dict[str, tuple[int, int, int, str]] = {}
    for row in products:
        filename = _text(row["productFilename"])
        uri = _text(row["dataURI"])
        if not filename.endswith("_dvr.xml") or not uri:
            continue
        found[uri] = _dvr_rank_key(filename)
    return [uri for uri, _ in sorted(found.items(), key=lambda item: item[1], reverse=True)]


def _dvr_rank_key(filename: str) -> tuple[int, int, int, str]:
    match = _DVR_NAME_RE.search(filename)
    if not match:
        return (-1, -1, -1, filename)
    start_sector, end_sector, run_id = int(match[1]), int(match[2]), int(match[3])
    return (end_sector - start_sector, end_sector, run_id, filename)


def dvr_download_link(data_uri: str) -> str:
    """A browser-resolvable MAST download link for a product URI (FR-14)."""
    return f"{MAST_DOWNLOAD_URL}?uri={quote(data_uri, safe=':/_-.')}"


class SpocCentroidArchive:
    """The centroid half of ``LightCurveArchive``, from SPOC DV reports at MAST.

    ``MastLightCurves`` measures the transits and passes centroid requests here.
    """

    def __init__(
        self,
        list_uris: Callable[[int], list[str]] = ask_spoc_dvr_uris,
        fetch_xml: Callable[[str], str] = fetch_dvr_xml,
        today: Callable[[], date] = date.today,
        time_limit: float = TIME_LIMIT_SECONDS,
    ) -> None:
        self._list_uris = list_uris
        self._fetch_xml = fetch_xml
        self._today = today
        self._time_limit = time_limit

    def centroid(self, candidate: CatalogEntry) -> CentroidMeasurement | None:
        try:
            uris = _within(self._time_limit, lambda: self._list_uris(candidate.tic_id))
        except _TimeLimitError:
            raise SourceUnavailableError(
                LIGHT_CURVE_ARCHIVE_NAME, "it did not answer in time"
            ) from None

        # One report that cannot be downloaded does not stop the search: the next one may hold
        # the result. Only when no report gave a result and some could not be read is the
        # archive reported as unavailable, because a missing report may have held it.
        problem: SourceUnavailableError | None = None
        for uri in uris[:MAX_DVR_FILES]:
            try:
                xml_text = _within(self._time_limit, lambda u=uri: self._fetch_xml(u))
            except _TimeLimitError:
                problem = SourceUnavailableError(
                    LIGHT_CURVE_ARCHIVE_NAME, "it did not answer in time"
                )
                continue
            except SourceUnavailableError as exc:
                problem = exc
                continue
            parsed = parse_dvr_centroid(xml_text, candidate)
            if parsed is not None:
                offset, err = parsed
                return CentroidMeasurement(
                    offset_arcsec=offset,
                    offset_err_arcsec=err,
                    source=Source(
                        name=LIGHT_CURVE_ARCHIVE_NAME,
                        url=dvr_download_link(uri),
                        retrieved=self._today(),
                    ),
                )
        if problem is not None:
            raise problem
        return None


def parse_dvr_centroid(xml_text: str, candidate: CatalogEntry) -> tuple[float, float] | None:
    """Extract ``(offset_arcsec, offset_err_arcsec)`` for ``candidate`` from a SPOC ``_dvr.xml``."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    planet_results = [child for child in root if _local_tag(child.tag) == "planetResults"]
    if not planet_results:
        return None

    matched = _match_planet_results(planet_results, candidate)
    if matched is None:
        return None

    sky_offset = _find_path(
        matched,
        (
            "centroidResults",
            "differenceImageMotionResults",
            "msTicCentroidOffsets",
            "meanSkyOffset",
        ),
    )
    if sky_offset is None:
        return None

    offset = _number(sky_offset.attrib.get("value"))
    err = _number(sky_offset.attrib.get("uncertainty"))
    if offset is None or err is None or offset < 0 or err <= 0:
        return None
    return offset, err


def _match_planet_results(
    planet_results: list[ET.Element], candidate: CatalogEntry
) -> ET.Element | None:
    expected_toi = f"{candidate.toi.star}.{candidate.toi.candidate:02d}"
    for pr in planet_results:
        if pr.attrib.get("toiId", "").strip() == expected_toi:
            return pr

    scored: list[tuple[float, ET.Element]] = []
    for pr in planet_results:
        period = _planet_result_period(pr)
        if period is not None and period > 0:
            rel_diff = abs(period - candidate.period_days) / candidate.period_days
            if rel_diff <= _PERIOD_TOLERANCE:
                scored.append((rel_diff, pr))
    if scored:
        scored.sort(key=lambda item: item[0])
        return scored[0][1]

    # A lone result is used only when its period cannot be read. A lone result with a known
    # period that does not match is a different signal, and its offset says nothing about
    # this candidate (FR-07).
    if len(planet_results) == 1 and _planet_result_period(planet_results[0]) is None:
        return planet_results[0]
    return None


def _planet_result_period(pr: ET.Element) -> float | None:
    pc = _find_path(pr, ("planetCandidate",))
    if pc is not None:
        period = _number(pc.attrib.get("orbitalPeriodInDays"))
        if period is not None and period > 0:
            return period
    fit = _find_path(pr, ("allTransitsFit", "modelParameters"))
    if fit is not None:
        for param in fit:
            if (
                _local_tag(param.tag) == "modelParameter"
                and param.attrib.get("name") == "orbitalPeriodDays"
            ):
                return _number(param.attrib.get("value"))
    return None


def _find_path(element: ET.Element, path: tuple[str, ...]) -> ET.Element | None:
    current: ET.Element | None = element
    for name in path:
        if current is None:
            return None
        current = next((c for c in current if _local_tag(c.tag) == name), None)
    return current


def _local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
