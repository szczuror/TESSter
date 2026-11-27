"""The candidate catalog: the TOI table of the NASA Exoplanet Archive, read with astroquery
(UC-01 step 2)."""

from __future__ import annotations

import math
import threading
import warnings
from collections.abc import Callable
from datetime import date
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from tesster.models import CatalogEntry, Disposition, Source, ToiId
from tesster.sources.base import (
    CandidateIncompleteError,
    CandidateNotFoundError,
    SourceUnavailableError,
)

if TYPE_CHECKING:
    from astropy.table import Table

CATALOG_NAME = "NASA Exoplanet Archive, TOI table"
TABLE = "toi"
PLANET_TABLE = "pscomppars"
PLANET_COLUMNS = ("pl_name", "pl_orbper")
PLANET_PERIOD_TOLERANCE = 0.05
"""Largest relative period difference when matching a TOI to a confirmed planet of the same star."""
TAP_URL = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"

TIME_LIMIT_SECONDS = 60.0
"""How long one candidate may take. The archive usually answers in a few seconds, but astroquery
sets no time limit of its own."""

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
"""The numbers are used in the units the archive gives them in: days, hours, ppm, solar radii,
degrees."""

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


def ask_archive(where: str) -> Table:
    """Send one query to the TOI table through astroquery, or raise SourceUnavailableError."""
    return _query_table(TABLE, COLUMNS, where)


def ask_planets(tic_id: int) -> Table:
    """Read confirmed planets of ``tic_id`` from the composite planet table."""
    return _query_table(PLANET_TABLE, PLANET_COLUMNS, f"tic_id='TIC {int(tic_id)}'")


def _query_table(table: str, columns: tuple[str, ...], where: str) -> Table:
    # Imported here because astroquery takes about two seconds to load, which commands that
    # never query the archive should not wait for.
    import pyvo
    import requests
    from astroquery import exceptions as astroquery_errors
    from astroquery.ipac.nexsci.nasa_exoplanet_archive import NasaExoplanetArchive

    try:
        with warnings.catch_warnings():
            # No rows means the candidate is not in the catalog, which get_candidate reports.
            warnings.simplefilter("ignore", astroquery_errors.NoResultsWarning)
            return NasaExoplanetArchive.query_criteria(
                table=table, select=",".join(columns), where=where
            )
    except (
        # astroquery turns every failure of the query into InvalidQueryError, network errors
        # included. The others come from the list of tables it reads before the first query.
        astroquery_errors.InvalidQueryError,
        astroquery_errors.RemoteServiceError,
        astroquery_errors.TimeoutError,
        pyvo.dal.DALAccessError,
        requests.RequestException,
    ) as exc:
        raise SourceUnavailableError(CATALOG_NAME, _summary(exc)) from exc


class ToiCatalog:
    """Implements ExoplanetCatalog with one query per candidate (plus optional planet aliases)."""

    def __init__(
        self,
        ask: Callable[[str], Table] = ask_archive,
        today: Callable[[], date] = date.today,
        time_limit: float = TIME_LIMIT_SECONDS,
        ask_planets: Callable[[int], Table] | None = None,
    ) -> None:
        self._ask = ask
        self._today = today
        self._time_limit = time_limit
        self._ask_planets = ask_planets

    def get_candidate(self, toi: ToiId) -> CatalogEntry:
        # ToiId holds two integers, so nothing the user typed reaches the query text.
        where = f"toi={toi.star}.{toi.candidate:02d}"
        try:
            table = _within(self._time_limit, lambda: self._ask(where))
        except _TimeLimitError:
            raise SourceUnavailableError(CATALOG_NAME, "it did not answer in time") from None
        if len(table) == 0:
            raise CandidateNotFoundError(toi)
        entry = self._entry(toi, table[0], where)
        aliases = self._aliases(entry)
        return entry.model_copy(update={"aliases": aliases}) if aliases else entry

    def _aliases(self, entry: CatalogEntry) -> list[str]:
        if self._ask_planets is None:
            return []
        try:
            planets = _within(self._time_limit, lambda: self._ask_planets(entry.tic_id))
        except (_TimeLimitError, SourceUnavailableError):
            return []
        return planet_aliases(planets, entry.period_days, entry.toi)

    def _entry(self, toi: ToiId, row: Any, where: str) -> CatalogEntry:
        numbers = {column: _number(row[column]) for column in (*_NEEDED, "st_rad")}
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
            disposition=_disposition(_text(row["tfopwg_disp"])),
            disposition_date=_day(_text(row["rowupdate"])),
            source=Source(name=CATALOG_NAME, url=catalog_link(where), retrieved=self._today()),
        )


def catalog_link(where: str) -> str:
    """An address that shows the same row in a browser. The report links to it (FR-14)."""
    query = f"select {','.join(COLUMNS)} from {TABLE} where {where}"
    return f"{TAP_URL}?{urlencode({'query': query, 'format': 'json'})}"


def planet_aliases(table: Table, period_days: float, toi: ToiId | None = None) -> list[str]:
    """Names from the confirmed-planet table that match this candidate's orbital period."""
    colnames = set(getattr(table, "colnames", ()))
    if "pl_name" not in colnames or len(table) == 0:
        return []
    toi_label = str(toi).lower() if toi is not None else ""
    names: list[str] = []
    for row in table:
        name = _text(row["pl_name"]).strip()
        if not name or name.lower() == toi_label:
            continue
        planet_period = _number(row["pl_orbper"]) if "pl_orbper" in colnames else None
        if planet_period is None:
            if len(table) == 1 and name not in names:
                names.append(name)
            continue
        if (
            abs(planet_period - period_days) / period_days <= PLANET_PERIOD_TOLERANCE
            and name not in names
        ):
            names.append(name)
    return names


def _number(cell: Any) -> float | None:
    """A table cell as a plain finite number, or None when the archive has no value.

    A cell with a unit gives its number in that unit. The archive sends NaN for an empty number,
    which astroquery leaves unmasked.
    """
    if getattr(cell, "mask", False):
        return None
    cell = getattr(cell, "value", cell)
    try:
        number = float(cell)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _text(cell: Any) -> str:
    """A table cell as text. The archive sends an empty string for an empty text."""
    return "" if getattr(cell, "mask", False) else str(cell)


def _disposition(code: str) -> Disposition | None:
    try:
        return Disposition(code)
    except ValueError:
        return None


def _day(timestamp: str) -> date | None:
    """The day of a catalog timestamp such as ``2024-02-15 10:08:02``."""
    try:
        return date.fromisoformat(timestamp[:10])
    except ValueError:
        return None


def _summary(exc: Exception) -> str:
    """The first line of an error, short enough for one line of the report."""
    lines = str(exc).strip().splitlines()
    return lines[0][:200] if lines else type(exc).__name__


class _TimeLimitError(Exception):
    pass


def _within[T](seconds: float, call: Callable[[], T]) -> T:
    """Run a call that has no time limit of its own, and stop waiting after ``seconds``.

    The call runs in a daemon thread. If it does not finish in time, the thread is left behind
    and ends with the program.
    """
    outcome: list[tuple[bool, Any]] = []

    def run() -> None:
        try:
            outcome.append((True, call()))
        except BaseException as exc:  # raised again below, in the caller's thread
            outcome.append((False, exc))

    thread = threading.Thread(target=run, daemon=True, name="toi-catalog-query")
    thread.start()
    thread.join(seconds)
    if not outcome:
        raise _TimeLimitError
    finished, value = outcome[0]
    if not finished:
        raise value
    return value
