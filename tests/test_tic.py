"""The TESS Input Catalog (TIC) at MAST, with canned answers (no network)."""

import json
import math
import threading
from datetime import date
from urllib.parse import parse_qs, urlsplit

import numpy as np
import pytest
import requests
from astropy.table import Table
from astroquery.exceptions import InvalidQueryError, RemoteServiceError
from astroquery.mast import Catalogs
from helpers import make_entry

from tesster.sources import SourceUnavailableError
from tesster.sources.base import STAR_CATALOG_NAME
from tesster.sources.tic import MAST_INVOKE_URL, TIC_CONE_SERVICE, TicStarCatalog

TODAY = date(2026, 11, 15)


def tic_table(*rows: dict) -> Table:
    """Rows of a Mast.Catalogs.Tic.Cone response (ID as text, Tmag and dstArcSec as float64)."""
    table = Table(masked=True)
    table["ID"] = np.array(["" if r.get("ID") is None else str(r["ID"]) for r in rows], dtype="U16")
    table["Tmag"] = np.array(
        [math.nan if r.get("Tmag") is None else r["Tmag"] for r in rows], dtype="float64"
    )
    table["dstArcSec"] = np.array(
        [math.nan if r.get("dstArcSec") is None else r["dstArcSec"] for r in rows],
        dtype="float64",
    )
    return table


def answering(*rows: dict, seen: list[tuple[float, float, float]] | None = None):
    def ask(ra_deg: float, dec_deg: float, radius_arcmin: float) -> Table:
        if seen is not None:
            seen.append((ra_deg, dec_deg, radius_arcmin))
        return tic_table(*rows)

    return ask


def catalog(ask) -> TicStarCatalog:
    return TicStarCatalog(ask, today=lambda: TODAY)


def test_rows_become_nearby_stars_sorted_by_separation():
    target = make_entry(tic_id=150428135, ra_deg=97.095717, dec_deg=-65.578615)
    rows = (
        {"ID": "150428140", "Tmag": 14.2, "dstArcSec": 42.5},
        {"ID": "150428138", "Tmag": 11.8, "dstArcSec": 12.0},
    )
    stars = catalog(answering(*rows)).stars_near(target, 2.5)

    assert [(s.tic_id, s.separation_arcsec, s.tmag) for s in stars] == [
        (150428138, 12.0, 11.8),
        (150428140, 42.5, 14.2),
    ]
    assert type(stars[0].tic_id) is int
    assert type(stars[0].separation_arcsec) is float
    assert type(stars[0].tmag) is float


def test_target_is_excluded_by_tic_number_even_when_offset_from_query_coordinates():
    """TOI-700 lies 3 arcsec from its TOI-table coordinates in TIC, so excluding by distance=0
    would leave the target in the neighbor list."""
    target = make_entry(tic_id=150428135)
    rows = (
        {"ID": "150428135", "Tmag": 10.9102, "dstArcSec": 3.12},
        {"ID": "150428138", "Tmag": 13.5, "dstArcSec": 28.0},
    )
    stars = catalog(answering(*rows)).stars_near(target, 2.5)

    assert [s.tic_id for s in stars] == [150428138]


def test_rows_without_usable_magnitude_or_separation_are_skipped():
    target = make_entry(tic_id=1)
    table = tic_table(
        {"ID": "2", "Tmag": None, "dstArcSec": 10.0},
        {"ID": "3", "Tmag": 12.0, "dstArcSec": None},
        {"ID": "4", "Tmag": 12.0, "dstArcSec": 200.0},  # outside 2.5 arcmin (150 arcsec)
        {"ID": "5", "Tmag": 13.0, "dstArcSec": 25.0},
        {"ID": "6", "Tmag": 14.0, "dstArcSec": 30.0},
    )
    table["Tmag"].mask[4] = True  # masked cell must also count as empty

    stars = catalog(lambda ra, dec, r: table).stars_near(target, 2.5)
    assert [s.tic_id for s in stars] == [5]


def test_source_links_to_the_mast_tic_cone_query():
    """FR-14: every nearby star shares one resolvable link to the cone search."""
    seen: list[tuple[float, float, float]] = []
    target = make_entry(tic_id=150428135, ra_deg=97.095717, dec_deg=-65.578615)
    stars = catalog(
        answering(
            {"ID": "150428138", "Tmag": 12.1, "dstArcSec": 15.0},
            {"ID": "150428140", "Tmag": 14.0, "dstArcSec": 35.0},
            seen=seen,
        )
    ).stars_near(target, 2.5)

    assert seen == [(97.095717, -65.578615, 2.5)]
    assert stars[0].source == stars[1].source
    source = stars[0].source
    assert source.name == STAR_CATALOG_NAME
    assert source.retrieved == TODAY
    assert not source.placeholder
    assert source.url.startswith(MAST_INVOKE_URL)
    assert not set(source.url) & set(" ()<>")

    parsed = parse_qs(urlsplit(source.url).query)
    payload = json.loads(parsed["request"][0])
    assert payload["service"] == TIC_CONE_SERVICE
    assert payload["params"] == {"ra": 97.095717, "dec": -65.578615, "radius": round(2.5 / 60, 6)}


def test_archive_is_asked_through_astroquery(monkeypatch):
    asked: list[dict] = []

    def query_region(coordinates, *, radius, catalog):
        asked.append({"ra": coordinates.ra.deg, "dec": coordinates.dec.deg, "catalog": catalog})
        return tic_table({"ID": "150428138", "Tmag": 12.5, "dstArcSec": 19.0})

    monkeypatch.setattr(Catalogs, "query_region", query_region)
    target = make_entry(tic_id=150428135, ra_deg=97.095717, dec_deg=-65.578615)
    stars = TicStarCatalog().stars_near(target, 2.5)

    assert asked == [{"ra": 97.095717, "dec": -65.578615, "catalog": "Tic"}]
    assert [s.tic_id for s in stars] == [150428138]


def test_archive_that_does_not_answer_is_given_up_on():
    release = threading.Event()
    slow = TicStarCatalog(lambda ra, dec, r: release.wait(30), time_limit=0.05)
    try:
        with pytest.raises(SourceUnavailableError, match="did not answer in time"):
            slow.stars_near(make_entry(), 2.5)
    finally:
        release.set()


@pytest.mark.parametrize(
    ("error", "detail"),
    [
        (InvalidQueryError("MAST service failed"), "MAST service failed"),
        (RemoteServiceError("503 Service Unavailable"), "503 Service Unavailable"),
        (requests.ConnectionError("connection refused"), "connection refused"),
    ],
)
def test_archive_problems_are_reported_as_unavailable(monkeypatch, error, detail):
    def query_region(*args, **kwargs):
        raise error

    monkeypatch.setattr(Catalogs, "query_region", query_region)
    with pytest.raises(SourceUnavailableError, match=detail) as raised:
        TicStarCatalog().stars_near(make_entry(), 2.5)
    assert raised.value.source == STAR_CATALOG_NAME
