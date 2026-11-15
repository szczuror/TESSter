"""Which nearby stars are bright enough to cause the dip (FR-07). Not a test itself: the result
decides whether the centroid test is required."""

from __future__ import annotations

from tesster.models import CatalogEntry, NearbyStar, NeighborAssessment

NEARBY_RADIUS_ARCMIN = 2.5
"""FR-07: look for stars this close to the target."""


def max_depth_if_eclipsed_ppm(target_tmag: float, star_tmag: float) -> float:
    """Depth seen on the target if a nearby star were completely eclipsed.

    All light of the nearby star is assumed to fall into the target's aperture, which gives
    the largest dip the star could cause: flux ratio r = 10^(-0.4 * (T_star - T_target)),
    dip = r / (1 + r).
    """
    ratio = 10 ** (-0.4 * (star_tmag - target_tmag))
    return 1e6 * ratio / (1 + ratio)


def assess_neighbors(candidate: CatalogEntry, stars: list[NearbyStar]) -> list[NeighborAssessment]:
    """Mark each nearby star that is bright enough to cause the dip on its own (FR-07)."""
    assessments = []
    for star in sorted(stars, key=lambda s: s.separation_arcsec):
        max_depth = max_depth_if_eclipsed_ppm(candidate.tmag, star.tmag)
        assessments.append(
            NeighborAssessment(
                star=star,
                max_depth_ppm=max_depth,
                could_cause_dip=max_depth >= candidate.depth_ppm,
            )
        )
    return assessments
