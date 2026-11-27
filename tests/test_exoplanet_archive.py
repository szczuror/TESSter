"""The NASA Exoplanet Archive TOI catalog, with canned answers (no network)."""

import threading
from datetime import date
from urllib.parse import parse_qs, urlsplit

import pytest
import pyvo
import requests
from astroquery.exceptions import InvalidQueryError, RemoteServiceError
from astroquery.ipac.nexsci.nasa_exoplanet_archive import NasaExoplanetArchive
from helpers import TOI_700_ROW as ROW
from helpers import answering, toi_table

from tesster.models import Disposition, parse_toi
from tesster.sources import (
    CandidateIncompleteError,
    CandidateNotFoundError,
    SourceUnavailableError,
)
from tesster.sources.exoplanet_archive import (
    CATALOG_NAME,
    COLUMNS,
    TAP_URL,
    ToiCatalog,
    planet_aliases,
)

TOI_700 = parse_toi("TOI-700.01")
TODAY = date(2026, 11, 15)


def catalog(ask) -> ToiCatalog:
    return ToiCatalog(ask, today=lambda: TODAY)


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
    # Plain numbers, so the rest of the code never meets astropy's quantities.
    assert type(entry.period_days) is float
    assert type(entry.tic_id) is int


def test_source_links_to_the_row_the_values_came_from():
    """FR-14: the link in the report shows the same row in a browser."""
    seen: list[str] = []
    entry = catalog(answering(ROW, seen=seen)).get_candidate(TOI_700)

    assert seen == ["toi=700.01"]
    address = urlsplit(entry.source.url)
    asked = parse_qs(address.query)
    assert entry.source.url.startswith(TAP_URL)
    assert asked["query"] == [f"select {','.join(COLUMNS)} from toi where toi=700.01"]
    assert asked["format"] == ["json"]
    assert entry.source.name == CATALOG_NAME
    assert entry.source.retrieved == TODAY
    assert not entry.source.placeholder
    # The report puts the address into a Markdown link, which these characters would break.
    assert not set(entry.source.url) & set(" ()<>")


def test_candidate_number_keeps_its_leading_zero():
    seen: list[str] = []
    catalog(answering(ROW, seen=seen)).get_candidate(parse_toi("TOI-1234.05"))
    assert seen == ["toi=1234.05"]


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


def test_masked_cells_count_as_empty():
    """astroquery unmasks the table today. If it stops, a masked cell must not pass as a value:
    the number under a mask is still there."""
    table = toi_table(ROW)
    for column in ("pl_orbper", "st_rad", "tfopwg_disp", "rowupdate"):
        table[column].mask[0] = True

    with pytest.raises(CandidateIncompleteError, match="its orbital period"):
        catalog(lambda where: table).get_candidate(TOI_700)

    table["pl_orbper"].mask[0] = False
    entry = catalog(lambda where: table).get_candidate(TOI_700)
    assert entry.stellar_radius_rsun is None
    assert entry.disposition is None
    assert entry.disposition_date is None


def test_archive_that_does_not_answer_is_given_up_on():
    """astroquery sets no time limit for the query, so the catalog sets one."""
    release = threading.Event()
    slow = ToiCatalog(lambda where: release.wait(30), time_limit=0.05)
    try:
        with pytest.raises(SourceUnavailableError, match="did not answer in time"):
            slow.get_candidate(TOI_700)
    finally:
        release.set()


def test_archive_is_asked_through_astroquery(monkeypatch):
    asked: list[dict] = []

    def query_criteria(**criteria):
        asked.append(criteria)
        return toi_table(ROW)

    monkeypatch.setattr(NasaExoplanetArchive, "query_criteria", query_criteria)
    entry = ToiCatalog().get_candidate(TOI_700)

    assert asked == [{"table": "toi", "select": ",".join(COLUMNS), "where": "toi=700.01"}]
    assert entry.tic_id == 150428135


@pytest.mark.parametrize(
    ("error", "detail"),
    [
        # astroquery reports every failure of the query this way, network errors included.
        (InvalidQueryError("ConnectionError: Max retries exceeded"), "Max retries exceeded"),
        (RemoteServiceError("The server is down for maintenance"), "down for maintenance"),
        # Errors from the list of tables astroquery reads before the first query.
        (pyvo.dal.DALServiceError("503 Service Unavailable"), "503 Service Unavailable"),
        (requests.ConnectionError("connection refused"), "connection refused"),
        (InvalidQueryError("ORA-00904: invalid identifier\nmore\nlines"), "invalid identifier$"),
    ],
)
def test_archive_problems_are_reported_as_unavailable(monkeypatch, error, detail):
    """UC-01 *a: a source that cannot be read is named, with what went wrong."""

    def query_criteria(**criteria):
        raise error

    monkeypatch.setattr(NasaExoplanetArchive, "query_criteria", query_criteria)
    with pytest.raises(SourceUnavailableError, match=detail) as raised:
        ToiCatalog().get_candidate(TOI_700)
    assert raised.value.source == CATALOG_NAME
    assert str(raised.value).startswith(f"{CATALOG_NAME} could not be reached")
    assert "\n" not in str(raised.value)


def test_tests_cannot_reach_the_archive():
    """The guard in conftest.py: a query without a canned answer fails the test."""
    with pytest.raises(pytest.fail.Exception, match="online archive"):
        ToiCatalog().get_candidate(TOI_700)


def test_planet_aliases_match_the_candidate_by_orbital_period():
    """When a star hosts several confirmed planets, only the one with this candidate's period
    becomes an alias."""
    from astropy.table import Table

    planets = Table(
        rows=[
            ("TOI-270 b", 3.35992),
            ("TOI-270 c", 5.66051),
            ("TOI-270 d", 11.38194),
        ],
        names=("pl_name", "pl_orbper"),
    )
    row = ROW | {"toi": "270.01", "tid": 259377017, "pl_orbper": 5.6604773}
    cat = ToiCatalog(answering(row), today=lambda: TODAY, ask_planets=lambda tic_id: planets)

    entry = cat.get_candidate(parse_toi("TOI-270.01"))

    assert entry.aliases == ["TOI-270 c"]
    assert planet_aliases(planets, 3.36, parse_toi("TOI-270.02")) == ["TOI-270 b"]
