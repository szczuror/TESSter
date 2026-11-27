"""Stand-in for the archives that are not connected yet.

Every method raises SourceNotConnectedError, so the check goes on and the report says which
data are missing. Returning an empty result instead would put a false statement into the
report, such as "No papers mention this candidate".
"""

from __future__ import annotations

from collections.abc import Sequence

from tesster.models import (
    CatalogEntry,
    CentroidMeasurement,
    NearbyStar,
    Paper,
    ToiId,
    TransitMetrics,
)
from tesster.sources.base import (
    LIGHT_CURVE_ARCHIVE_NAME,
    PAPER_ARCHIVE_NAME,
    STAR_CATALOG_NAME,
    SourceNotConnectedError,
)


class NotConnected:
    """Implements PaperArchive, StarCatalog and LightCurveArchive."""

    def search(self, toi: ToiId, aliases: Sequence[str] = ()) -> list[Paper]:
        raise SourceNotConnectedError(PAPER_ARCHIVE_NAME)

    def stars_near(self, candidate: CatalogEntry, radius_arcmin: float) -> list[NearbyStar]:
        raise SourceNotConnectedError(STAR_CATALOG_NAME)

    def transit_metrics(self, candidate: CatalogEntry) -> TransitMetrics | None:
        raise SourceNotConnectedError(LIGHT_CURVE_ARCHIVE_NAME)

    def centroid(self, candidate: CatalogEntry) -> CentroidMeasurement | None:
        raise SourceNotConnectedError(LIGHT_CURVE_ARCHIVE_NAME)
