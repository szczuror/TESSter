"""SPOC Data Validation (DV) centroid source, with canned answers (no network)."""

import threading
from datetime import date

import numpy as np
import pytest
import requests
from astropy.table import Table
from astroquery.exceptions import InvalidQueryError, RemoteServiceError
from astroquery.mast import Observations
from helpers import make_entry

from tesster.models import parse_toi
from tesster.sources import SourceNotConnectedError, SourceUnavailableError
from tesster.sources.base import LIGHT_CURVE_ARCHIVE_NAME
from tesster.sources.spoc_centroid import (
    MAST_DOWNLOAD_URL,
    SpocCentroidArchive,
    dvr_download_link,
    rank_dvr_uris,
)

TODAY = date(2026, 11, 15)
SAMPLE_URI = "mast:TESS/product/tess2019199201929-s0014-s0086-0000000274662200-00971_dvr.xml"


def dvr_xml(
    *,
    toi_id: str | None = "1285.01",
    period_days: float = 1.2293,
    offset: float = 19.35,
    uncertainty: float = 2.70,
    extra_planet: tuple[str | None, float, float, float] | None = None,
) -> str:
    def planet_block(num: int, toi: str | None, period: float, val: float, err: float) -> str:
        toi_attr = f' toiId="{toi}"' if toi is not None else ""
        return f"""
        <planetResults planetNumber="{num}"{toi_attr}>
          <planetCandidate orbitalPeriodInDays="{period}" />
          <centroidResults>
            <differenceImageMotionResults>
              <msTicCentroidOffsets>
                <meanSkyOffset value="{val}" uncertainty="{err}" />
              </msTicCentroidOffsets>
            </differenceImageMotionResults>
          </centroidResults>
        </planetResults>
        """

    blocks = [planet_block(1, toi_id, period_days, offset, uncertainty)]
    if extra_planet is not None:
        blocks.append(planet_block(2, *extra_planet))
    return (
        '<dvTargetResults xmlns="http://www.nasa.gov/2018/TESS/DV">'
        + "".join(blocks)
        + "</dvTargetResults>"
    )


def products_table(*rows: tuple[str, str]) -> Table:
    table = Table()
    table["productFilename"] = np.array([r[0] for r in rows], dtype="U96")
    table["dataURI"] = np.array([r[1] for r in rows], dtype="U128")
    return table


def test_dvr_xml_yields_a_centroid_measurement_with_a_resolvable_link():
    archive = SpocCentroidArchive(
        list_uris=lambda tic_id: [SAMPLE_URI],
        fetch_xml=lambda uri: dvr_xml(offset=19.35, uncertainty=2.70),
        today=lambda: TODAY,
    )
    entry = make_entry(toi=parse_toi("TOI-1285.01"), tic_id=274662200, period_days=1.2293)

    measurement = archive.centroid(entry)

    assert measurement is not None
    assert measurement.offset_arcsec == 19.35
    assert measurement.offset_err_arcsec == 2.70
    assert measurement.source.name == LIGHT_CURVE_ARCHIVE_NAME
    assert measurement.source.retrieved == TODAY
    assert not measurement.source.placeholder
    assert measurement.source.url == dvr_download_link(SAMPLE_URI)
    assert measurement.source.url.startswith(MAST_DOWNLOAD_URL)
    assert not set(measurement.source.url) & set(" ()<>")


def test_multi_planet_dvr_matches_candidate_by_period_when_toi_id_is_absent():
    """TOI-270 has three candidates in one dvr.xml without toiId attributes."""
    xml = dvr_xml(
        toi_id=None,
        period_days=11.38,
        offset=2.86,
        uncertainty=2.53,
        extra_planet=(None, 5.6605, 1.27, 2.52),
    )
    archive = SpocCentroidArchive(
        list_uris=lambda tic_id: [SAMPLE_URI],
        fetch_xml=lambda uri: xml,
        today=lambda: TODAY,
    )
    entry = make_entry(toi=parse_toi("TOI-270.01"), tic_id=259377017, period_days=5.6605)

    measurement = archive.centroid(entry)

    assert measurement is not None
    assert measurement.offset_arcsec == 1.27
    assert measurement.offset_err_arcsec == 2.52


