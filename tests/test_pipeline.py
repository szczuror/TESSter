"""End-to-end checks with placeholder data and the standard procedure (no LLM)."""

import pytest
from helpers import catalog_only, make_entry

from tesster.models import Check, CheckStatus, NotChecked, Report, Verdict
from tesster.pipeline import check_candidate, check_many
from tesster.sources import CandidateIncompleteError, DataSources
from tesster.sources.fake import FixtureSources, load_fixtures
from tesster.sources.not_connected import NotConnected


def offline(toi: str, sources, settings, **kwargs) -> Report:
    outcome = check_candidate(toi, sources=sources, settings=settings, offline=True, **kwargs)
    assert isinstance(outcome, Report), outcome
    return outcome


def with_outage(toi: str, source: str) -> DataSources:
    """Placeholder data in which one source cannot be reached for one candidate."""
    data = load_fixtures()
    next(c for c in data["candidates"] if c["toi"] == toi)["unavailable"].append(source)
    fixtures = FixtureSources(data)
    return DataSources(fixtures, fixtures, fixtures, fixtures, placeholder=True)


@pytest.mark.parametrize(
    ("toi", "expected"), [(toi, Verdict(v)) for toi, _, v in FixtureSources().scenarios()]
)
def test_placeholder_candidates_get_their_expected_verdict(toi, expected, sources, settings):
    assert offline(toi, sources, settings).verdict is expected


def test_bright_neighbor_makes_centroid_test_run_first(sources, settings):
    report = offline("TOI-90003.01", sources, settings)
    assert [r.check for r in report.checks][0] is Check.CENTROID
    assert "nearby star" in report.cause


def test_every_test_says_why_it_was_run_or_skipped(sources, settings):
    report = offline("TOI-90001.01", sources, settings)
    centroid = next(r for r in report.checks if r.check is Check.CENTROID)
    assert centroid.status is CheckStatus.SKIPPED
    assert "not needed" in centroid.reason
    assert all(r.reason for r in report.checks)


def test_unreachable_paper_archive_is_reported_and_check_continues(sources, settings):
    report = offline("TOI-90004.01", sources, settings)
    assert report.papers is None
    assert any("Paper archive" in p for p in report.problems)
    assert report.verdict is Verdict.INCONCLUSIVE
    assert report.settle_by


def test_no_papers_is_not_an_error(sources, settings):
    report = offline("TOI-90002.01", sources, settings)
    assert report.papers == []
    assert report.problems == []


def test_catalog_false_positive_with_passing_tests_is_flagged(sources, settings):
    report = offline("TOI-90005.01", sources, settings)
    assert report.verdict is Verdict.LIKELY_PLANET
    assert any(
        "catalog lists this candidate as a false positive" in d for d in report.disagreements
    )


def test_unknown_candidate_is_not_checked(sources, settings):
    outcome = check_candidate("TOI-90009.01", sources=sources, settings=settings, offline=True)
    assert isinstance(outcome, NotChecked)
    assert "No candidate TOI-90009.01" in outcome.reason


def test_invalid_input_is_not_checked(sources, settings):
    outcome = check_candidate("TOI-abc", sources=sources, settings=settings, offline=True)
    assert isinstance(outcome, NotChecked)
    assert "TOI-1234.01" in outcome.reason


def test_blind_test_hides_catalog_status_and_papers(sources, settings):
    report = offline("TOI-90005.01", sources, settings, blind=True)
    assert report.blind
    assert report.candidate.disposition is None
    assert report.papers is None
    assert report.disagreements == []


def test_unreachable_star_catalog_makes_centroid_required(settings):
    report = offline("TOI-90001.01", with_outage("TOI-90001.01", "stars"), settings)
    assert report.neighbors is None
    assert report.checks[0].check is Check.CENTROID
    assert report.checks[0].status is CheckStatus.PASSED  # 0.4 +/- 0.5 arcsec is precise enough
    assert any("Star catalog" in p for p in report.problems)


def test_unreachable_star_catalog_needs_a_precise_centroid(settings):
    # 3.0 +/- 9.0 arcsec cannot rule out a bright star one TESS pixel away.
    report = offline("TOI-90004.01", with_outage("TOI-90004.01", "stars"), settings)
    assert report.checks[0].status is CheckStatus.UNCLEAR
    assert report.verdict is Verdict.INCONCLUSIVE


def test_unreachable_light_curve_archive_skips_its_tests_and_check_continues(settings):
    report = offline("TOI-90002.01", with_outage("TOI-90002.01", "light_curves"), settings)
    skipped = {r.check for r in report.checks if "could not be reached" in r.finding}
    assert skipped == {Check.ODD_EVEN, Check.SECONDARY_ECLIPSE}
    assert any("Light-curve archive" in p for p in report.problems)
    assert report.verdict is Verdict.INCONCLUSIVE


def test_sources_not_connected_yet_are_reported_as_missing_data(settings):
    report = offline("TOI-1234.01", catalog_only(make_entry()), settings)

    assert not report.placeholder_data
    assert report.papers is None  # an empty list would say that no paper mentions the candidate
    assert report.neighbors is None
    for source in ("Paper archive", "Star catalog", "Light-curve archive"):
        assert any(source in p and "is not connected" in p for p in report.problems), source
    # A bright nearby star cannot be ruled out without the star catalog, so the centroid test
    # is required and comes first (FR-07).
    assert [(r.check, r.status) for r in report.checks] == [
        (Check.CENTROID, CheckStatus.SKIPPED),
        (Check.ODD_EVEN, CheckStatus.SKIPPED),
        (Check.SECONDARY_ECLIPSE, CheckStatus.SKIPPED),
        (Check.COMPANION_SIZE, CheckStatus.PASSED),
    ]
    assert "is not connected" in report.checks[0].finding
    assert report.verdict is Verdict.INCONCLUSIVE


def test_catalog_alone_can_show_a_companion_too_big_for_a_planet(settings):
    # A star of 1.47 solar radii with a 2.4 % dip, as the catalog lists TOI-236.01.
    entry = make_entry(stellar_radius_rsun=1.47459, depth_ppm=23574.8)
    report = offline("TOI-1234.01", catalog_only(entry), settings)

    assert report.verdict is Verdict.FALSE_POSITIVE
    assert "a star rather than a planet" in report.cause


def test_candidate_the_catalog_lists_without_a_period_is_not_checked(settings):
    """FR-02: the user is told which value is missing."""

    class WithoutPeriod:
        def get_candidate(self, toi):
            raise CandidateIncompleteError(toi, ["orbital period"])

    off = NotConnected()
    sources = DataSources(catalog=WithoutPeriod(), papers=off, stars=off, light_curves=off)
    outcome = check_candidate("TOI-125.04", sources=sources, settings=settings, offline=True)

    assert isinstance(outcome, NotChecked)
    assert outcome.reason == (
        "The exoplanet catalog lists TOI-125.04 without its orbital period, so it cannot be "
        "checked."
    )


def test_batch_lists_likely_planets_first_and_unchecked_last(sources, settings):
    inputs = ["TOI-90002.01", "TOI-abc", "TOI-90004.01", "TOI-90001.01", "TOI-90005.01"]
    outcomes = check_many(inputs, sources=sources, settings=settings, offline=True)
    labels = [o.verdict.value if isinstance(o, Report) else "not checked" for o in outcomes]
    assert labels == [
        "likely planet",
        "likely planet",
        "inconclusive",
        "false positive",
        "not checked",
    ]
    assert [str(o.toi) for o in outcomes[:2]] == ["TOI-90001.01", "TOI-90005.01"]
