"""Outside data sources (supporting actors in docs/use-cases.md)."""

from __future__ import annotations

from pathlib import Path

from tesster.sources.base import (
    CandidateIncompleteError,
    CandidateNotFoundError,
    DataSources,
    SourceError,
    SourceNotConnectedError,
    SourceUnavailableError,
)
from tesster.sources.exoplanet_archive import ToiCatalog, ask_planets
from tesster.sources.fake import fake_sources
from tesster.sources.light_curves import MastLightCurves
from tesster.sources.not_connected import NotConnected
from tesster.sources.papers import ArxivPapers
from tesster.sources.saved import SAVED_DIR, save_candidate, use_saved


def online_sources() -> DataSources:
    """The live online archives, without the saved-data replay layer."""
    not_connected = NotConnected()
    return DataSources(
        catalog=ToiCatalog(ask_planets=ask_planets),
        papers=ArxivPapers(),
        stars=not_connected,
        light_curves=MastLightCurves(centroids=not_connected),
    )


def build_sources(saved_dir: Path | None = SAVED_DIR) -> DataSources:
    """The sources every check uses: saved archive answers when available, online archives
    otherwise.

    The candidate catalog (NASA Exoplanet Archive), the paper archive (arXiv) and light-curve
    transit measurements (MAST) are connected. The star catalog and centroid measurements
    (Package A) still report themselves as not connected, which the report shows under Problems.
    The placeholder data (``fake_sources``) are for tests only.
    """
    sources = online_sources()
    return use_saved(sources, saved_dir) if saved_dir is not None else sources


__all__ = [
    "CandidateIncompleteError",
    "CandidateNotFoundError",
    "DataSources",
    "SAVED_DIR",
    "SourceError",
    "SourceNotConnectedError",
    "SourceUnavailableError",
    "build_sources",
    "fake_sources",
    "online_sources",
    "save_candidate",
    "use_saved",
]
