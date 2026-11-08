"""The verifier agent: an LLM that carries out UC-01 steps 3-7 through tool calls.

The model only proposes tool calls; the application runs them, records every result in the
Investigation and computes the verdict itself. Tool-level rules (FR-07 order, known paper ids,
plain sentences) are enforced with ModelRetry, which sends the model a correction instead of
failing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pydantic_ai
from pydantic import BaseModel
from pydantic_ai import Agent, ModelRetry, RunContext, UsageLimits
from pydantic_ai.settings import ModelSettings

from tess_verifier import investigation as steps
from tess_verifier.agent.instructions import VERIFIER_INSTRUCTIONS
from tess_verifier.config import Settings
from tess_verifier.investigation import Investigation, StepError
from tess_verifier.models import Check, CheckStatus, PaperStance, Verdict
from tess_verifier.sources import DataSources
from tess_verifier.vetting.checks import NEARBY_RADIUS_ARCMIN

pydantic_ai.BANNER_ENABLED = False

ACTOR = "agent"


@dataclass
class VerifierDeps:
    inv: Investigation
    sources: DataSources


@dataclass(frozen=True)
class AgentRun:
    reason: str
    """The agent's final answer: one sentence with the main reason."""
    usage: str


class PaperForAgent(BaseModel):
    id: str
    title: str
    year: int
    abstract: str


class NeighborForAgent(BaseModel):
    tic_id: int
    separation_arcsec: float
    tmag: float
    max_depth_if_fully_eclipsed_ppm: float
    could_cause_dip: bool


class NeighborsForAgent(BaseModel):
    search_radius_arcmin: float
    target_tmag: float
    dip_depth_ppm: float
    stars: list[NeighborForAgent] | None
    centroid_test_must_come_first: bool
    note: str


class CheckResultForAgent(BaseModel):
    check: Check
    status: CheckStatus
    finding: str


class VerdictForAgent(BaseModel):
    verdict: Verdict
    final: bool
    tests_still_to_run: list[Check]
    failed_tests: list[str]
    """Names of the failed tests, for the final sentence."""
    likely_cause: str | None
    what_would_settle_it: list[str]
    note: str


verifier_agent = Agent(
    deps_type=VerifierDeps,
    output_type=str,
    instructions=VERIFIER_INSTRUCTIONS,
    name="tess-verifier",
)


@verifier_agent.tool(retries=2)
def search_papers(ctx: RunContext[VerifierDeps]) -> list[PaperForAgent] | str:
    """Search the paper archives for papers that mention the candidate.

    Returns each paper's id, title, year and abstract, or a message saying why there are none.
    """
    inv = ctx.deps.inv
    papers = steps.find_papers(inv, ctx.deps.sources, actor=ACTOR)
    if inv.blind:
        return "Papers are hidden in a blind test."
    if papers is None:
        return "The paper archive could not be reached, so no papers can be listed."
    if not papers:
        return "No papers mention this candidate."
    return [
        PaperForAgent(
            id=p.paper.id, title=p.paper.title, year=p.paper.year, abstract=p.paper.abstract
        )
        for p in papers
    ]


@verifier_agent.tool(retries=2)
def classify_paper(
    ctx: RunContext[VerifierDeps],
    paper_id: str,
    stance: Literal["confirms", "rules_out", "mentions"],
    justification: str,
) -> str:
    """Record what one paper says about the candidate.

    Args:
        paper_id: The paper's id, as returned by search_papers.
        stance: "confirms" if the paper shows the candidate is a planet, "rules_out" if it
            shows the signal is not a planet, "mentions" otherwise.
        justification: One short plain sentence, based on the title or abstract, that
            supports the stance.
    """
    try:
        steps.classify_paper(ctx.deps.inv, paper_id, PaperStance(stance), justification, ACTOR)
    except StepError as exc:
        raise ModelRetry(str(exc)) from exc
    return "Recorded."


@verifier_agent.tool(retries=2)
def find_nearby_stars(ctx: RunContext[VerifierDeps]) -> NeighborsForAgent:
    """Look for stars near the target that are bright enough to cause the dip on their own.

    A star counts if, completely eclipsed, it would dim the light in the target's pixels by at
    least the observed depth. If there is one, the centroid test must run before other tests.
    """
    inv = ctx.deps.inv
    neighbors = steps.scan_neighbors(inv, ctx.deps.sources, actor=ACTOR)
    entry = inv.entry
    must_come_first = Check.CENTROID in inv.required
    if neighbors is None:
        note = "The star catalog could not be reached, so the centroid test is required."
    elif inv.bright_neighbors:
        note = "At least one star could cause the dip: run the centroid test first."
    else:
        note = "No star nearby is bright enough to cause the dip."
    return NeighborsForAgent(
        search_radius_arcmin=NEARBY_RADIUS_ARCMIN,
        target_tmag=entry.tmag,
        dip_depth_ppm=entry.depth_ppm,
        stars=None
        if neighbors is None
        else [
            NeighborForAgent(
                tic_id=n.star.tic_id,
                separation_arcsec=n.star.separation_arcsec,
                tmag=n.star.tmag,
                max_depth_if_fully_eclipsed_ppm=round(n.max_depth_ppm),
                could_cause_dip=n.could_cause_dip,
            )
            for n in neighbors
        ],
        centroid_test_must_come_first=must_come_first,
        note=note,
    )


