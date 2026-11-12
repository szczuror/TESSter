"""The verdict rule (FR-11, FR-12, FR-13).

The verdict is computed here, never by the LLM, so the same check results always give the same
verdict (NFR-03). What each test contributes (its cause, what would settle it, when it is
required) comes from the registry.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tesster.models import Check, CheckResult, CheckStatus, Verdict
from tesster.vetting.registry import priority, spec_for
from tesster.vetting.spec import Family, Weight

NEARBY_ECLIPSING_BINARY = (
    "a nearby eclipsing binary (another star in the same pixels is a pair of stars eclipsing "
    "each other)"
)
"""FR-12: the likely cause when the dip comes from another star and that star is a binary."""


@dataclass(frozen=True)
class Decision:
    verdict: Verdict
    template_reason: str
    """One-sentence main reason built without the LLM (FR-10)."""
    cause: str | None = None
    failed: list[Check] = field(default_factory=list)
    """Failed checks, in registry order."""
    settle_by: list[str] = field(default_factory=list)
    not_run: list[Check] = field(default_factory=list)
    """Required checks that have no result yet."""


def decide(results: list[CheckResult], required: list[Check]) -> Decision:
    """FR-11: *false positive* if any test failed, *likely planet* if every required test
    passed, *inconclusive* otherwise.

    A failed supporting test does not count: it is shown in the report but leaves the verdict
    as it is.
    """
    by_check = {r.check: r for r in results}
    not_run = [c for c in required if c not in by_check]

    failed = sorted(
        (
            r
            for r in results
            if r.status is CheckStatus.FAILED and spec_for(r.check).weight is Weight.DECISIVE
        ),
        key=lambda r: priority(r.check),
    )
    if failed:
        first = failed[0]
        families = {spec_for(r.check).family for r in failed}
        if {Family.SOURCE, Family.ECLIPSING_BINARY} <= families:
            cause = NEARBY_ECLIPSING_BINARY
        else:
            cause = spec_for(first.check).cause
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
        settle_by=[spec_for(c).settle_by for c in without_pass],
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
