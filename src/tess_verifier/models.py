"""Domain model: candidate identifiers, data from outside sources, checks, verdicts and reports.

Terms follow docs/glossary.md. In code a verification test is called a *check*, because pytest
treats every class whose name starts with ``Test`` as a test case; reports still say "test".
"""

from __future__ import annotations

import re
from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, computed_field

TOI_FORMAT_HINT = "TOI-1234.01"

_TOI_RE = re.compile(r"^TOI[-\s]?(\d+)\.(\d{2})$", re.IGNORECASE)
_TOI_WITHOUT_SUFFIX_RE = re.compile(r"^TOI[-\s]?\d+$", re.IGNORECASE)
_TIC_RE = re.compile(r"^TIC[-\s]?\d+$", re.IGNORECASE)


class InvalidToiError(ValueError):
    """The input is not a TOI number the system can check (UC-01 1a)."""


class ToiId(BaseModel, frozen=True):
    """A TESS Object of Interest number, e.g. TOI-1234.01: star 1234, candidate 01."""

    star: int
    candidate: int

    def __str__(self) -> str:
        return f"TOI-{self.star}.{self.candidate:02d}"


def parse_toi(text: str) -> ToiId:
    """Parse user input such as ``TOI-1234.01`` (case and surrounding spaces do not matter)."""
    cleaned = text.strip()
    if match := _TOI_RE.match(cleaned):
        return ToiId(star=int(match[1]), candidate=int(match[2]))
    if _TOI_WITHOUT_SUFFIX_RE.match(cleaned):
        raise InvalidToiError(
            f"'{cleaned}' has no candidate suffix. Checking all candidates of a star is not "
            f"supported yet, so give one candidate, e.g. {TOI_FORMAT_HINT}."
        )
    if _TIC_RE.match(cleaned):
        raise InvalidToiError(
            f"TIC numbers are not supported yet. Give the candidate's TOI number, "
            f"e.g. {TOI_FORMAT_HINT}."
        )
    raise InvalidToiError(
        f"'{cleaned}' is not a valid TOI number. Expected e.g. {TOI_FORMAT_HINT}."
    )


class Source(BaseModel, frozen=True):
    """Where a fact comes from. Every outside fact in a report links to one (FR-14)."""

    name: str
    url: str
    retrieved: date | None = None
    placeholder: bool = False


class Disposition(StrEnum):
    """TFOPWG disposition of a TOI in the catalogs."""

    PC = "PC"
    CP = "CP"
    KP = "KP"
    FP = "FP"
    FA = "FA"
    APC = "APC"

    @property
    def label(self) -> str:
        return _DISPOSITION_LABELS[self]


_DISPOSITION_LABELS = {
    Disposition.PC: "planet candidate",
    Disposition.CP: "confirmed planet",
    Disposition.KP: "known planet",
    Disposition.FP: "false positive",
    Disposition.FA: "false alarm",
    Disposition.APC: "ambiguous planet candidate",
}


class CatalogEntry(BaseModel):
    """A candidate as listed in an exoplanet catalog (UC-01 step 2)."""

    toi: ToiId
    tic_id: int
    tmag: float
    """TESS magnitude of the target star."""
    ra_deg: float
    dec_deg: float
    period_days: float
    epoch_btjd: float
    duration_hours: float
    depth_ppm: float
    stellar_radius_rsun: float | None = None
    disposition: Disposition | None = None
    disposition_date: date | None = None
    aliases: list[str] = []
    """Other names of the object, e.g. the name of a confirmed planet."""
    source: Source


class Paper(BaseModel):
    """A paper that mentions the candidate (FR-04)."""

    id: str
    title: str
    year: int
    abstract: str
    source: Source


class PaperStance(StrEnum):
    """What a paper says about the candidate (FR-05)."""

    CONFIRMS = "confirms"
    RULES_OUT = "rules_out"
    MENTIONS = "mentions"
    UNCLASSIFIED = "unclassified"

    @property
    def label(self) -> str:
        return {
            PaperStance.CONFIRMS: "confirms the candidate",
            PaperStance.RULES_OUT: "rules the candidate out",
            PaperStance.MENTIONS: "only mentions the candidate",
            PaperStance.UNCLASSIFIED: "not classified",
        }[self]


