"""Every verification test the system can run, listed in one place.

To add a test: add a member and its label to ``models.Check``, write the test and its ``SPEC``
in a new module in vetting/checks/, and list the ``SPEC`` below.
"""

from __future__ import annotations

from tesster.models import Check
from tesster.vetting.checks import centroid, companion_size, odd_even, secondary_eclipse
from tesster.vetting.spec import CheckSpec, Neighbors

_LISTED = (centroid.SPEC, odd_even.SPEC, secondary_eclipse.SPEC, companion_size.SPEC)

SPECS: dict[Check, CheckSpec] = {spec.check: spec for spec in _LISTED}
"""The order matters. It is the order the standard procedure runs the tests in, and when several
tests fail, the cause and the main reason come from the first of them in this order, not from
the order the tests ran in, so repeated checks give the same report (NFR-03)."""

if len(SPECS) != len(_LISTED):
    raise RuntimeError("Two tests in vetting/registry.py have the same Check id.")
if _missing := [check.value for check in Check if check not in SPECS]:
    raise RuntimeError(f"No test is listed in vetting/registry.py for: {', '.join(_missing)}.")


def spec_for(check: Check) -> CheckSpec:
    return SPECS[check]


def priority(check: Check) -> int:
    """Position of the test in the registry. A lower number comes first."""
    return list(SPECS).index(check)


def required_checks(neighbors: Neighbors) -> list[Check]:
    """Checks every verdict needs, in the order they must run.

    The centroid test comes first when a star bright enough to cause the dip lies within
    2.5 arcmin (FR-07), and also when the star catalog could not be reached (``None``),
    because then such a star cannot be ruled out. The tests for two eclipsing stars are always
    required (FR-06).
    """
    return [spec.check for spec in SPECS.values() if spec.required_when(neighbors)]
