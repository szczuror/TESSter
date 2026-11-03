"""Follow-up questions about a report (UC-02, FR-15)."""

from __future__ import annotations

import json

import pydantic_ai
from pydantic_ai import Agent, RunContext, UsageLimits
from pydantic_ai.messages import ModelMessage
from pydantic_ai.settings import ModelSettings

from tess_verifier.agent.instructions import FOLLOWUP_INSTRUCTIONS
from tess_verifier.config import Settings
from tess_verifier.models import Report

pydantic_ai.BANNER_ENABLED = False

followup_agent = Agent(
    deps_type=Report,
    output_type=str,
    instructions=FOLLOWUP_INSTRUCTIONS,
    name="tess-verifier-followup",
)


@followup_agent.instructions
def report_context(ctx: RunContext[Report]) -> str:
    return "Report (JSON):\n" + report_for_followup(ctx.deps)


def report_for_followup(report: Report) -> str:
    """The report as JSON for the model.

    Paper abstracts are left out: they are outside text that should not reach the instructions,
    and answers need only titles, stances and links. The tool trace is left out too.
    """
    data = report.model_dump(
        mode="json",
        exclude={"trace": True, "papers": {"__all__": {"paper": {"abstract"}}}},
    )
    return json.dumps(data, indent=1, ensure_ascii=False)


def ask_followup(
    report: Report,
    question: str,
    history: list[ModelMessage] | None,
    settings: Settings,
) -> tuple[str, list[ModelMessage]]:
    """Answer one question. Returns the answer and the conversation so far."""
    result = followup_agent.run_sync(
        question,
        deps=report,
        model=settings.model,
        message_history=history,
        model_settings=ModelSettings(max_tokens=settings.max_tokens),
        usage_limits=UsageLimits(request_limit=5),
    )
    return result.output, result.all_messages()
