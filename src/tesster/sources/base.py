"""Interfaces to the supporting actors from docs/use-cases.md.

Each outside system is a Protocol, so the online archives (NASA Exoplanet Archive, ExoFOP,
NASA ADS, arXiv, MAST) and the test fixtures can be swapped without touching the rest of the
code.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from tesster.models import (
    CatalogEntry,
    CentroidMeasurement,
    NearbyStar,
    Paper,
    ToiId,
    TransitMetrics,
)

PAPER_ARCHIVE_NAME = "Paper archive (NASA ADS / arXiv)"
STAR_CATALOG_NAME = "Star catalog (TIC at MAST)"
LIGHT_CURVE_ARCHIVE_NAME = "Light-curve archive (TESS data at MAST)"


class SourceError(Exception):
    """Base class for problems with outside sources."""


class CandidateNotFoundError(SourceError):
    def __init__(self, toi: ToiId) -> None:
        super().__init__(f"No candidate {toi} in the exoplanet catalog.")
        self.toi = toi


class CandidateIncompleteError(SourceError):
    """The catalog lists the candidate without a value every check needs (FR-02)."""

    def __init__(self, toi: ToiId, missing: Sequence[str]) -> None:
        super().__init__(
            f"The exoplanet catalog lists {toi} without its {_join(missing)}, so it cannot be "
            "checked."
        )
        self.toi = toi
        self.missing = list(missing)


class SourceUnavailableError(SourceError):
    """An outside source could not be reached (UC-01 *a)."""

    def __init__(self, source: str, detail: str) -> None:
        super().__init__(f"{source} could not be reached: {detail}")
        self.source = source
        self.detail = detail


class SourceNotConnectedError(SourceUnavailableError):
    """A source this version does not read yet.

    It counts as unavailable, so the report says the data are missing. An empty result would
    claim that there is nothing to find.
    """

    def __init__(self, source: str) -> None:
        detail = "not connected in this version of TESSter yet"
        SourceError.__init__(self, f"{source} is {detail}")
        self.source = source
        self.detail = detail


def _join(items: Sequence[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


class ExoplanetCatalog(Protocol):
    def get_candidate(self, toi: ToiId) -> CatalogEntry:
        """Return the catalog entry, or raise CandidateNotFoundError, CandidateIncompleteError
        or SourceUnavailableError."""
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
    """True when the data are made up (the test fixtures)."""
