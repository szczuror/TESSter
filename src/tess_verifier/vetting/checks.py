"""Verification tests (glossary: Verification Test). Plain rules with fixed thresholds, no LLM.

v1 applies the rules to placeholder measurements. Later versions will measure the same numbers
from real light curves and pixel data, and the rules here stay the same.
"""

from __future__ import annotations

import math

from tess_verifier.models import (
    CatalogEntry,
    CentroidMeasurement,
    Check,
    CheckResult,
    CheckStatus,
    NearbyStar,
    NeighborAssessment,
    Source,
    TransitMetrics,
)

NEARBY_RADIUS_ARCMIN = 2.5
"""FR-07: look for stars this close to the target."""

SIGMA_LIMIT = 3.0
"""A difference of at least this many standard deviations counts as real."""

EARTH_RADII_PER_SUN_RADIUS = 109.1
EARTH_RADII_PER_JUPITER_RADIUS = 11.21
MAX_PLANET_RADIUS_EARTH = 2 * EARTH_RADII_PER_JUPITER_RADIUS
"""Objects bigger than about two Jupiter radii are stars, not planets."""

CENTROID_PRECISION_FRACTION = 1 / 3
"""The centroid must be measured to better than this fraction of the distance to the neighbor."""

TESS_PIXEL_ARCSEC = 21.0
"""Size of one TESS pixel on the sky. When the star catalog cannot be reached, a star bright
enough to cause the dip may lie as close as one pixel."""

NO_LIGHT_CURVE = "No light-curve measurements are available for this candidate."

NO_USABLE_ERROR = (
    "The measurement has no usable error (zero or missing), so its significance cannot be judged."
)


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


def _significance(value: float, error: float) -> float | None:
    """How many standard deviations the value lies from zero, or None if the error is not usable.

    An error of zero, below zero or NaN means the error is missing, not that the measurement is
    perfect, so it must not count as an infinitely significant result.
    """
    if not (math.isfinite(value) and math.isfinite(error)) or error <= 0:
        return None
    return abs(value) / error


def _without_usable_error(check: Check, reason: str, sources: list[Source]) -> CheckResult:
    return CheckResult(
        check=check,
        status=CheckStatus.UNCLEAR,
        reason=reason,
        finding=NO_USABLE_ERROR,
        sources=sources,
    )


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
    sigma = _significance(offset, err)
    sources = [measurement.source]
    if sigma is None:
        return _without_usable_error(Check.CENTROID, reason, sources)
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


def odd_even_check(metrics: TransitMetrics | None, reason: str) -> CheckResult:
    """Are odd and even dips equally deep? Two eclipsing stars often make alternating dips."""
    if metrics is None:
        return CheckResult(
            check=Check.ODD_EVEN, status=CheckStatus.SKIPPED, reason=reason, finding=NO_LIGHT_CURVE
        )
    sources = [metrics.source]
    if metrics.odd_transits < 1 or metrics.even_transits < 1:
        return CheckResult(
            check=Check.ODD_EVEN,
            status=CheckStatus.UNCLEAR,
            reason=reason,
            finding="Only one transit was observed, which is not enough to compare odd and "
            "even dips.",
            sources=sources,
        )
    diff = metrics.odd_depth_ppm - metrics.even_depth_ppm
    sigma = _significance(diff, math.hypot(metrics.odd_depth_err_ppm, metrics.even_depth_err_ppm))
    if sigma is None:
        return _without_usable_error(Check.ODD_EVEN, reason, sources)
    if sigma >= SIGMA_LIMIT:
        return CheckResult(
            check=Check.ODD_EVEN,
            status=CheckStatus.FAILED,
            reason=reason,
            finding=f"Odd and even dips differ in depth by {abs(diff):.0f} ppm ({sigma:.1f} "
            "sigma), the alternating pattern of two stars eclipsing each other.",
            sources=sources,
        )
    return CheckResult(
        check=Check.ODD_EVEN,
        status=CheckStatus.PASSED,
        reason=reason,
        finding=f"Odd and even dips are equally deep within the errors ({sigma:.1f} sigma).",
        sources=sources,
    )


def secondary_eclipse_check(metrics: TransitMetrics | None, reason: str) -> CheckResult:
    """Is there a second, shallower dip between the main dips?"""
    if metrics is None:
        return CheckResult(
            check=Check.SECONDARY_ECLIPSE,
            status=CheckStatus.SKIPPED,
            reason=reason,
            finding=NO_LIGHT_CURVE,
        )
    depth, err = metrics.secondary_depth_ppm, metrics.secondary_depth_err_ppm
    sigma = _significance(depth, err)
    sources = [metrics.source]
    if sigma is None:
        return _without_usable_error(Check.SECONDARY_ECLIPSE, reason, sources)
    if depth > 0 and sigma >= SIGMA_LIMIT:
        return CheckResult(
            check=Check.SECONDARY_ECLIPSE,
            status=CheckStatus.FAILED,
            reason=reason,
            finding=f"A second, shallower dip of {depth:.0f} ppm ({sigma:.1f} sigma) appears "
            "between the main dips, as when one star eclipses another.",
            sources=sources,
        )
    return CheckResult(
        check=Check.SECONDARY_ECLIPSE,
        status=CheckStatus.PASSED,
        reason=reason,
        finding=f"No second dip between the main dips (depth {depth:.0f} +/- {err:.0f} ppm, "
        f"{sigma:.1f} sigma).",
        sources=sources,
    )


def companion_size_check(candidate: CatalogEntry, reason: str) -> CheckResult:
    """Is the transiting object small enough to be a planet? Radius = R_star * sqrt(depth)."""
    if candidate.stellar_radius_rsun is None:
        return CheckResult(
            check=Check.COMPANION_SIZE,
            status=CheckStatus.UNCLEAR,
            reason=reason,
            finding="The host star's radius is unknown, so the size of the transiting object "
            "cannot be estimated.",
            sources=[candidate.source],
        )
    radius_earth = (
        candidate.stellar_radius_rsun
        * math.sqrt(candidate.depth_ppm / 1e6)
        * EARTH_RADII_PER_SUN_RADIUS
    )
    radius_jupiter = radius_earth / EARTH_RADII_PER_JUPITER_RADIUS
    if radius_earth > MAX_PLANET_RADIUS_EARTH:
        return CheckResult(
            check=Check.COMPANION_SIZE,
            status=CheckStatus.FAILED,
            reason=reason,
            finding=f"The dip implies an object of about {radius_earth:.1f} Earth radii "
            f"({radius_jupiter:.1f} Jupiter radii), too big for a planet, so it is probably "
            "a star.",
            sources=[candidate.source],
        )
    return CheckResult(
        check=Check.COMPANION_SIZE,
        status=CheckStatus.PASSED,
        reason=reason,
        finding=f"The dip implies an object of about {radius_earth:.1f} Earth radii "
        f"({radius_jupiter:.2f} Jupiter radii), a size planets can have.",
        sources=[candidate.source],
    )
