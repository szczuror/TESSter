"""Outside data sources (supporting actors in docs/use-cases.md)."""

from tesster.sources import http
from tesster.sources.base import (
    CandidateIncompleteError,
    CandidateNotFoundError,
    DataSources,
    SourceError,
    SourceNotConnectedError,
    SourceUnavailableError,
)
from tesster.sources.exoplanet_archive import ToiCatalog
from tesster.sources.fake import fake_sources
from tesster.sources.not_connected import NotConnected


def build_sources() -> DataSources:
    """The sources every check uses: the online archives.

    Only the candidate catalog is connected so far. The other sources report themselves as not
    connected, which the report shows under Problems. The placeholder data (``fake_sources``)
    are for tests only.
    """
    not_connected = NotConnected()
    return DataSources(
        catalog=ToiCatalog(http.new_client()),
        papers=not_connected,
        stars=not_connected,
        light_curves=not_connected,
    )


__all__ = [
    "CandidateIncompleteError",
    "CandidateNotFoundError",
    "DataSources",
    "SourceError",
    "SourceNotConnectedError",
    "SourceUnavailableError",
    "build_sources",
    "fake_sources",
]
