"""The agent's tools and rules, driven by a scripted fake model (no network, no API key)."""

import pytest
from pydantic_ai import UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from tess_verifier import investigation as steps
from tess_verifier.agent.followup import ask_followup, followup_agent
from tess_verifier.agent.verifier import candidate_prompt, verifier_agent
from tess_verifier.config import Settings
from tess_verifier.investigation import Investigation
from tess_verifier.models import Check, PaperStance, Report, Verdict, parse_toi
from tess_verifier.pipeline import ConfigurationError, check_candidate


class Script:
    """A fake LLM that plays fixed turns: a list of tool calls, an exception, or the final text."""

    def __init__(self, *turns):
        self.turns = turns
        self.sent: list[str] = []

    def __call__(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        self.sent += [str(getattr(part, "content", "")) for part in messages[-1].parts]
        turn = self.turns[sum(isinstance(m, ModelResponse) for m in messages)]
        if isinstance(turn, Exception):
            raise turn
        if isinstance(turn, str):
            return ModelResponse(parts=[TextPart(turn)])
        return ModelResponse(parts=[ToolCallPart(name, args) for name, args in turn])

    def sent_text(self) -> str:
        return "\n".join(self.sent)


def run_agent(script: Script, toi: str, sources, settings) -> Report:
    with verifier_agent.override(model=FunctionModel(script)):
        report = check_candidate(toi, sources=sources, settings=settings)
    assert isinstance(report, Report), report
    return report


def call(check: str, reason: str = "A reason.") -> tuple[str, dict]:
    return ("run_check", {"check": check, "reason": reason})


def test_agent_must_run_the_centroid_test_first_when_a_bright_star_is_near(sources, settings):
    script = Script(
        [("search_papers", {})],
        [
            (
                "classify_paper",
                {
                    "paper_id": "placeholder-2026-042",
                    "stance": "rules_out",
                    "justification": "Ground photometry shows the eclipse on a nearby star.",
                },
            )
        ],
        [("find_nearby_stars", {})],
        [call("odd_even_depth")],  # refused: FR-07 says the centroid test comes first
        [call("centroid", "A star 38 arcsec away could cause the dip.")],
        [call("odd_even_depth"), call("secondary_eclipse"), call("companion_size")],
        [("get_verdict", {})],
        "The light centre moves toward a star 38 arcsec away, so the dip comes from that star.",
    )
    report = run_agent(script, "TOI-90003.01", sources, settings)

    assert "Run the centroid test first" in script.sent_text()
    assert [r.check for r in report.checks] == [
        Check.CENTROID,
        Check.ODD_EVEN,
        Check.SECONDARY_ECLIPSE,
        Check.COMPANION_SIZE,
    ]
    assert report.checks[0].reason == "A star 38 arcsec away could cause the dip."
    assert report.verdict is Verdict.FALSE_POSITIVE
    assert report.main_reason.startswith("The light centre moves")
    assert report.papers[0].stance is PaperStance.RULES_OUT
    assert report.checked_with.startswith("LLM agent")
    assert not any(r.auto_run for r in report.checks)


def test_safety_net_runs_the_steps_the_agent_left_out(sources, settings):
    script = Script(
        [("find_nearby_stars", {})],
        [call("odd_even_depth")],
        "Looks like a planet.",
    )
    report = run_agent(script, "TOI-90001.01", sources, settings)

    assert [r.check for r in report.checks if r.auto_run] == [
        Check.SECONDARY_ECLIPSE,
        Check.COMPANION_SIZE,
    ]
    assert report.papers is not None  # the safety net searched for papers (FR-04)
    assert report.papers[0].stance is PaperStance.UNCLASSIFIED
    assert report.main_reason != "Looks like a planet."  # the agent never saw the verdict
    assert any("run automatically" in n for n in report.notes)
    assert any("template" in n for n in report.notes)


def test_unknown_paper_id_is_sent_back_to_the_model(sources, settings):
    script = Script(
        [("search_papers", {})],
        [
            (
                "classify_paper",
                {"paper_id": "2019Natur.000", "stance": "confirms", "justification": "x"},
            )
        ],
        [
            (
                "classify_paper",
                {
                    "paper_id": "placeholder-2025-017",
                    "stance": "mentions",
                    "justification": "It only lists the candidate in a catalogue.",
                },
            )
        ],
        "Done.",
    )
    report = run_agent(script, "TOI-90001.01", sources, settings)

    assert "Known paper ids: placeholder-2025-017" in script.sent_text()
    assert report.papers[0].stance is PaperStance.MENTIONS


def test_required_test_cannot_be_skipped(sources, settings):
    script = Script(
        [("find_nearby_stars", {})],
        [("skip_check", {"check": "odd_even_depth", "reason": "Not needed."})],
        "Done.",
    )
    report = run_agent(script, "TOI-90001.01", sources, settings)

    assert "is required for this candidate" in script.sent_text()
    odd_even = next(r for r in report.checks if r.check is Check.ODD_EVEN)
    assert odd_even.auto_run


def test_model_error_falls_back_to_the_standard_procedure(sources, settings):
    script = Script([("find_nearby_stars", {})], UnexpectedModelBehavior("the model went silent"))
    report = run_agent(script, "TOI-90003.01", sources, settings)

    assert report.checked_with.startswith("standard procedure (fallback")
    assert any("UnexpectedModelBehavior" in n for n in report.notes)
    assert report.verdict is Verdict.FALSE_POSITIVE


def test_unknown_model_is_a_configuration_error(sources):
    with pytest.raises(ConfigurationError, match="Unknown model"):
        check_candidate("TOI-90001.01", sources=sources, settings=Settings(model="nosuch:model"))


def test_prompt_gives_the_candidate_data(sources):
    inv = Investigation(toi=parse_toi("TOI-90003.01"))
    steps.load_candidate(inv, sources)
    prompt = candidate_prompt(inv)
    assert "TOI-90003.01" in prompt
    assert "planet candidate (PC)" in prompt
    assert "depth 800 ppm" in prompt


def test_blind_prompt_hides_names_and_catalog_status(sources):
    inv = Investigation(toi=parse_toi("TOI-90005.01"), blind=True)
    steps.load_candidate(inv, sources)
    prompt = candidate_prompt(inv)
    assert "90005" not in prompt
    assert "TIC" not in prompt
    assert "false positive" not in prompt
    assert "blind test" in prompt


def test_followup_answers_from_the_report_without_paper_abstracts(sources, settings):
    report = check_candidate("TOI-90003.01", sources=sources, settings=settings, offline=True)
    seen: dict[str, str] = {}

    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen["instructions"] = info.instructions or ""
        return ModelResponse(parts=[TextPart("Because a bright star lies 38 arcsec away.")])

    with followup_agent.override(model=FunctionModel(answer)):
        text, history = ask_followup(report, "Why was the centroid test first?", None, settings)
        _, longer_history = ask_followup(report, "And then?", history, settings)

    assert text.startswith("Because")
    assert '"verdict": "false positive"' in seen["instructions"]
    assert "Seeing-limited photometry shows" in seen["instructions"]  # the title is there
    assert "Ground-based time-series photometry" not in seen["instructions"]  # the abstract not
    assert len(longer_history) > len(history)
