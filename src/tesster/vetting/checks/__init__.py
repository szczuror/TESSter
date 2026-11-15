"""Verification tests (glossary: Verification Test). Plain rules with fixed thresholds, no LLM.

Each test lives in its own module. v1 applies the rules to placeholder measurements. Later
versions will measure the same numbers from real light curves and pixel data, and the rules
here stay the same.
"""

from tesster.vetting.checks.centroid import (
    CENTROID_PRECISION_FRACTION,
    TESS_PIXEL_ARCSEC,
    centroid_check,
)
from tesster.vetting.checks.common import NO_LIGHT_CURVE, NO_USABLE_ERROR, SIGMA_LIMIT
from tesster.vetting.checks.companion_size import MAX_PLANET_RADIUS_EARTH, companion_size_check
from tesster.vetting.checks.neighbors import (
    NEARBY_RADIUS_ARCMIN,
    assess_neighbors,
    max_depth_if_eclipsed_ppm,
)
from tesster.vetting.checks.odd_even import odd_even_check
from tesster.vetting.checks.secondary_eclipse import secondary_eclipse_check

__all__ = [
    "CENTROID_PRECISION_FRACTION",
    "MAX_PLANET_RADIUS_EARTH",
    "NEARBY_RADIUS_ARCMIN",
    "NO_LIGHT_CURVE",
    "NO_USABLE_ERROR",
    "SIGMA_LIMIT",
    "TESS_PIXEL_ARCSEC",
    "assess_neighbors",
    "centroid_check",
    "companion_size_check",
    "max_depth_if_eclipsed_ppm",
    "odd_even_check",
    "secondary_eclipse_check",
]
