"""The candidate catalog: the TOI table of the NASA Exoplanet Archive, read through its TAP
service (UC-01 step 2)."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import date
from typing import Any

import httpx

from tesster.models import CatalogEntry, Disposition, Source, ToiId
from tesster.sources.base import (
    CandidateIncompleteError,
    CandidateNotFoundError,
    SourceUnavailableError,
)

CATALOG_NAME = "NASA Exoplanet Archive, TOI table"
TAP_URL = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"

BTJD_ZERO_BJD = 2_457_000.0
"""BTJD, the time scale of TESS data, is BJD minus this number. The catalog gives BJD."""

COLUMNS = (
    "toi",
    "tid",
    "tfopwg_disp",
    "st_tmag",
    "ra",
    "dec",
    "pl_orbper",
    "pl_tranmid",
    "pl_trandurh",
    "pl_trandep",
    "st_rad",
    "rowupdate",
)

_NEEDED = {
    "tid": "TIC number",
    "ra": "coordinates",
    "dec": "coordinates",
    "st_tmag": "TESS magnitude",
    "pl_orbper": "orbital period",
    "pl_tranmid": "transit time",
    "pl_trandurh": "transit duration",
    "pl_trandep": "transit depth",
}
"""Columns no check can do without, with the name the user is told when one is empty (FR-02).
The catalog has no period for candidates seen in transit only once."""

_MUST_BE_POSITIVE = ("pl_orbper", "pl_trandurh", "pl_trandep")


class ToiCatalog:
    """Implements ExoplanetCatalog with one TAP query per candidate."""

    def __init__(self, client: httpx.Client, today: Callable[[], date] = date.today) -> None:
        self._client = client
        self._today = today

    def get_candidate(self, toi: ToiId) -> CatalogEntry:
        url = query_url(toi)
        rows = self._rows(url)
        if not rows:
            raise CandidateNotFoundError(toi)
        return self._entry(toi, rows[0], url)

    def _rows(self, url: httpx.URL) -> list[dict[str, Any]]:
        try:
            response = self._client.get(url)
            response.raise_for_status()
            rows = response.json()
        except httpx.TimeoutException as exc:
            raise SourceUnavailableError(CATALOG_NAME, "it did not answer in time") from exc
        except httpx.HTTPStatusError as exc:
            raise SourceUnavailableError(
                CATALOG_NAME, f"it answered with HTTP {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            raise SourceUnavailableError(CATALOG_NAME, str(exc) or type(exc).__name__) from exc
        except ValueError as exc:
            raise SourceUnavailableError(CATALOG_NAME, "its answer was not JSON") from exc
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise SourceUnavailableError(CATALOG_NAME, "its answer was not a list of rows")
        return rows

    def _entry(self, toi: ToiId, row: dict[str, Any], url: httpx.URL) -> CatalogEntry:
        numbers = {column: _number(row.get(column)) for column in (*_NEEDED, "st_rad")}
        for column in _MUST_BE_POSITIVE:
            if numbers[column] is not None and numbers[column] <= 0:
                numbers[column] = None
        missing = list(dict.fromkeys(what for c, what in _NEEDED.items() if numbers[c] is None))
        if missing:
            raise CandidateIncompleteError(toi, missing)
        radius = numbers["st_rad"]
        return CatalogEntry(
            toi=toi,
            tic_id=int(numbers["tid"]),
            tmag=numbers["st_tmag"],
            ra_deg=numbers["ra"],
            dec_deg=numbers["dec"],
            period_days=numbers["pl_orbper"],
            epoch_btjd=round(numbers["pl_tranmid"] - BTJD_ZERO_BJD, 6),
            duration_hours=numbers["pl_trandurh"],
            depth_ppm=numbers["pl_trandep"],
            stellar_radius_rsun=radius if radius is not None and radius > 0 else None,
            disposition=_disposition(row.get("tfopwg_disp")),
            disposition_date=_day(row.get("rowupdate")),
            source=Source(name=CATALOG_NAME, url=str(url), retrieved=self._today()),
        )


def query_url(toi: ToiId) -> httpx.URL:
    """The query for one candidate. The report links to it, so the reader sees the same row."""
    # ToiId holds two integers, so nothing the user typed reaches the query text.
    query = f"select {','.join(COLUMNS)} from toi where toi={toi.star}.{toi.candidate:02d}"
    return httpx.URL(TAP_URL, params={"query": query, "format": "json"})


def _number(value: object) -> float | None:
    """The value as a finite number, or None when the catalog leaves it empty."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _disposition(value: object) -> Disposition | None:
    try:
        return Disposition(value)
    except ValueError:
        return None


def _day(value: object) -> date | None:
    """The day of a catalog timestamp such as ``2024-02-15 10:08:02``."""
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None
