import math

import numpy as np
from astropy.table import QTable, Table

from tesster.models import CatalogEntry, Source, ToiId
from tesster.sources import CandidateNotFoundError, DataSources
from tesster.sources.exoplanet_archive import COLUMNS
from tesster.sources.not_connected import NotConnected

SOURCE = Source(name="Test catalog", url="https://example.org/catalog")

TOI_700_ROW = {
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
"""What the NASA Exoplanet Archive answered for TOI-700.01 on 2026-11-15."""

_TEXT_COLUMNS = {"toi": "U8", "tfopwg_disp": "U3", "rowupdate": "U19"}
_UNITS = {
    "ra": "deg",
    "dec": "deg",
    "pl_orbper": "d",
    "pl_trandurh": "h",
    "pl_trandep": "ppm",
    "st_rad": "solRad",
}


def make_entry(**overrides) -> CatalogEntry:
    values = {
        "toi": ToiId(star=1234, candidate=1),
        "tic_id": 1,
        "tmag": 10.0,
        "ra_deg": 0.0,
        "dec_deg": 0.0,
        "period_days": 3.0,
        "epoch_btjd": 2000.0,
        "duration_hours": 2.0,
        "depth_ppm": 1000.0,
        "stellar_radius_rsun": 1.0,
        "source": SOURCE,
    }
    values.update(overrides)
    return CatalogEntry(**values)


class OneCandidate:
    """A catalog that lists a single candidate."""

    def __init__(self, entry: CatalogEntry) -> None:
        self.entry = entry

    def get_candidate(self, toi: ToiId) -> CatalogEntry:
        if toi != self.entry.toi:
            raise CandidateNotFoundError(toi)
        return self.entry


def catalog_only(entry: CatalogEntry) -> DataSources:
    """Sources as ``tesster check`` has them now: the catalog is connected, the paper archive,
    the star catalog and the light-curve archive are not."""
    off = NotConnected()
    return DataSources(catalog=OneCandidate(entry), papers=off, stars=off, light_curves=off)


def toi_table(*rows: dict) -> QTable:
    """Rows of the TOI table in the form astroquery returns them (seen on 2026-11-15).

    Some columns carry units, the table is masked but nothing in it is, and a value the archive
    does not have (``None`` here) is NaN for a number and an empty string for a text.
    """
    plain = Table(masked=True)
    for name in COLUMNS:
        if name in _TEXT_COLUMNS:
            values = ["" if row[name] is None else row[name] for row in rows]
            plain[name] = np.array(values, dtype=_TEXT_COLUMNS[name])
        else:
            values = [math.nan if row[name] is None else row[name] for row in rows]
            plain[name] = np.array(values, dtype="int32" if name == "tid" else "float64")
        if name in _UNITS:
            plain[name].unit = _UNITS[name]
    return QTable(plain, masked=True)


def answering(*rows: dict, seen: list[str] | None = None):
    """An archive that answers every query with these rows. ``seen`` collects the queries."""

    def ask(where: str) -> QTable:
        if seen is not None:
            seen.append(where)
        return toi_table(*rows)

    return ask
