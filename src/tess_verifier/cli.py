"""Command line: ``tess-verifier check TOI-...`` and ``tess-verifier samples``."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated

import typer
from pydantic_ai import AgentRunError, UserError
from pydantic_ai.messages import ModelMessage
from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.prompt import Prompt
from rich.table import Table

from tess_verifier.config import Settings, load_settings
from tess_verifier.models import NotChecked, Report
from tess_verifier.pipeline import ConfigurationError, check_candidate, check_many
from tess_verifier.report import render_report, render_summary, render_trace
from tess_verifier.sources import build_sources
from tess_verifier.sources.fake import FixtureSources

app = typer.Typer(
    help="TESS Verifier: checks whether a TESS candidate (TOI) looks like a planet or a "
    "false positive.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
err_console = Console(stderr=True)


@app.callback()
def main() -> None:
    _use_utf8_output()


def _use_utf8_output() -> None:
    """On Windows, redirected output defaults to a code page (e.g. cp1252) that cannot encode
    the characters Rich draws, so switch both streams to UTF-8."""
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
        if encoding != "utf8" and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


@app.command()
def check(
    tois: Annotated[list[str], typer.Argument(help="One or more TOI numbers, e.g. TOI-1234.01.")],
    offline: Annotated[
        bool, typer.Option("--offline", help="Run the standard procedure without an LLM.")
    ] = False,
    blind: Annotated[
        bool,
        typer.Option("--blind", help="Hide catalog status, names and papers (for evaluation)."),
    ] = False,
    model: Annotated[
        str | None,
        typer.Option(help="LLM as provider:model. Overrides TESS_VERIFIER_MODEL."),
    ] = None,
    out: Annotated[Path | None, typer.Option(help="Folder to save Markdown reports in.")] = None,
    chat: Annotated[
        bool,
        typer.Option(
            "--chat",
            help="Ask follow-up questions after the report (one TOI, needs an LLM, "
            "not with --blind).",
        ),
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Show every tool call and the token usage.")
    ] = False,
) -> None:
    """Check candidates and show the report (one TOI) or a summary (several TOIs)."""
    settings = load_settings()
    if model:
        settings = settings.model_copy(update={"model": model})
    if chat and (offline or len(tois) != 1):
        err_console.print("[red]--chat needs exactly one TOI and an LLM (no --offline).[/red]")
        raise typer.Exit(2)
    if chat and blind:
        err_console.print(
            "[red]--chat does not work with --blind: the follow-up questions would show the "
            "model the candidate's name.[/red]"
        )
        raise typer.Exit(2)

    sources = build_sources(settings.data)
    options = {"sources": sources, "settings": settings, "offline": offline, "blind": blind}
    try:
        if len(tois) == 1:
            outcomes: list[Report | NotChecked] = [check_candidate(tois[0], **options)]
        else:
            outcomes = check_many(tois, **options)
    except ConfigurationError as exc:
        err_console.print(f"[red]The LLM is not set up:[/red] {escape(str(exc))}")
        err_console.print(
            "Put your provider's API key in .env (see .env.example), pick another model with "
            "--model, or run without an LLM using --offline."
        )
        raise typer.Exit(2) from None

    reports = [o for o in outcomes if isinstance(o, Report)]
    if len(tois) == 1:
        if isinstance(outcomes[0], NotChecked):
            err_console.print(f"[red]Not checked:[/red] {escape(outcomes[0].reason)}")
            raise typer.Exit(1)
        console.print(Markdown(render_report(reports[0])))
    else:
        console.print(Markdown(render_summary(outcomes)))

    if verbose:
        for report in reports:
            console.print(render_trace(report), highlight=False, markup=False)
    if out:
        _save(out, outcomes, reports)
    if not reports:
        # UC-03 1a: none of the inputs could be checked.
        err_console.print("[red]None of the inputs could be checked.[/red]")
        raise typer.Exit(1)
    if chat:
        _chat(reports[0], settings)


@app.command()
def samples() -> None:
    """List the placeholder candidates of this version and what each one shows."""
    table = Table(title="Placeholder candidates (made-up data)")
    table.add_column("TOI", no_wrap=True)
    table.add_column("Scenario")
    table.add_column("Expected verdict", no_wrap=True)
    for toi, scenario, expected in FixtureSources().scenarios():
        table.add_row(toi, scenario, expected)
    console.print(table)
    console.print("Try: tess-verifier check TOI-90003.01 --offline")


def _save(folder: Path, outcomes: Sequence[Report | NotChecked], reports: Sequence[Report]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for report in reports:
        (folder / f"{report.toi}.md").write_text(render_report(report), encoding="utf-8")
    if len(outcomes) > 1:
        (folder / "summary.md").write_text(render_summary(outcomes), encoding="utf-8")
    console.print(f"Saved {len(reports)} report(s) to {escape(str(folder))}")


def _chat(report: Report, settings: Settings) -> None:
    """UC-02: answer questions about the report until the user enters an empty line."""
    from tess_verifier.agent.followup import ask_followup

    console.print("\nAsk about this report. An empty line ends the conversation.")
    history: list[ModelMessage] | None = None
    while True:
        try:
            question = Prompt.ask(
                "[bold cyan]Question[/bold cyan]", default="", show_default=False, console=console
            )
        except (EOFError, KeyboardInterrupt):
            break
        if not question.strip():
            break
        try:
            answer, history = ask_followup(report, question, history, settings)
        except (UserError, AgentRunError) as exc:
            err_console.print(f"[red]The LLM could not answer:[/red] {escape(str(exc))}")
            continue
        console.print(Markdown(answer))
