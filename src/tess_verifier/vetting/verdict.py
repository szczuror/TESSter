"""Which checks are required, and the verdict rule (FR-06, FR-07, FR-11, FR-12, FR-13).

The verdict is computed here, never by the LLM, so the same check results always give the same
verdict (NFR-03).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tess_verifier.models import Check, CheckResult, CheckStatus, NeighborAssessment, Verdict

ECLIPSING_BINARY_CHECKS = (Check.ODD_EVEN, Check.SECONDARY_ECLIPSE, Check.COMPANION_SIZE)
"""FR-06: always check whether the dip could come from two stars eclipsing each other."""

CAUSES = {
    Check.CENTROID: "a nearby star (the dip comes from another star whose light falls into the "
    "same pixels)",
    Check.ODD_EVEN: "two stars eclipsing each other (an eclipsing binary)",
    Check.SECONDARY_ECLIPSE: "two stars eclipsing each other (an eclipsing binary)",
    Check.COMPANION_SIZE: "a star rather than a planet (the transiting object is too big to be "
    "a planet)",
}
"""FR-12: the likely cause when a check fails."""

FAILURE_PRIORITY = (Check.CENTROID, Check.ODD_EVEN, Check.SECONDARY_ECLIPSE, Check.COMPANION_SIZE)
"""When several tests fail, the cause and the main reason come from the first of them in this
order, not from the order the tests ran in, so repeated checks give the same report (NFR-03)."""

NEARBY_ECLIPSING_BINARY = (
    "a nearby eclipsing binary (another star in the same pixels is a pair of stars eclipsing "
    "each other)"
)

SETTLE_BY = {
    Check.CENTROID: "High-resolution imaging or seeing-limited photometry from the ground, to "
    "see which nearby star dims.",
    Check.ODD_EVEN: "More transits, from new TESS sectors or ground-based photometry, to compare "
    "odd and even dips.",
    Check.SECONDARY_ECLIPSE: "More light-curve data, from new TESS sectors or ground-based "
    "photometry, to look for a secondary eclipse.",
    Check.COMPANION_SIZE: "A spectrum of the host star, to measure its radius.",
}
"""FR-13: the observation or data that would settle a check without a result."""


def required_checks(neighbors: list[NeighborAssessment] | None) -> list[Check]:
    """Checks every verdict needs, in the order they must run.

    The centroid test comes first when a star bright enough to cause the dip lies within
    2.5 arcmin (FR-07), and also when the star catalog could not be reached (``None``),
    because then such a star cannot be ruled out.
    """
    if neighbors is None or any(n.could_cause_dip for n in neighbors):
        return [Check.CENTROID, *ECLIPSING_BINARY_CHECKS]
    return list(ECLIPSING_BINARY_CHECKS)


@dataclass(frozen=True)
class Decision:
    verdict: Verdict
    template_reason: str
    """One-sentence main reason built without the LLM (FR-10)."""
    cause: str | None = None
    failed: list[Check] = field(default_factory=list)
    """Failed checks, in FAILURE_PRIORITY order."""
    settle_by: list[str] = field(default_factory=list)
    not_run: list[Check] = field(default_factory=list)
    """Required checks that have no result yet."""


def decide(results: list[CheckResult], required: list[Check]) -> Decision:
    """FR-11: *false positive* if any test failed, *likely planet* if every required test
    passed, *inconclusive* otherwise."""
    by_check = {r.check: r for r in results}
    not_run = [c for c in required if c not in by_check]

    failed = sorted(
        (r for r in results if r.status is CheckStatus.FAILED),
        key=lambda r: FAILURE_PRIORITY.index(r.check),
    )
    if failed:
        first = failed[0]
        failed_checks = {r.check for r in failed}
        if Check.CENTROID in failed_checks and failed_checks & set(ECLIPSING_BINARY_CHECKS):
            cause = NEARBY_ECLIPSING_BINARY
        else:
            cause = CAUSES[first.check]
        reason = f"The {first.check.label.lower()} failed: {_lower_first(first.finding)}"
        if len(failed) > 1:
            others = _join([r.check.label.lower() for r in failed[1:]])
            reason = f"{reason.rstrip('.')}; the {others} failed too."
        return Decision(
            verdict=Verdict.FALSE_POSITIVE,
            template_reason=reason,
            cause=cause,
            failed=[r.check for r in failed],
            not_run=not_run,
        )

    without_pass = [
        c for c in required if c not in by_check or by_check[c].status is not CheckStatus.PASSED
    ]
    if not without_pass:
        return Decision(
            verdict=Verdict.LIKELY_PLANET,
            template_reason=_planet_reason(required),
        )

    labels = _join([c.label.lower() for c in without_pass])
    return Decision(
        verdict=Verdict.INCONCLUSIVE,
        template_reason=f"No test failed, but the {labels} gave no clear result, so a false "
        "positive cannot be ruled out yet.",
        settle_by=[SETTLE_BY[c] for c in without_pass],
        not_run=not_run,
    )


def _planet_reason(required: list[Check]) -> str:
    if Check.CENTROID in required:
        return (
            "Every required test passed: the dip comes from the target star and shows no sign "
            "of two stars eclipsing each other."
        )
    return (
        "Every required test passed: the dip shows no sign of two stars eclipsing each other, "
        "and no nearby star is bright enough to cause it."
    )


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:]


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]
