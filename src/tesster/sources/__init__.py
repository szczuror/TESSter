"""Outside data sources (supporting actors in docs/use-cases.md)."""

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
from tesster.sources.spoc_centroid import SpocCentroidArchive
from tesster.sources.tic import TicStarCatalog


def build_sources() -> DataSources:
    """The sources every check uses: the online archives.

    The candidate catalog, the star catalog and the SPOC centroid measurement are connected.
    The other sources (papers, light-curve transit metrics) report themselves as not connected,
    which the report shows under Problems. The placeholder data (``fake_sources``) are for
    tests only.
    """
    not_connected = NotConnected()
    return DataSources(
        catalog=ToiCatalog(),
        papers=not_connected,
        stars=TicStarCatalog(),
        light_curves=SpocCentroidArchive(transits=not_connected),
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
