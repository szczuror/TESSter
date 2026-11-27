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
from tesster.sources.papers import ArxivPapers
from tesster.sources.saved import SAVED_DIR, save_candidate, use_saved
from tesster.sources.spoc_centroid import SpocCentroidArchive
from tesster.sources.tic import TicStarCatalog


def online_sources() -> DataSources:
    """The live online archives, without the saved-data replay layer."""
    return DataSources(
        catalog=ToiCatalog(ask_planets=ask_planets),
        papers=ArxivPapers(),
        stars=TicStarCatalog(),
        light_curves=MastLightCurves(centroids=SpocCentroidArchive()),
    )


def build_sources(saved_dir: Path | None = SAVED_DIR) -> DataSources:
    """The sources every check uses: saved archive answers when available, online archives
    otherwise.

    All sources are connected: the candidate catalog (NASA Exoplanet Archive), the paper archive
    (arXiv), the star catalog (TIC at MAST), light-curve transit measurements (MAST) and the
    centroid measurement (SPOC Data Validation reports at MAST). The placeholder data
    (``fake_sources``) are for tests only.
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