class ClassifiedPaper(BaseModel):
    paper: Paper
    stance: PaperStance = PaperStance.UNCLASSIFIED
    note: str = ""


class NearbyStar(BaseModel):
    """A star near the target, as listed in a star catalog."""

    tic_id: int
    separation_arcsec: float
    tmag: float
    source: Source


class NeighborAssessment(BaseModel):
    """Whether a nearby star is bright enough to cause the dip on its own (FR-07)."""

    star: NearbyStar
    max_depth_ppm: float
    """Depth seen on the target if this star were completely eclipsed."""
    could_cause_dip: bool


class TransitMetrics(BaseModel):
    """Numbers measured from the light curve. In v1 they come from placeholder data."""

    odd_depth_ppm: float
    odd_depth_err_ppm: float
    odd_transits: int
    even_depth_ppm: float
    even_depth_err_ppm: float
    even_transits: int
    secondary_depth_ppm: float
    secondary_depth_err_ppm: float
    source: Source


class CentroidMeasurement(BaseModel):
    """Shift of the light-weighted centre of the image during the dip."""

    offset_arcsec: float
    offset_err_arcsec: float
    source: Source


class Check(StrEnum):
    """Verification tests the system can run."""

    CENTROID = "centroid"
    ODD_EVEN = "odd_even_depth"
    SECONDARY_ECLIPSE = "secondary_eclipse"
    COMPANION_SIZE = "companion_size"

    @property
    def label(self) -> str:
        return {
            Check.CENTROID: "Centroid test",
            Check.ODD_EVEN: "Odd-even depth test",
            Check.SECONDARY_ECLIPSE: "Secondary eclipse test",
            Check.COMPANION_SIZE: "Companion size test",
        }[self]


class CheckStatus(StrEnum):
    """Outcome of a check (FR-09); *skipped* means it was not run."""

    PASSED = "passed"
    FAILED = "failed"
    UNCLEAR = "unclear"
    SKIPPED = "skipped"


class CheckResult(BaseModel):
    check: Check
    status: CheckStatus
    reason: str
    """Why the check was run or skipped (FR-08)."""
    finding: str
    """What the check found, in plain words."""
    sources: list[Source] = []
    auto_run: bool = False
    """True when the safety net ran the check because the agent did not."""


class Verdict(StrEnum):
    LIKELY_PLANET = "likely planet"
    FALSE_POSITIVE = "false positive"
    INCONCLUSIVE = "inconclusive"


class Report(BaseModel):
    """Everything the user sees after a check (UC-01 step 8)."""

    toi: ToiId
    generated_at: datetime
    checked_with: str
    blind: bool
    placeholder_data: bool
    candidate: CatalogEntry
    papers: list[ClassifiedPaper] | None
    """None when papers were not searched (blind test) or the archive could not be reached."""
    neighbors: list[NeighborAssessment] | None
    """None when the star catalog could not be reached."""
    checks: list[CheckResult]
    verdict: Verdict
    main_reason: str
    cause: str | None = None
    settle_by: list[str] = []
    disagreements: list[str] = []
    problems: list[str] = []
    notes: list[str] = []
    trace: list[str] = []
    usage: str | None = None
    duration_seconds: float = 0.0

    @computed_field
    @property
    def sources(self) -> list[Source]:
        """Every outside source used in the report, without repeats."""
        found: list[Source] = [self.candidate.source]
        found += [p.paper.source for p in self.papers or []]
        found += [n.star.source for n in self.neighbors or []]
        for result in self.checks:
            found += result.sources
        unique: list[Source] = []
        for source in found:
            if source not in unique:
                unique.append(source)
        return unique


class NotChecked(BaseModel):
    """An input that produced no report, with the reason (FR-02, UC-03 2a)."""

    input: str
    reason: str
