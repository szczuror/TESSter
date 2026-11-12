"""Odd-even depth test: are odd and even dips equally deep?"""

from __future__ import annotations

import math

from tesster.models import Check, CheckResult, CheckStatus, TransitMetrics
from tesster.vetting.checks.common import (
    NO_LIGHT_CURVE,
    SIGMA_LIMIT,
    significance,
    without_usable_error,
)
from tesster.vetting.spec import CheckContext, CheckSpec, Family, always


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
    sigma = significance(diff, math.hypot(metrics.odd_depth_err_ppm, metrics.even_depth_err_ppm))
    if sigma is None:
        return without_usable_error(Check.ODD_EVEN, reason, sources)
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


def _run(ctx: CheckContext) -> CheckResult:
    return odd_even_check(ctx.sources.light_curves.transit_metrics(ctx.entry), ctx.reason)


SPEC = CheckSpec(
    check=Check.ODD_EVEN,
    family=Family.ECLIPSING_BINARY,
    looks_for="are odd and even dips equally deep? Two eclipsing stars often alternate.",
    cause="two stars eclipsing each other (an eclipsing binary)",
    settle_by="More transits, from new TESS sectors or ground-based photometry, to compare odd "
    "and even dips.",
    standard_reason="Always run: two stars eclipsing each other can mimic a transit and often "
    "make alternating deeper and shallower dips (FR-06).",
    required_when=always,
    run=_run,
)
