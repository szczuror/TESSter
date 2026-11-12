"""Centroid test: does the light-weighted centre of the image move during the dip?"""

from __future__ import annotations

from tesster.models import (
    CentroidMeasurement,
    Check,
    CheckResult,
    CheckStatus,
    NeighborAssessment,
)
from tesster.vetting.checks.common import SIGMA_LIMIT, significance, without_usable_error

CENTROID_PRECISION_FRACTION = 1 / 3
"""The centroid must be measured to better than this fraction of the distance to the neighbor."""

TESS_PIXEL_ARCSEC = 21.0
"""Size of one TESS pixel on the sky. When the star catalog cannot be reached, a star bright
enough to cause the dip may lie as close as one pixel."""


def _closest_possible_neighbor(
    bright_neighbors: list[NeighborAssessment] | None,
) -> tuple[float, str] | None:
    """Separation and description of the closest star that could cause the dip, if any."""
    if bright_neighbors is None:
        return TESS_PIXEL_ARCSEC, (
            f"a star one TESS pixel ({TESS_PIXEL_ARCSEC:.0f} arcsec) away, which cannot be "
            "ruled out because the star catalog could not be reached"
        )
    if not bright_neighbors:
        return None
    closest = min(n.star.separation_arcsec for n in bright_neighbors)
    return closest, f"a star {closest:.0f} arcsec away"


def centroid_check(
    measurement: CentroidMeasurement | None,
    bright_neighbors: list[NeighborAssessment] | None,
    reason: str,
) -> CheckResult:
    """Does the light-weighted centre of the image move during the dip?

    ``bright_neighbors`` is None when the star catalog could not be reached (FR-07).
    """
    if measurement is None:
        return CheckResult(
            check=Check.CENTROID,
            status=CheckStatus.SKIPPED,
            reason=reason,
            finding="No pixel data (target pixel files) are available to measure the light "
            "centre, so the test could not run.",
        )
    offset, err = measurement.offset_arcsec, measurement.offset_err_arcsec
    sigma = significance(offset, err)
    sources = [measurement.source]
    if sigma is None:
        return without_usable_error(Check.CENTROID, reason, sources)
    if sigma >= SIGMA_LIMIT:
        return CheckResult(
            check=Check.CENTROID,
            status=CheckStatus.FAILED,
            reason=reason,
            finding=f"During the dip the light centre moves by {offset:.1f} arcsec "
            f"({sigma:.1f} sigma), so the dip most likely comes from a nearby star.",
            sources=sources,
        )
    neighbor = _closest_possible_neighbor(bright_neighbors)
    if neighbor is not None:
        separation, star = neighbor
        if err > separation * CENTROID_PRECISION_FRACTION:
            return CheckResult(
                check=Check.CENTROID,
                status=CheckStatus.UNCLEAR,
                reason=reason,
                finding=f"No shift is seen, but the light centre is measured only to "
                f"+/-{err:.1f} arcsec, too coarse to tell the target from {star}.",
                sources=sources,
            )
    return CheckResult(
        check=Check.CENTROID,
        status=CheckStatus.PASSED,
        reason=reason,
        finding=f"The light centre stays in place during the dip (shift {offset:.1f} +/- "
        f"{err:.1f} arcsec, {sigma:.1f} sigma), as expected if the target star dims.",
        sources=sources,
    )
