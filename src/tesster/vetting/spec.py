"""What every verification test declares about itself.

Each test module in vetting/checks/ defines one ``SPEC``. The registry (vetting/registry.py)
lists them, so the pipeline, the verdict rule and the agent treat all tests the same way.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from tesster.models import CatalogEntry, Check, CheckResult, NeighborAssessment
from tesster.sources.base import DataSources

Neighbors = list[NeighborAssessment] | None
"""Stars near the target. None when the star catalog could not be reached."""


class Family(StrEnum):
    """The kind of false positive a test looks for."""

    SOURCE = "source"
    """The dip may come from another star nearby (FR-07)."""
    ECLIPSING_BINARY = "eclipsing_binary"
    """The dip may come from two stars eclipsing each other (FR-06)."""


def always(neighbors: Neighbors) -> bool:
    return True


def never(neighbors: Neighbors) -> bool:
    return False


@dataclass(frozen=True)
class CheckContext:
    """What a test gets when it runs."""

    entry: CatalogEntry
    neighbors: Neighbors
    sources: DataSources
    reason: str
    """Why the test is run (FR-08). It goes into the result as it is."""


@dataclass(frozen=True, kw_only=True)
class CheckSpec:
    check: Check
    family: Family
    looks_for: str
    """What the test checks, in one line for the agent."""
    cause: str
    """FR-12: the likely cause when the test fails."""
    settle_by: str
    """FR-13: the observation or data that would settle the test when it gives no result."""
    standard_reason: str | Callable[[Neighbors], str]
    """Why the standard procedure and the safety net run the test (FR-08)."""
    run: Callable[[CheckContext], CheckResult]
    """Gets the data the test needs and applies its rule. May raise SourceUnavailableError."""
    required_when: Callable[[Neighbors], bool] = never
    """Whether every verdict needs this test for this candidate."""
    not_needed_reason: str | None = None
    """Why the standard procedure skips the test when it is not required. None: it says nothing."""

    def reason(self, neighbors: Neighbors) -> str:
        """The standard reason for this candidate."""
        if callable(self.standard_reason):
            return self.standard_reason(neighbors)
        return self.standard_reason