@verifier_agent.tool(retries=2)
def run_check(ctx: RunContext[VerifierDeps], check: Check, reason: str) -> CheckResultForAgent:
    """Run one verification test and record why it was run.

    Tests:
    - centroid: does the light centre move during the dip? A shift means the dip comes from a
      nearby star.
    - odd_even_depth: are odd and even dips equally deep? Two eclipsing stars often alternate.
    - secondary_eclipse: is there a second, shallower dip between the main dips?
    - companion_size: is the transiting object small enough to be a planet?

    Args:
        check: The test to run.
        reason: Why this test is run for this candidate, in one short plain sentence for a student.
    """
    try:
        result = steps.run_check(ctx.deps.inv, ctx.deps.sources, check, reason, actor=ACTOR)
    except StepError as exc:
        raise ModelRetry(str(exc)) from exc
    return CheckResultForAgent(check=result.check, status=result.status, finding=result.finding)


@verifier_agent.tool(retries=2)
def skip_check(ctx: RunContext[VerifierDeps], check: Check, reason: str) -> str:
    """Record that a test which is not required will not be run, and why.

    Args:
        check: The test to skip.
        reason: Why the test is not needed for this candidate, in one short plain sentence.
    """
    try:
        steps.skip_check(ctx.deps.inv, check, reason, ACTOR)
    except StepError as exc:
        raise ModelRetry(str(exc)) from exc
    return "Recorded."


@verifier_agent.tool(retries=2)
def get_verdict(ctx: RunContext[VerifierDeps]) -> VerdictForAgent:
    """Get the verdict that code computes from the test results so far. You cannot change it."""
    inv = ctx.deps.inv
    decision = steps.current_decision(inv)
    final = not decision.not_run
    if final:
        inv.verdict_seen = decision.verdict
        inv.checks_when_verdict_seen = len(inv.results)
        note = "This verdict is final. Answer with one plain sentence giving its main reason."
        if len(decision.failed) > 1:
            note += " Name every failed test in it."
    elif not inv.neighbors_scanned:
        note = "Not final: call find_nearby_stars, then run the tests still to run."
    else:
        note = "Not final: run the tests still to run, then call get_verdict again."
    inv.log(ACTOR, f"get_verdict -> {decision.verdict.value}{'' if final else ' (not final)'}")
    return VerdictForAgent(
        verdict=decision.verdict,
        final=final,
        tests_still_to_run=decision.not_run,
        failed_tests=[c.label for c in decision.failed],
        likely_cause=decision.cause,
        what_would_settle_it=decision.settle_by,
        note=note,
    )


def candidate_prompt(inv: Investigation) -> str:
    """The context the model starts with: the candidate's catalog data (UC-01 step 2)."""
    entry = inv.entry
    radius = (
        f"{entry.stellar_radius_rsun:.2f} solar radii"
        if entry.stellar_radius_rsun is not None
        else "unknown"
    )
    transit = (
        f"Transit: period {entry.period_days:.4f} days, depth {entry.depth_ppm:.0f} ppm, "
        f"duration {entry.duration_hours:.1f} hours"
    )
    if inv.blind:
        # The model must not use what it may remember about a known object (NFR-01).
        return "\n".join(
            [
                "Check this transit candidate.",
                "",
                "Candidate: name hidden. This is a blind test: catalog status, names and "
                "papers are hidden, so do not search for papers.",
                f"Target star: TESS magnitude {entry.tmag:.1f}, radius {radius}",
                transit,
            ]
        )
    status = (
        f"{entry.disposition.label} ({entry.disposition.value}) as of {entry.disposition_date}"
        if entry.disposition is not None
        else "not given"
    )
    return "\n".join(
        [
            "Check this transit candidate.",
            "",
            f"Candidate: {inv.toi}",
            f"Target star: TIC {entry.tic_id}, TESS magnitude {entry.tmag:.1f}, radius {radius}",
            transit,
            f"Catalog status: {status}",
        ]
    )


def run_verifier(inv: Investigation, sources: DataSources, settings: Settings) -> AgentRun:
    """Let the agent check the candidate. Raises pydantic_ai errors on model problems."""
    result = verifier_agent.run_sync(
        candidate_prompt(inv),
        deps=VerifierDeps(inv=inv, sources=sources),
        model=settings.model,
        model_settings=ModelSettings(max_tokens=settings.max_tokens),
        usage_limits=UsageLimits(request_limit=settings.max_requests),
    )
    usage = result.usage
    return AgentRun(
        reason=result.output.strip(),
        usage=f"{usage.requests} model requests, {usage.input_tokens} input and "
        f"{usage.output_tokens} output tokens",
    )
