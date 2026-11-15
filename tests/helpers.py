import httpx

from tesster.models import CatalogEntry, Source, ToiId
from tesster.sources import CandidateNotFoundError, DataSources
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


def archive_client(handler) -> httpx.Client:
    """An HTTP client that gets its answers from ``handler`` and never opens a connection."""
    return httpx.Client(transport=httpx.MockTransport(handler))


def archive_answering(*rows: dict, seen: list[httpx.Request] | None = None) -> httpx.Client:
    """A client whose archive answers every query with these rows."""

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(200, json=list(rows))

    return archive_client(handler)
