from helpers import catalog_only, make_entry

from tesster.models import CheckStatus, NotChecked, Report
from tesster.pipeline import check_candidate, check_many
from tesster.report import BLIND_BANNER, PLACEHOLDER_BANNER, render_report, render_summary


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


def test_report_says_which_data_are_missing_when_a_source_is_not_connected(settings):
    markdown = render_report(offline("TOI-1234.01", catalog_only(make_entry()), settings))

    assert "No papers mention this candidate" not in markdown  # nobody looked, so it is unknown
    assert "Papers could not be searched (see Problems)." in markdown
    assert "The star catalog was not available (see Problems)." in markdown
    assert "Paper archive (NASA ADS / arXiv) is not connected in this version" in markdown
    assert PLACEHOLDER_BANNER not in markdown


def test_catalog_status_is_shown_with_the_date_of_the_catalog_entry(sources, settings):
    """FR-03."""
    markdown = render_report(offline("TOI-90001.01", sources, settings))
    assert (
        "- Catalog status: planet candidate (PC), catalog entry last updated 2026-09-15."
        in markdown
    )


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


def test_nearby_stars_table_lists_only_bright_neighbors_and_counts_fainter_ones(sources, settings):
    """A crowded field can hold thousands of stars within 2.5 arcmin. The report lists only
    those bright enough to cause the dip, plus a count of the rest."""
    with_bright_and_faint = render_report(offline("TOI-90003.01", sources, settings))
    assert "| 900300031 | 38 arcsec | 13.1 |" in with_bright_and_faint
    assert "900300032" not in with_bright_and_faint
    assert "1 other star is too faint to cause the dip." in with_bright_and_faint

    only_faint = render_report(offline("TOI-90001.01", sources, settings))
    assert "900100011" not in only_faint
    assert (
        "No star within 2.5 arcmin is bright enough to cause the dip (2 fainter stars checked)."
        in only_faint
    )
