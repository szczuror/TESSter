import pytest

from tess_verifier.models import (
    Check,
    CheckResult,
    CheckStatus,
    NearbyStar,
    NeighborAssessment,
    Source,
    Verdict,
)
from tess_verifier.vetting.verdict import (
    CAUSES,
    ECLIPSING_BINARY_CHECKS,
    NEARBY_ECLIPSING_BINARY,
    SETTLE_BY,
    decide,
    required_checks,
)

P, F, U, S = CheckStatus.PASSED, CheckStatus.FAILED, CheckStatus.UNCLEAR, CheckStatus.SKIPPED
EB_ONLY = list(ECLIPSING_BINARY_CHECKS)
WITH_CENTROID = [Check.CENTROID, *ECLIPSING_BINARY_CHECKS]


def result(check: Check, status: CheckStatus) -> CheckResult:
    return CheckResult(check=check, status=status, reason="r", finding="Finding text.")


def neighbor(could_cause: bool) -> NeighborAssessment:
    star = NearbyStar(tic_id=1, separation_arcsec=30, tmag=12, source=Source(name="s", url="u"))
    return NeighborAssessment(star=star, max_depth_ppm=1, could_cause_dip=could_cause)


class TestRequiredChecks:
    def test_eclipsing_binary_checks_are_always_required(self):
        assert required_checks([]) == EB_ONLY

    def test_bright_neighbor_puts_centroid_first(self):
        assert required_checks([neighbor(False), neighbor(True)]) == WITH_CENTROID

    def test_unknown_neighbors_require_centroid(self):
        assert required_checks(None) == WITH_CENTROID


class TestVerdictRule:
    """FR-11 truth table."""

    def test_all_required_passed_is_likely_planet(self):
        decision = decide([result(c, P) for c in EB_ONLY], EB_ONLY)
        assert decision.verdict is Verdict.LIKELY_PLANET
        assert decision.cause is None

    def test_any_failed_test_is_false_positive_even_if_optional(self):
        results = [result(Check.CENTROID, F), *[result(c, P) for c in EB_ONLY]]
        assert decide(results, EB_ONLY).verdict is Verdict.FALSE_POSITIVE

    def test_optional_unclear_test_does_not_block_likely_planet(self):
        results = [result(Check.CENTROID, U), *[result(c, P) for c in EB_ONLY]]
        assert decide(results, EB_ONLY).verdict is Verdict.LIKELY_PLANET

    @pytest.mark.parametrize("status", [U, S])
    def test_required_test_without_pass_is_inconclusive(self, status):
        results = [result(Check.CENTROID, status), *[result(c, P) for c in EB_ONLY]]
        decision = decide(results, WITH_CENTROID)
        assert decision.verdict is Verdict.INCONCLUSIVE
        assert decision.settle_by == [SETTLE_BY[Check.CENTROID]]  # FR-13

    def test_required_test_not_run_is_inconclusive(self):
        decision = decide([result(Check.ODD_EVEN, P)], EB_ONLY)
        assert decision.verdict is Verdict.INCONCLUSIVE
        assert decision.not_run == [Check.SECONDARY_ECLIPSE, Check.COMPANION_SIZE]


class TestCause:
    """FR-12: a false positive names its likely cause."""

    def test_failed_centroid_points_to_a_nearby_star(self):
        decision = decide([result(Check.CENTROID, F)], WITH_CENTROID)
        assert decision.cause == CAUSES[Check.CENTROID]

    def test_failed_odd_even_points_to_an_eclipsing_binary(self):
        decision = decide([result(Check.ODD_EVEN, F)], EB_ONLY)
        assert "eclipsing binary" in decision.cause

    def test_failed_centroid_and_eclipsing_binary_test_point_to_a_nearby_eclipsing_binary(self):
        decision = decide([result(Check.CENTROID, F), result(Check.ODD_EVEN, F)], WITH_CENTROID)
        assert decision.cause == NEARBY_ECLIPSING_BINARY

    def test_template_reason_names_the_failed_test(self):
        decision = decide([result(Check.ODD_EVEN, F)], EB_ONLY)
        assert decision.template_reason == "The odd-even depth test failed: finding text."

    def test_cause_and_reason_do_not_depend_on_the_order_the_tests_ran_in(self):
        odd_even, size = result(Check.ODD_EVEN, F), result(Check.COMPANION_SIZE, F)
        assert decide([odd_even, size], EB_ONLY) == decide([size, odd_even], EB_ONLY)
        assert decide([size, odd_even], EB_ONLY).cause == CAUSES[Check.ODD_EVEN]

    def test_template_reason_names_every_failed_test(self):
        decision = decide([result(Check.COMPANION_SIZE, F), result(Check.ODD_EVEN, F)], EB_ONLY)
        assert decision.failed == [Check.ODD_EVEN, Check.COMPANION_SIZE]
        assert decision.template_reason == (
            "The odd-even depth test failed: finding text; the companion size test failed too."
        )
