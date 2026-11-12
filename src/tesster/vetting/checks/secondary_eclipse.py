"""Secondary eclipse test: is there a second, shallower dip between the main dips?"""

from __future__ import annotations

from tesster.models import Check, CheckResult, CheckStatus, TransitMetrics
from tesster.vetting.checks.common import (
    NO_LIGHT_CURVE,
    SIGMA_LIMIT,
    significance,
    without_usable_error,
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
    sigma = significance(depth, err)
    sources = [metrics.source]
    if sigma is None:
        return without_usable_error(Check.SECONDARY_ECLIPSE, reason, sources)
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
