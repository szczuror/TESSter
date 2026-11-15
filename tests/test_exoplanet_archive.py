"""The NASA Exoplanet Archive TOI catalog, with canned answers (no network)."""

from datetime import date

import httpx
import pytest

from tesster.models import Disposition, parse_toi
from tesster.sources import CandidateNotFoundError, SourceUnavailableError
from tesster.sources.base import CandidateIncompleteError
from tesster.sources.exoplanet_archive import CATALOG_NAME, TAP_URL, ToiCatalog

TOI_700 = parse_toi("TOI-700.01")
TODAY = date(2026, 11, 15)

ROW = {
    "toi": "700.01",
    "tid": 150428135,
    "tfopwg_disp": "CP",
    "st_tmag": 10.9102,
    "ra": 97.095717,
    "dec": -65.578615,
    "pl_orbper": 16.051106,
    "pl_tranmid": 2459303.157062,
    "pl_trandurh": 1.3968229,
    "pl_trandep": 2768.5212418,
    "st_rad": 0.419457,
    "rowupdate": "2024-02-15 10:08:02",
}
"""What the archive answered for TOI-700.01 on 2026-11-15."""


def catalog(handler) -> ToiCatalog:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return ToiCatalog(client, today=lambda: TODAY)


def answering(*rows: dict, seen: list[httpx.Request] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(200, json=list(rows))

    return handler


def test_row_becomes_a_catalog_entry():
    entry = catalog(answering(ROW)).get_candidate(TOI_700)

    assert entry.toi == TOI_700
    assert entry.tic_id == 150428135
    assert entry.tmag == 10.9102
    assert (entry.ra_deg, entry.dec_deg) == (97.095717, -65.578615)
    assert entry.period_days == 16.051106
    assert entry.epoch_btjd == 2303.157062  # the catalog gives BJD, TESS data use BTJD
    assert entry.duration_hours == 1.3968229
    assert entry.depth_ppm == 2768.5212418
    assert entry.stellar_radius_rsun == 0.419457
    assert entry.disposition is Disposition.CP
    assert entry.disposition_date == date(2024, 2, 15)
    assert entry.aliases == []


def test_source_links_to_the_query_that_was_sent():
    """FR-14: the link in the report shows the row the values came from."""
    seen: list[httpx.Request] = []
    entry = catalog(answering(ROW, seen=seen)).get_candidate(TOI_700)

    (request,) = seen
    assert str(request.url).startswith(TAP_URL)
    assert request.url.params["format"] == "json"
    assert request.url.params["query"].endswith("from toi where toi=700.01")
    assert entry.source.name == CATALOG_NAME
    assert entry.source.url == str(request.url)
    assert entry.source.retrieved == TODAY
    assert not entry.source.placeholder
    # The report puts the address into a Markdown link, which these characters would break.
    assert not set(entry.source.url) & set(" ()<>")


def test_candidate_number_keeps_its_leading_zero():
    seen: list[httpx.Request] = []
    catalog(answering(ROW, seen=seen)).get_candidate(parse_toi("TOI-1234.05"))
    assert seen[0].url.params["query"].endswith("toi=1234.05")


def test_unknown_candidate_is_not_found():
    with pytest.raises(CandidateNotFoundError, match="No candidate TOI-700.01"):
        catalog(answering()).get_candidate(TOI_700)


@pytest.mark.parametrize(
    ("changes", "missing"),
    [
        ({"pl_orbper": None}, "its orbital period"),  # seen in transit only once
        ({"pl_orbper": 0}, "its orbital period"),
        ({"pl_trandurh": None}, "its transit duration"),
        ({"pl_trandep": None, "pl_tranmid": None}, "its transit time and transit depth"),
        ({"ra": None, "dec": None}, "its coordinates"),
        ({"st_tmag": None}, "its TESS magnitude"),
    ],
)
def test_candidate_without_a_needed_value_is_incomplete(changes, missing):
    """FR-02: the user is told which value is missing."""
    with pytest.raises(CandidateIncompleteError, match=missing) as raised:
        catalog(answering(ROW | changes)).get_candidate(TOI_700)
    assert "TOI-700.01" in str(raised.value)


def test_missing_star_radius_status_and_date_are_allowed():
    row = ROW | {"st_rad": None, "tfopwg_disp": None, "rowupdate": None}
    entry = catalog(answering(row)).get_candidate(TOI_700)

    assert entry.stellar_radius_rsun is None
    assert entry.disposition is None
    assert entry.disposition_date is None


def test_unknown_status_code_is_not_given():
    entry = catalog(answering(ROW | {"tfopwg_disp": "??"})).get_candidate(TOI_700)
    assert entry.disposition is None


def timeout(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("", request=request)


def refused(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


@pytest.mark.parametrize(
    ("handler", "detail"),
    [
        (timeout, "did not answer in time"),
        (refused, "connection refused"),
        (lambda request: httpx.Response(500, text="Internal Server Error"), "HTTP 500"),
        # A query the archive rejects comes back as HTTP 400 with an XML error.
        (lambda request: httpx.Response(400, text="<VOTABLE>ORA-00904</VOTABLE>"), "HTTP 400"),
        (lambda request: httpx.Response(200, text="<html>maintenance</html>"), "not JSON"),
        (lambda request: httpx.Response(200, json={"error": "busy"}), "not a list of rows"),
    ],
)
def test_archive_problems_are_reported_as_unavailable(handler, detail):
    """UC-01 *a: a source that cannot be read is named, with what went wrong."""
    with pytest.raises(SourceUnavailableError, match=detail) as raised:
        catalog(handler).get_candidate(TOI_700)
    assert raised.value.source == CATALOG_NAME
    assert str(raised.value).startswith(f"{CATALOG_NAME} could not be reached")
