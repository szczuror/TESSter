from tess_verifier.models import CheckStatus, NotChecked, Report
from tess_verifier.pipeline import check_candidate, check_many
from tess_verifier.report import BLIND_BANNER, PLACEHOLDER_BANNER, render_report, render_summary


def offline(toi: str, sources, settings, **kwargs) -> Report:
    report = check_candidate(toi, sources=sources, settings=settings, offline=True, **kwargs)
    assert isinstance(report, Report)
    return report


def test_every_outside_source_is_linked(sources, settings):
    """FR-14: every fact from an outside source links to it."""
    report = offline("TOI-90003.01", sources, settings)
    markdown = render_report(report)
    assert report.sources
    for source in report.sources:
        assert f"]({source.url})" in markdown
        assert f"<{source.url}>" in markdown
    for result in report.checks:
        if result.status is not CheckStatus.SKIPPED:
            assert result.sources, result.check


def test_report_shows_verdict_reason_and_cause(sources, settings):
    report = offline("TOI-90002.01", sources, settings)
    markdown = render_report(report)
    assert markdown.startswith("# TOI-90002.01: false positive")
    assert f"**Verdict: false positive.** {report.main_reason}" in markdown
    assert "**Likely cause:** two stars eclipsing each other" in markdown


def test_inconclusive_report_says_what_would_settle_it(sources, settings):
    markdown = render_report(offline("TOI-90004.01", sources, settings))
    assert "**What would settle it:**" in markdown
    assert "## Problems and missing data" in markdown


def test_placeholder_and_blind_banners(sources, settings):
    assert PLACEHOLDER_BANNER in render_report(offline("TOI-90001.01", sources, settings))
    blind = render_report(offline("TOI-90001.01", sources, settings, blind=True))
    assert BLIND_BANNER in blind
    assert "Catalog status: hidden (blind test)" in blind


def test_summary_lists_inputs_that_were_not_checked(sources, settings):
    outcomes = check_many(
        ["TOI-90002.01", "TOI-xyz", "TOI-90001.01"],
        sources=sources,
        settings=settings,
        offline=True,
    )
    summary = render_summary(outcomes)
    lines = [line for line in summary.splitlines() if line.startswith("| TOI")]
    assert lines[1].startswith("| TOI-90001.01 | likely planet")
    assert lines[2].startswith("| TOI-90002.01 | false positive")
    assert lines[3].startswith("| TOI-xyz | not checked")
    assert isinstance(outcomes[-1], NotChecked)
