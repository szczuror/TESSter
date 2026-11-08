"""Interfaces to the supporting actors from docs/use-cases.md.

Each outside system is a Protocol, so v1 can use placeholder data and later versions can plug
in the real archives (NASA Exoplanet Archive, ExoFOP, NASA ADS, arXiv, MAST) without touching
the rest of the code.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from tess_verifier.models import (
    CatalogEntry,
    CentroidMeasurement,
    NearbyStar,
    Paper,
    ToiId,
    TransitMetrics,
)


class SourceError(Exception):
    """Base class for problems with outside sources."""


class CandidateNotFoundError(SourceError):
    def __init__(self, toi: ToiId) -> None:
        super().__init__(f"No candidate {toi} in the exoplanet catalog.")
        self.toi = toi


class SourceUnavailableError(SourceError):
    """An outside source could not be reached (UC-01 *a)."""

    def __init__(self, source: str, detail: str) -> None:
        super().__init__(f"{source} could not be reached: {detail}")
        self.source = source
        self.detail = detail


class ExoplanetCatalog(Protocol):
    def get_candidate(self, toi: ToiId) -> CatalogEntry:
        """Return the catalog entry, or raise CandidateNotFoundError / SourceUnavailableError."""
        ...


class PaperArchive(Protocol):
    def search(self, toi: ToiId, aliases: Sequence[str] = ()) -> list[Paper]:
        """Return papers that mention the candidate, or raise SourceUnavailableError."""
        ...


class StarCatalog(Protocol):
    def stars_near(self, candidate: CatalogEntry, radius_arcmin: float) -> list[NearbyStar]:
        """Return stars within the radius of the target, or raise SourceUnavailableError."""
        ...


class LightCurveArchive(Protocol):
    def transit_metrics(self, candidate: CatalogEntry) -> TransitMetrics | None:
        """Return depths measured from the light curve, None if there is no light curve, or
        raise SourceUnavailableError."""
        ...

    def centroid(self, candidate: CatalogEntry) -> CentroidMeasurement | None:
        """Return the centroid shift during the dip, None if there are no pixel data, or raise
        SourceUnavailableError."""
        ...


@dataclass(frozen=True)
class DataSources:
    """All outside sources one check uses."""

    catalog: ExoplanetCatalog
    papers: PaperArchive
    stars: StarCatalog
    light_curves: LightCurveArchive
    placeholder: bool = False
    """True when the data are made up (v1 fixtures)."""
