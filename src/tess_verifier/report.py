"""Reports as Markdown (one source of truth for the terminal and for files)."""

from __future__ import annotations

from collections.abc import Sequence

from tess_verifier.models import CheckStatus, NotChecked, Report, Source
from tess_verifier.vetting.checks import NEARBY_RADIUS_ARCMIN

PLACEHOLDER_BANNER = (
    "> **Placeholder data.** The values below are made up for development and do not describe "
    "a real object."
)
BLIND_BANNER = "> **Blind test.** Catalog status, names and papers were hidden from the check."

STATUS_MARK = {
    CheckStatus.PASSED: "passed",
    CheckStatus.FAILED: "**failed**",
    CheckStatus.UNCLEAR: "*unclear*",
    CheckStatus.SKIPPED: "skipped",
}


def link(source: Source) -> str:
    name = f"{source.name} (placeholder)" if source.placeholder else source.name
    return f"[{name}]({source.url})"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_report(report: Report) -> str:
    c = report.candidate
    out: list[str] = [f"# {report.toi}: {report.verdict.value}", ""]
    if report.placeholder_data:
        out += [PLACEHOLDER_BANNER, ""]
    if report.blind:
        out += [BLIND_BANNER, ""]
    out += [f"**Verdict: {report.verdict.value}.** {report.main_reason}", ""]
    if report.cause:
        out += [f"**Likely cause:** {report.cause}.", ""]
    if report.settle_by:
        out += ["**What would settle it:**", "", *[f"- {s}" for s in report.settle_by], ""]
    for note in report.disagreements:
        out += [f"> **Disagreement:** {note}", ""]

    out += ["## Candidate", ""]
    if c.disposition is not None:
        out.append(
            f"- Catalog status: {c.disposition.label} ({c.disposition.value}), "
            f"as of {c.disposition_date}. Source: {link(c.source)}"
        )
    elif report.blind:
        out.append("- Catalog status: hidden (blind test)")
    else:
        out.append(f"- Catalog status: not given. Source: {link(c.source)}")
    radius = f"{c.stellar_radius_rsun:.2f} solar radii" if c.stellar_radius_rsun else "unknown"
    out += [
        f"- Target star: TIC {c.tic_id}, TESS magnitude {c.tmag:.1f}, radius {radius}. "
        f"Source: {link(c.source)}",
        f"- Transit: period {c.period_days:.4f} d, depth {c.depth_ppm:.0f} ppm, duration "
        f"{c.duration_hours:.1f} h. Source: {link(c.source)}",
        "",
    ]

    out += ["## Papers", ""]
    if report.papers is None:
        out.append(
            "Papers were hidden in this blind test."
            if report.blind
            else "Papers could not be searched (see Problems)."
        )
    elif not report.papers:
        out.append("No papers mention this candidate.")
    else:
        for p in report.papers:
            line = f"- *{p.paper.title}* ({p.paper.year}): {p.stance.label}."
            if p.note:
                line += f" {p.note}"
            out.append(f"{line} {link(p.paper.source)}")
    out.append("")

    out += [f"## Nearby stars (within {NEARBY_RADIUS_ARCMIN} arcmin)", ""]
    if report.neighbors is None:
        out.append("The star catalog could not be reached (see Problems).")
    elif not report.neighbors:
        out.append("No stars found.")
    else:
        out += [
            "| TIC | Separation | TESS mag | Largest dip it could cause | Could cause the dip? |",
            "|---|---|---|---|---|",
        ]
        for n in report.neighbors:
            out.append(
                f"| {n.star.tic_id} | {n.star.separation_arcsec:.0f} arcsec | {n.star.tmag:.1f} "
                f"| {n.max_depth_ppm:,.0f} ppm | {'yes' if n.could_cause_dip else 'no'} |"
            )
        out += ["", f"Source: {link(report.neighbors[0].star.source)}"]
    out.append("")

    out += [
        "## Tests",
        "",
        "| # | Test | Result | Why it was run or skipped | Finding | Source |",
        "|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(report.checks, start=1):
        reason = r.reason + (" *(run automatically)*" if r.auto_run else "")
        sources = ", ".join(link(s) for s in r.sources) or "-"
        out.append(
            f"| {i} | {r.check.label} | {STATUS_MARK[r.status]} | {_cell(reason)} "
            f"| {_cell(r.finding)} | {sources} |"
        )
    out.append("")

    if report.problems:
        out += ["## Problems and missing data", "", *[f"- {p}" for p in report.problems], ""]
    if report.notes:
        out += ["## Notes", "", *[f"- {n}" for n in report.notes], ""]

    out += ["## Sources", ""]
    for i, s in enumerate(report.sources, start=1):
        name = f"{s.name} (placeholder)" if s.placeholder else s.name
        retrieved = f", retrieved {s.retrieved}" if s.retrieved else ""
        # The bare URL keeps the address visible in terminals that do not show link targets.
        out.append(f"{i}. {name}{retrieved}: <{s.url}>")
    out.append("")

    footer = (
        f"*Checked with {report.checked_with} in {report.duration_seconds:.1f} s, "
        f"{report.generated_at:%Y-%m-%d %H:%M} UTC."
    )
    if report.usage:
        footer += f" Usage: {report.usage}."
    out.append(footer + "*")
    return "\n".join(out) + "\n"


def render_trace(report: Report) -> str:
    lines = [f"Trace for {report.toi}:", *[f"  {i}. {t}" for i, t in enumerate(report.trace, 1)]]
    if report.usage:
        lines.append(f"  Usage: {report.usage}")
    return "\n".join(lines)


def render_summary(outcomes: Sequence[Report | NotChecked]) -> str:
    """UC-03 / FR-16: one line per input, likely planets first."""
    out = [
        "# Candidates checked",
        "",
        "| TOI | Verdict | Main reason |",
        "|---|---|---|",
    ]
    for o in outcomes:
        if isinstance(o, Report):
            out.append(f"| {o.toi} | {o.verdict.value} | {_cell(o.main_reason)} |")
        else:
            out.append(f"| {_cell(o.input)} | not checked | {_cell(o.reason)} |")
    if any(isinstance(o, Report) and o.placeholder_data for o in outcomes):
        out += ["", PLACEHOLDER_BANNER]
    return "\n".join(out) + "\n"
