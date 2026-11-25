"""The check registry: what every test declares, and what the rest of the code reads from it."""

from dataclasses import replace

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from tesster.agent.verifier import verifier_agent
from tesster.investigation import sentence_problem
from tesster.models import (
    Check,
    CheckResult,
    CheckStatus,
    NearbyStar,
    NeighborAssessment,
    Source,
    Verdict,
)
from tesster.pipeline import check_candidate
from tesster.vetting import registry
from tesster.vetting.registry import SPECS
from tesster.vetting.spec import Weight, always, never
from tesster.vetting.verdict import decide

FIRST_FOUR = [Check.CENTROID, Check.ODD_EVEN, Check.SECONDARY_ECLIPSE, Check.COMPANION_SIZE]
BRIGHT_NEIGHBOR = NeighborAssessment(
    star=NearbyStar(tic_id=1, separation_arcsec=30, tmag=12, source=Source(name="s", url="u")),
    max_depth_ppm=1,
    could_cause_dip=True,
)


def result(check: Check, status: CheckStatus) -> CheckResult:
    return CheckResult(check=check, status=status, reason="r", finding="Finding text.")


def test_every_check_has_a_spec_and_a_label():
    assert set(SPECS) == set(Check)
    assert all(spec.check is check for check, spec in SPECS.items())
    assert all(check.label for check in Check)


def test_centroid_test_comes_first_in_the_registry():
    # FR-07: the standard procedure runs the tests in registry order.
    assert next(iter(SPECS)) is Check.CENTROID


def test_the_first_four_tests_keep_their_order():
    # NFR-03: when several tests fail, the cause and the main reason come from the first one.
    assert [check for check in SPECS if check in FIRST_FOUR] == FIRST_FOUR


@pytest.mark.parametrize("check", list(Check))
@pytest.mark.parametrize("neighbors", [None, [BRIGHT_NEIGHBOR]], ids=["no catalog", "bright star"])
def test_registry_texts_are_plain_sentences(check, neighbors):
    """The reasons go through run_check and skip_check, which refuse anything else."""
    spec = SPECS[check]
    texts = [spec.looks_for, spec.cause, spec.settle_by, spec.reason(neighbors)]
    if spec.not_needed_reason is not None:
        texts.append(spec.not_needed_reason)
    for text in texts:
        assert sentence_problem(text) is None, text


def test_supporting_test_cannot_be_required():
    spec = SPECS[Check.COMPANION_SIZE]
    assert replace(spec, weight=Weight.SUPPORTING, required_when=never)
    with pytest.raises(ValueError, match="supporting test cannot be required"):
        replace(spec, weight=Weight.SUPPORTING, required_when=always)


class TestSupportingTests:
    """A supporting test is shown in the report but never changes the verdict."""

    @pytest.fixture(autouse=True)
    def companion_size_is_supporting(self, monkeypatch):
        spec = replace(SPECS[Check.COMPANION_SIZE], weight=Weight.SUPPORTING, required_when=never)
        monkeypatch.setitem(registry.SPECS, Check.COMPANION_SIZE, spec)

    def test_it_is_not_required(self):
        assert registry.required_checks([]) == [Check.ODD_EVEN, Check.SECONDARY_ECLIPSE]

    def test_its_failure_does_not_change_the_verdict(self):
        results = [
            result(Check.ODD_EVEN, CheckStatus.PASSED),
            result(Check.SECONDARY_ECLIPSE, CheckStatus.PASSED),
            result(Check.COMPANION_SIZE, CheckStatus.FAILED),
        ]
        decision = decide(results, registry.required_checks([]))
        assert decision.verdict is Verdict.LIKELY_PLANET
        assert decision.failed == []
        assert decision.cause is None

    def test_its_failure_is_left_out_of_a_false_positive(self):
        results = [
            result(Check.ODD_EVEN, CheckStatus.FAILED),
            result(Check.SECONDARY_ECLIPSE, CheckStatus.PASSED),
            result(Check.COMPANION_SIZE, CheckStatus.FAILED),
        ]
        decision = decide(results, registry.required_checks([]))
        assert decision.verdict is Verdict.FALSE_POSITIVE
        assert decision.failed == [Check.ODD_EVEN]
        assert decision.template_reason == "The odd-even depth test failed: finding text."


def test_model_is_told_about_every_test_in_the_registry(sources, settings):
    seen = {}

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.update({tool.name: tool for tool in info.function_tools})
        return ModelResponse(parts=[TextPart("Done.")])

    with verifier_agent.override(model=FunctionModel(model)):
        check_candidate("TOI-90001.01", sources=sources, settings=settings)

    tool = seen["run_check"]
    for check, spec in SPECS.items():
        assert f"- {check.value}: {spec.looks_for}" in tool.description
    arguments = tool.parameters_json_schema["properties"]
    assert arguments["check"]["description"] == "The test to run."
    assert arguments["reason"]["description"].startswith("Why this test is run")
