"""State of one candidate check and the steps that change it.

The same steps are used by the LLM agent's tools, by the standard procedure (no LLM) and by the
safety net, so all three record results the same way. Every step writes a line to ``trace``
naming who called it, which ``--verbose`` shows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import assert_never

from tess_verifier.models import (
    CatalogEntry,
    Check,
    CheckResult,
    CheckStatus,
    ClassifiedPaper,
    NeighborAssessment,
    PaperStance,
    ToiId,
    Verdict,
)
from tess_verifier.sources import DataSources, SourceUnavailableError
from tess_verifier.vetting import checks
from tess_verifier.vetting.verdict import Decision, decide, required_checks

SAFETY_NET = "safety net"
"""Actor name for steps the pipeline runs because the agent did not."""


class StepError(Exception):
    """A step was called at the wrong time or with bad input. The message says what to do."""


MAX_SENTENCE_CHARS = 400
"""Longest sentence the LLM may write into the report."""

_LINK_OR_MARKUP = re.compile(r"https?://|www\.|[\[\]<>`]")


def sentence_problem(text: str) -> str | None:
    """Why a sentence the LLM wrote cannot go into the report, or None if it can.

    The main reason (FR-10), the reasons for running or skipping tests and the paper notes are
    shown as the model wrote them. They must be one plain line, because the report links only
    to the data sources (FR-14, NFR-02), never to links or formatting the model made up.
    """
    text = text.strip()
    if not text:
        return "it is empty"
    if "\n" in text or "\r" in text:
        return "it has more than one line"
    if len(text) > MAX_SENTENCE_CHARS:
        return f"it is longer than {MAX_SENTENCE_CHARS} characters"
    if _LINK_OR_MARKUP.search(text):
        return "it contains a link or one of the characters [ ] < > `"
    return None


def _require_plain(text: str, what: str) -> None:
    if problem := sentence_problem(text):
        raise StepError(
            f"The {what} cannot be used: {problem}. Write one plain sentence of at most "
            f"{MAX_SENTENCE_CHARS} characters, without links, Markdown or line breaks."
        )


@dataclass
class Investigation:
    toi: ToiId
    blind: bool = False
    candidate: CatalogEntry | None = None
    papers: list[ClassifiedPaper] | None = None
    papers_searched: bool = False
    neighbors: list[NeighborAssessment] | None = None
    neighbors_scanned: bool = False
    results: list[CheckResult] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)
    verdict_seen: Verdict | None = None
    """Last final verdict the agent saw through get_verdict."""
    checks_when_verdict_seen: int = 0

    @property
    def entry(self) -> CatalogEntry:
        if self.candidate is None:
            raise StepError("The candidate has not been loaded from the catalog yet.")
        return self.candidate

    @property
    def required(self) -> list[Check]:
        return required_checks(self.neighbors)

    @property
    def bright_neighbors(self) -> list[NeighborAssessment]:
        return [n for n in self.neighbors or [] if n.could_cause_dip]

    def result_for(self, check: Check) -> CheckResult | None:
        return next((r for r in self.results if r.check is check), None)

    def log(self, actor: str, text: str) -> None:
        self.trace.append(f"{actor}: {text}")


def load_candidate(inv: Investigation, sources: DataSources) -> CatalogEntry:
    """UC-01 step 2. Raises CandidateNotFoundError or SourceUnavailableError."""
    entry = sources.catalog.get_candidate(inv.toi)
    if inv.blind:
        # NFR-01: hide the catalog status and other names, so the check relies on the tests.
        entry = entry.model_copy(
            update={"disposition": None, "disposition_date": None, "aliases": []}
        )
    inv.candidate = entry
    inv.log("pipeline", f"loaded {inv.toi} from the exoplanet catalog")
    return entry


def find_papers(
    inv: Investigation, sources: DataSources, actor: str = "procedure"
) -> list[ClassifiedPaper] | None:
    """UC-01 step 3. Returns None when papers are hidden (blind test) or unreachable."""
    if inv.papers_searched:
        return inv.papers
    inv.papers_searched = True
    if inv.blind:
        inv.log(actor, "search_papers -> skipped, papers are hidden in a blind test")
        return None
    try:
        found = sources.papers.search(inv.toi, inv.entry.aliases)
    except SourceUnavailableError as exc:
        inv.problems.append(f"{exc}. The report lists no papers.")
        inv.log(actor, f"search_papers -> {exc.source} unavailable")
        return None
    inv.papers = [ClassifiedPaper(paper=p) for p in found]
    inv.log(actor, f"search_papers -> {len(found)} paper(s)")
    return inv.papers


def classify_paper(
    inv: Investigation, paper_id: str, stance: PaperStance, note: str, actor: str = "agent"
) -> ClassifiedPaper:
    """FR-05: record what a paper says about the candidate."""
    papers = inv.papers or []
    match = next((p for p in papers if p.paper.id == paper_id), None)
    if match is None:
        known = ", ".join(p.paper.id for p in papers) or "none"
        raise StepError(f"There is no paper with id '{paper_id}'. Known paper ids: {known}.")
    _require_plain(note, "justification")
    match.stance = stance
    match.note = note.strip()
    inv.log(actor, f"classify_paper({paper_id}) -> {stance.value}")
    return match


def scan_neighbors(
    inv: Investigation, sources: DataSources, actor: str = "procedure"
) -> list[NeighborAssessment] | None:
    """UC-01 step 4. Returns None when the star catalog could not be reached."""
    if inv.neighbors_scanned:
        return inv.neighbors
    inv.neighbors_scanned = True
    try:
        stars = sources.stars.stars_near(inv.entry, checks.NEARBY_RADIUS_ARCMIN)
    except SourceUnavailableError as exc:
        inv.problems.append(
            f"{exc}. A bright nearby star cannot be ruled out, so the centroid test is required."
        )
        inv.log(actor, f"find_nearby_stars -> {exc.source} unavailable")
        return None
    inv.neighbors = checks.assess_neighbors(inv.entry, stars)
    inv.log(
        actor,
        f"find_nearby_stars -> {len(inv.neighbors)} star(s) within "
        f"{checks.NEARBY_RADIUS_ARCMIN} arcmin, {len(inv.bright_neighbors)} bright enough to "
        "cause the dip",
    )
    return inv.neighbors


def run_check(
    inv: Investigation,
    sources: DataSources,
    check: Check,
    reason: str,
    *,
    actor: str = "procedure",
) -> CheckResult:
    """UC-01 steps 5-6. Running a check twice returns the first result.

    Raises StepError when FR-07 says another step must come first, or when the reason is not
    one plain sentence.
    """
    if existing := inv.result_for(check):
        return existing
    if not inv.neighbors_scanned:
        raise StepError(
            "Look for nearby stars first (find_nearby_stars): if one is bright enough to "
            "cause the dip, the centroid test has to come first (FR-07)."
        )
    if (
        Check.CENTROID in inv.required
        and check is not Check.CENTROID
        and inv.result_for(Check.CENTROID) is None
    ):
        raise StepError(
            "Run the centroid test first: a star bright enough to cause the dip may lie "
            "within 2.5 arcmin, so we must first check which star the dip comes from (FR-07)."
        )
    _require_plain(reason, "reason")
    reason = reason.strip()
    try:
        result = _measure(inv, sources, check, reason)
    except SourceUnavailableError as exc:
        # UC-01 *a: the check goes on, and the report says why this test could not run.
        result = CheckResult(
            check=check,
            status=CheckStatus.SKIPPED,
            reason=reason,
            finding=f"{exc}, so the test could not run.",
        )
    if actor == SAFETY_NET:
        result = result.model_copy(update={"auto_run": True})
    if result.status is CheckStatus.SKIPPED and check in inv.required:
        inv.problems.append(f"{check.label}: {result.finding}")
    inv.results.append(result)
    inv.log(actor, f"run_check({check.value}) -> {result.status.value}")
    return result


def _measure(inv: Investigation, sources: DataSources, check: Check, reason: str) -> CheckResult:
    """Run one check on the data. Raises SourceUnavailableError if the light curves are out."""
    entry = inv.entry
    match check:
        case Check.CENTROID:
            # None tells the test that the star catalog could not be reached.
            neighbors = None if inv.neighbors is None else inv.bright_neighbors
            return checks.centroid_check(sources.light_curves.centroid(entry), neighbors, reason)
        case Check.ODD_EVEN:
            return checks.odd_even_check(sources.light_curves.transit_metrics(entry), reason)
        case Check.SECONDARY_ECLIPSE:
            return checks.secondary_eclipse_check(
                sources.light_curves.transit_metrics(entry), reason
            )
        case Check.COMPANION_SIZE:
            return checks.companion_size_check(entry, reason)
        case _:
            assert_never(check)


def skip_check(
    inv: Investigation, check: Check, reason: str, actor: str = "procedure"
) -> CheckResult:
    """FR-08: record that an optional check was not run, and why."""
    if existing := inv.result_for(check):
        return existing
    if check in inv.required:
        raise StepError(
            f"The {check.label.lower()} is required for this candidate and cannot be skipped. "
            "Run it; if its data are missing, it is recorded as skipped automatically."
        )
    _require_plain(reason, "reason")
    result = CheckResult(
        check=check, status=CheckStatus.SKIPPED, reason=reason.strip(), finding="Not run."
    )
    inv.results.append(result)
    inv.log(actor, f"skip_check({check.value})")
    return result


def current_decision(inv: Investigation) -> Decision:
    return decide(inv.results, inv.required)
