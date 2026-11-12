"""What the verification tests share: the significance limit and results for unusable data."""

from __future__ import annotations

import math

from tesster.models import Check, CheckResult, CheckStatus, Source

SIGMA_LIMIT = 3.0
"""A difference of at least this many standard deviations counts as real."""

NO_LIGHT_CURVE = "No light-curve measurements are available for this candidate."

NO_USABLE_ERROR = (
    "The measurement has no usable error (zero or missing), so its significance cannot be judged."
)


def significance(value: float, error: float) -> float | None:
    """How many standard deviations the value lies from zero, or None if the error is not usable.

    An error of zero, below zero or NaN means the error is missing, not that the measurement is
    perfect, so it must not count as an infinitely significant result.
    """
    if not (math.isfinite(value) and math.isfinite(error)) or error <= 0:
        return None
    return abs(value) / error


def without_usable_error(check: Check, reason: str, sources: list[Source]) -> CheckResult:
    return CheckResult(
        check=check,
        status=CheckStatus.UNCLEAR,
        reason=reason,
        finding=NO_USABLE_ERROR,
        sources=sources,
    )
