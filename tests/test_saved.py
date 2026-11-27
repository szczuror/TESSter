"""Saved archive data: saving what connected sources return and replaying it without the network."""

from datetime import date

import pytest
from helpers import SOURCE, make_entry

from tesster.models import (
    CentroidMeasurement,
    Check,
    CheckStatus,
    NearbyStar,
    Paper,
    Report,
    Source,
    TransitMetrics,
    Verdict,
    parse_toi,
)
from tesster.pipeline import check_candidate
from tesster.sources import (
    CandidateNotFoundError,
    DataSources,
    SourceNotConnectedError,
    build_sources,
)
from tesster.sources.not_connected import NotConnected
from tesster.sources.papers import mentions_candidate
from tesster.sources.reference import REFERENCE_CANDIDATES
from tesster.sources.saved import SAVED_DIR, save_candidate, use_saved

TOI = parse_toi("TOI-270.01")
OTHER_TOI = parse_toi("TOI-700.01")


class RecordingSources:
    """Fake sources that count how many times each method is called."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.entry = make_entry(toi=TOI, tic_id=259377017, aliases=["TOI-270 c"])
        self.paper = Paper(
            id="arXiv:1903.06107v2",
            title="A super-Earth and two sub-Neptunes transiting TOI-270",
            year=2019,
            abstract="We report TOI-270 c around the nearby M dwarf TOI-270.",
            source=Source(
                name="arXiv: arXiv:1903.06107v2",
                url="https://arxiv.org/abs/1903.06107v2",
                retrieved=date(2026, 11, 15),
            ),
        )
        self.star = NearbyStar(tic_id=99, separation_arcsec=45.0, tmag=16.2, source=SOURCE)
        self.distant_star = NearbyStar(
            tic_id=100, separation_arcsec=140.0, tmag=15.0, source=SOURCE
        )
        self.metrics = TransitMetrics(
            odd_depth_ppm=3420.0,
            odd_depth_err_ppm=80.0,
            odd_transits=5,
            even_depth_ppm=3460.0,
            even_depth_err_ppm=80.0,
            even_transits=5,
            secondary_depth_ppm=10.0,
            secondary_depth_err_ppm=40.0,
            source=SOURCE,
        )
        self.centroid_shift = CentroidMeasurement(
            offset_arcsec=0.3, offset_err_arcsec=0.4, source=SOURCE
        )

    def as_data_sources(self) -> DataSources:
        return DataSources(catalog=self, papers=self, stars=self, light_curves=self)

    def get_candidate(self, toi):
        self.calls.append(f"catalog:{toi}")
        if toi != TOI:
            raise CandidateNotFoundError(toi)
        return self.entry

    def search(self, toi, aliases=()):
        self.calls.append(f"papers:{toi}")
        return [self.paper]

    def stars_near(self, candidate, radius_arcmin):
        self.calls.append(f"stars:{candidate.toi}")
        return [self.star, self.distant_star]

    def transit_metrics(self, candidate):
        self.calls.append(f"transit_metrics:{candidate.toi}")
        return self.metrics

    def centroid(self, candidate):
        self.calls.append(f"centroid:{candidate.toi}")
        return self.centroid_shift


def test_saved_candidate_is_replayed_without_calling_the_inner_sources(tmp_path):
    live = RecordingSources()
    path = save_candidate(TOI, live.as_data_sources(), tmp_path)
    assert path == tmp_path / "TOI-270.01.json"

    failing = NotConnected()
    replayed = use_saved(
        DataSources(catalog=failing, papers=failing, stars=failing, light_curves=failing),
        tmp_path,
    )

    entry = replayed.catalog.get_candidate(TOI)
    assert entry == live.entry
    assert replayed.papers.search(TOI, entry.aliases) == [live.paper]
    assert replayed.stars.stars_near(entry, 2.5) == [live.star, live.distant_star]
    assert replayed.stars.stars_near(entry, 1.0) == [live.star]
    assert replayed.light_curves.transit_metrics(entry) == live.metrics
    assert replayed.light_curves.centroid(entry) == live.centroid_shift


def test_unsaved_candidate_falls_through_to_the_inner_sources(tmp_path):
    live = RecordingSources()
    replayed = use_saved(live.as_data_sources(), tmp_path)

    with pytest.raises(CandidateNotFoundError):
        replayed.catalog.get_candidate(OTHER_TOI)
    assert live.calls == ["catalog:TOI-700.01"]


def test_sources_not_connected_when_saving_still_fall_through_later(tmp_path):
    """If Package A (stars and centroid) was not connected when a candidate was saved,
    those calls still reach the wrapped source."""
    live = RecordingSources()
    off = NotConnected()
    partial = DataSources(catalog=live, papers=live, stars=off, light_curves=off)
    save_candidate(TOI, partial, tmp_path)

    replayed = use_saved(partial, tmp_path)
    entry = replayed.catalog.get_candidate(TOI)
    assert replayed.papers.search(TOI, entry.aliases) == [live.paper]
    with pytest.raises(SourceNotConnectedError, match="Star catalog"):
        replayed.stars.stars_near(entry, 2.5)
    with pytest.raises(SourceNotConnectedError, match="Light-curve archive"):
        replayed.light_curves.centroid(entry)


@pytest.mark.parametrize("candidate", REFERENCE_CANDIDATES, ids=lambda c: c.toi)
def test_saved_reference_candidates_run_without_the_network(candidate, settings):
    """Every reference candidate has saved archive data that run in tests and CI without the
    network, with valid links (FR-14) and verified paper mentions (NFR-02)."""
    assert (SAVED_DIR / f"{candidate.toi}.json").is_file()
    outcome = check_candidate(
        candidate.toi, sources=build_sources(), settings=settings, offline=True
    )
    assert isinstance(outcome, Report)
    assert not outcome.placeholder_data
    assert outcome.papers is not None
    for classified in outcome.papers:
        text = f"{classified.paper.title} {classified.paper.abstract}"
        assert mentions_candidate(text, outcome.toi, outcome.candidate.aliases)
    for source in outcome.sources:
        assert source.url.startswith("https://")
        assert not set(source.url) & set(" ()<>")


def test_saved_reference_candidates_give_expected_check_outcomes(settings):
    sources = build_sources()

    def check_map(toi: str) -> tuple[Verdict, dict[Check, CheckStatus]]:
        report = check_candidate(toi, sources=sources, settings=settings, offline=True)
        assert isinstance(report, Report)
        return report.verdict, {r.check: r.status for r in report.checks}

    for planet in ("TOI-270.01", "TOI-562.01"):
        _, results = check_map(planet)
        assert results[Check.ODD_EVEN] is CheckStatus.PASSED
        assert results[Check.SECONDARY_ECLIPSE] is CheckStatus.PASSED
        assert results[Check.COMPANION_SIZE] is CheckStatus.PASSED

    verdict_236, results_236 = check_map("TOI-236.01")
    assert verdict_236 is Verdict.FALSE_POSITIVE
    assert results_236[Check.COMPANION_SIZE] is CheckStatus.FAILED

    verdict_1637, results_1637 = check_map("TOI-1637.01")
    assert verdict_1637 is Verdict.FALSE_POSITIVE
    assert results_1637[Check.SECONDARY_ECLIPSE] is CheckStatus.FAILED

    verdict_3503, results_3503 = check_map("TOI-3503.01")
    assert verdict_3503 is Verdict.FALSE_POSITIVE
    assert results_3503[Check.ODD_EVEN] is CheckStatus.FAILED
