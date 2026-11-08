"""One check from TOI number to report (UC-01), and several checks at once (UC-03).

1. Parse the TOI number and load the candidate from the catalog (no LLM, so a wrong number
   costs nothing).
2. Let the LLM agent run the check through its tools, or run the standard procedure without an
   LLM (``offline``, or as a fallback when the LLM fails during the check).
3. The safety net runs every required step the agent left out.
4. Code computes the verdict (FR-11) and builds the report.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from datetime import UTC, datetime

from pydantic_ai import AgentRunError, ModelAuthenticationError, ModelNotFoundError, UserError

from tess_verifier import investigation as steps
from tess_verifier.agent.verifier import run_verifier
from tess_verifier.config import Settings
from tess_verifier.investigation import SAFETY_NET, Investigation
from tess_verifier.models import (
    Check,
    Disposition,
    InvalidToiError,
    NotChecked,
    PaperStance,
    Report,
    Verdict,
    parse_toi,
)
from tess_verifier.sources import CandidateNotFoundError, DataSources, SourceUnavailableError
from tess_verifier.vetting.verdict import ECLIPSING_BINARY_CHECKS, Decision

STANDARD_REASONS = {
    Check.ODD_EVEN: "Always run: two stars eclipsing each other can mimic a transit and often "
    "make alternating deeper and shallower dips (FR-06).",
    Check.SECONDARY_ECLIPSE: "Always run: a pair of eclipsing stars often shows a second, "
    "shallower eclipse between the main dips (FR-06).",
    Check.COMPANION_SIZE: "Always run: an object too big to be a planet must be a star (FR-06).",
}
CENTROID_NOT_NEEDED = (
    "No star within 2.5 arcmin is bright enough to cause the dip, so the centroid test is not "
    "needed (FR-07)."
)
VERDICT_ORDER = {Verdict.LIKELY_PLANET: 0, Verdict.INCONCLUSIVE: 1, Verdict.FALSE_POSITIVE: 2}
"""FR-16: likely planets first; inputs without a report go last."""


class ConfigurationError(Exception):
    """The LLM cannot be used as configured: missing or wrong key or address, or unknown model."""


def check_candidate(
    raw_toi: str,
    *,
    sources: DataSources,
    settings: Settings,
    offline: bool = False,
    blind: bool = False,
) -> Report | NotChecked:
    """Check one candidate. Raises ConfigurationError when the LLM is not set up."""
    started = time.perf_counter()
    try:
        toi = parse_toi(raw_toi)
    except InvalidToiError as exc:
        return NotChecked(input=raw_toi.strip(), reason=str(exc))

    inv = Investigation(toi=toi, blind=blind)
    try:
        steps.load_candidate(inv, sources)
    except (CandidateNotFoundError, SourceUnavailableError) as exc:
        return NotChecked(input=str(toi), reason=str(exc))

    checked_with, agent_reason, usage = _orchestrate(inv, sources, settings, offline=offline)
    apply_safety_net(inv, sources)
    decision = steps.current_decision(inv)
    return Report(
        toi=toi,
        generated_at=datetime.now(UTC),
        checked_with=checked_with,
        blind=blind,
        placeholder_data=sources.placeholder,
        candidate=inv.entry,
        papers=inv.papers,
        neighbors=inv.neighbors,
        checks=inv.results,
        verdict=decision.verdict,
        main_reason=_main_reason(inv, decision, agent_reason),
        cause=decision.cause,
        settle_by=decision.settle_by,
        disagreements=_disagreements(inv, decision.verdict),
        problems=inv.problems,
        notes=inv.notes,
        trace=inv.trace,
        usage=usage,
        duration_seconds=round(time.perf_counter() - started, 2),
    )


def check_many(
    raw_tois: Sequence[str],
    *,
    sources: DataSources,
    settings: Settings,
    offline: bool = False,
    blind: bool = False,
) -> list[Report | NotChecked]:
    """UC-03: check every input and sort the results for FR-16."""
    outcomes = [
        check_candidate(raw, sources=sources, settings=settings, offline=offline, blind=blind)
        for raw in raw_tois
    ]
    return sorted(outcomes, key=_rank)


def run_standard_procedure(inv: Investigation, sources: DataSources) -> None:
    """UC-01 steps 3-6 without an LLM. Safe to run on a partly done investigation."""
    steps.find_papers(inv, sources)
    steps.scan_neighbors(inv, sources)
    if Check.CENTROID in inv.required:
        steps.run_check(inv, sources, Check.CENTROID, _centroid_reason(inv))
    elif inv.result_for(Check.CENTROID) is None:
        steps.skip_check(inv, Check.CENTROID, CENTROID_NOT_NEEDED)
    for check in ECLIPSING_BINARY_CHECKS:
        steps.run_check(inv, sources, check, STANDARD_REASONS[check])


def apply_safety_net(inv: Investigation, sources: DataSources) -> None:
    """Run every required step the agent left out (FR-04, FR-06, FR-07)."""
    if not inv.papers_searched:
        steps.find_papers(inv, sources, actor=SAFETY_NET)
    if not inv.neighbors_scanned:
        steps.scan_neighbors(inv, sources, actor=SAFETY_NET)
    added = 0
    for check in inv.required:
        if inv.result_for(check) is None:
            reason = _centroid_reason(inv) if check is Check.CENTROID else STANDARD_REASONS[check]
            steps.run_check(inv, sources, check, reason, actor=SAFETY_NET)
            added += 1
    if added:
        inv.notes.append(
            f"{added} required test(s) were run automatically because the agent did not run them."
        )


def _orchestrate(
    inv: Investigation, sources: DataSources, settings: Settings, *, offline: bool
) -> tuple[str, str | None, str | None]:
    """Run the check. Returns (checked with, agent's main reason, token usage)."""
    if offline:
        run_standard_procedure(inv, sources)
        return "standard procedure (offline, no LLM)", None, None
    try:
        run = run_verifier(inv, sources, settings)
    except UserError as exc:
        raise ConfigurationError(str(exc)) from exc
    except (ModelAuthenticationError, ModelNotFoundError) as exc:
        raise ConfigurationError(f"{settings.model}: {exc}") from exc
    except AgentRunError as exc:
        inv.notes.append(
            f"The LLM agent stopped with an error ({type(exc).__name__}: {exc}). "
            "The standard procedure finished the check."
        )
        run_standard_procedure(inv, sources)
        return f"standard procedure (fallback after an error of {settings.model})", None, None
    return f"LLM agent ({settings.model})", run.reason, run.usage


def _main_reason(inv: Investigation, decision: Decision, agent_reason: str | None) -> str:
    """The agent's sentence, unless the verdict or the results changed after the agent saw them,
    or the sentence is not one plain line (FR-10)."""
    if agent_reason is None:
        return decision.template_reason
    if not agent_reason:
        inv.notes.append("The agent gave no main reason, so it comes from a template.")
        return decision.template_reason
    same_verdict = inv.verdict_seen is decision.verdict
    same_tests = inv.checks_when_verdict_seen == len(inv.results)
    if not (same_verdict and same_tests):
        inv.notes.append(
            "The main reason comes from a template, because the verdict or the tests changed "
            "after the agent last saw them."
        )
        return decision.template_reason
    if problem := steps.sentence_problem(agent_reason):
        inv.notes.append(
            "The main reason comes from a template, because the agent's sentence could not be "
            f"used: {problem}."
        )
        return decision.template_reason
    return agent_reason


def _centroid_reason(inv: Investigation) -> str:
    if inv.neighbors is None:
        return (
            "The star catalog could not be reached, so a bright nearby star cannot be ruled "
            "out and we check which star the dip comes from (FR-07)."
        )
    closest = min(inv.bright_neighbors, key=lambda n: n.star.separation_arcsec)
    return (
        f"TIC {closest.star.tic_id}, {closest.star.separation_arcsec:.0f} arcsec away, is bright "
        "enough to cause the dip, so we first check which star the dip comes from (FR-07)."
    )


def _disagreements(inv: Investigation, verdict: Verdict) -> list[str]:
    """UC-01 2b: say when the catalog or papers disagree with the verdict."""
    notes = []
    disposition = inv.entry.disposition
    if disposition in (Disposition.CP, Disposition.KP) and verdict is Verdict.FALSE_POSITIVE:
        notes.append(
            f"The catalog lists this candidate as a {disposition.label}, but our tests point to "
            "a false positive."
        )
    if disposition in (Disposition.FP, Disposition.FA) and verdict is Verdict.LIKELY_PLANET:
        notes.append(
            f"The catalog lists this candidate as a {disposition.label}, but our TESS tests "
            "found nothing wrong. False positives found by later observations, such as radial "
            "velocities, cannot be seen in TESS data alone."
        )
    stances = [p.stance for p in inv.papers or []]
    if verdict is Verdict.LIKELY_PLANET and PaperStance.RULES_OUT in stances:
        notes.append(
            f"{stances.count(PaperStance.RULES_OUT)} paper(s) rule this candidate out; see Papers."
        )
    if verdict is Verdict.FALSE_POSITIVE and PaperStance.CONFIRMS in stances:
        notes.append(
            f"{stances.count(PaperStance.CONFIRMS)} paper(s) confirm this candidate; see Papers."
        )
    return notes


def _rank(outcome: Report | NotChecked) -> int:
    if isinstance(outcome, Report):
        return VERDICT_ORDER[outcome.verdict]
    return len(VERDICT_ORDER)