def test_dvr_uris_are_ranked_by_largest_sector_span_then_latest_sector():
    table = products_table(
        (
            "tess2024058043424-s0076-s0076-0000000274662200-00856_dvr.xml",
            "mast:TESS/product/s76_dvr.xml",
        ),
        (
            "tess2019199201929-s0014-s0086-0000000274662200-00971_dvr.xml",
            "mast:TESS/product/s14-s86_dvr.xml",
        ),
        (
            "tess2019199201929-s0014-s0078-0000000274662200-00929_dvr.xml",
            "mast:TESS/product/s14-s78_dvr.xml",
        ),
        (
            "tess2019199201929-s0014-s0086-0000000274662200-00971_dvr.pdf",
            "mast:TESS/product/s14-s86_dvr.pdf",
        ),
    )

    assert rank_dvr_uris(table) == [
        "mast:TESS/product/s14-s86_dvr.xml",
        "mast:TESS/product/s14-s78_dvr.xml",
        "mast:TESS/product/s76_dvr.xml",
    ]


def test_candidate_without_spoc_dv_products_returns_none():
    archive = SpocCentroidArchive(list_uris=lambda tic_id: [], fetch_xml=lambda uri: "")
    assert archive.centroid(make_entry()) is None


def test_unusable_spoc_uncertainty_falls_back_to_next_dvr_or_none():
    """SPOC writes uncertainty=-1.0 when a centroid offset could not be measured."""
    archive = SpocCentroidArchive(
        list_uris=lambda tic_id: ["mast:TESS/product/bad_dvr.xml", SAMPLE_URI],
        fetch_xml=lambda uri: (
            dvr_xml(offset=0.0, uncertainty=-1.0)
            if "bad" in uri
            else dvr_xml(offset=0.8, uncertainty=2.5)
        ),
    )
    measurement = archive.centroid(make_entry(toi=parse_toi("TOI-1285.01"), period_days=1.2293))
    assert measurement is not None
    assert measurement.offset_arcsec == 0.8


def test_transit_metrics_remain_not_connected_until_package_b():
    archive = SpocCentroidArchive(list_uris=lambda tic_id: [])
    with pytest.raises(SourceNotConnectedError):
        archive.transit_metrics(make_entry())


def test_archive_that_does_not_answer_is_given_up_on():
    release = threading.Event()
    slow = SpocCentroidArchive(lambda tic_id: release.wait(30), time_limit=0.05)
    try:
        with pytest.raises(SourceUnavailableError, match="did not answer in time"):
            slow.centroid(make_entry())
    finally:
        release.set()


@pytest.mark.parametrize(
    ("error", "detail"),
    [
        (InvalidQueryError("MAST observations failed"), "MAST observations failed"),
        (RemoteServiceError("503 Service Unavailable"), "503 Service Unavailable"),
        (requests.ConnectionError("connection refused"), "connection refused"),
    ],
)
def test_archive_problems_are_reported_as_unavailable(monkeypatch, error, detail):
    def query_criteria(**kwargs):
        raise error

    monkeypatch.setattr(Observations, "query_criteria", query_criteria)
    with pytest.raises(SourceUnavailableError, match=detail) as raised:
        SpocCentroidArchive().centroid(make_entry())
    assert raised.value.source == LIGHT_CURVE_ARCHIVE_NAME


def test_lone_dv_result_with_a_different_period_is_not_used():
    """A lone DV result whose period does not match is another signal, not this candidate."""
    archive = SpocCentroidArchive(
        list_uris=lambda tic_id: [SAMPLE_URI],
        fetch_xml=lambda uri: dvr_xml(toi_id=None, period_days=11.3, offset=4.0, uncertainty=0.8),
    )
    entry = make_entry(toi=parse_toi("TOI-1285.01"), period_days=2.1)

    assert archive.centroid(entry) is None


def test_lone_dv_result_without_a_period_is_used():
    xml = dvr_xml(toi_id=None, offset=0.9, uncertainty=2.1).replace(
        '<planetCandidate orbitalPeriodInDays="1.2293" />', ""
    )
    archive = SpocCentroidArchive(list_uris=lambda tic_id: [SAMPLE_URI], fetch_xml=lambda uri: xml)

    measurement = archive.centroid(make_entry(period_days=2.1))

    assert measurement is not None
    assert measurement.offset_arcsec == 0.9
