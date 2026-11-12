"""Companion size test: is the transiting object small enough to be a planet?"""

from __future__ import annotations

import math

from tesster.models import CatalogEntry, Check, CheckResult, CheckStatus

EARTH_RADII_PER_SUN_RADIUS = 109.1
EARTH_RADII_PER_JUPITER_RADIUS = 11.21
MAX_PLANET_RADIUS_EARTH = 2 * EARTH_RADII_PER_JUPITER_RADIUS
"""Objects bigger than about two Jupiter radii are stars, not planets."""


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
