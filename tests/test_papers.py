"""The arXiv paper archive and candidate-mention check (FR-04, FR-14, NFR-02)."""

from datetime import date

import pytest
import requests

from tesster.models import parse_toi
from tesster.sources import SourceUnavailableError
from tesster.sources.base import PAPER_ARCHIVE_NAME
from tesster.sources.papers import ArxivPapers, build_query, mentions_candidate

TODAY = date(2026, 11, 15)
TOI_270 = parse_toi("TOI-270.01")
TOI_495 = parse_toi("TOI-495.01")

SAMPLE_FEED = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1903.06107v2</id>
    <published>2019-03-14T18:00:00Z</published>
    <title>A super-Earth and two sub-Neptunes transiting
      the nearby and quiet M dwarf TOI-270</title>
    <summary>We report the discovery of three planets around TOI-270:
      TOI-270 b, TOI-270 c (TOI-270.01) and TOI-270 d.</summary>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2511.13830v1</id>
    <published>2025-11-18T12:00:00Z</published>
    <title>The atmospheric composition of TOI-270 d</title>
    <summary>We analyse JWST transmission spectra of the sub-Neptune TOI-270 d.</summary>
  </entry>
</feed>
"""


def test_only_papers_that_mention_the_candidate_are_kept():
    """NFR-02: a paper about another planet of the same star (TOI-270 d) is filtered out."""
    seen: list[str] = []

    def ask(query: str) -> str:
        seen.append(query)
        return SAMPLE_FEED

    papers = ArxivPapers(ask=ask, today=lambda: TODAY).search(TOI_270, aliases=["TOI-270 c"])

    assert seen == [build_query(TOI_270, ["TOI-270 c"])]
    assert len(papers) == 1
    paper = papers[0]
    assert paper.id == "arXiv:1903.06107v2"
    assert paper.year == 2019
    assert paper.title == (
        "A super-Earth and two sub-Neptunes transiting the nearby and quiet M dwarf TOI-270"
    )
    assert "TOI-270 c" in paper.abstract
    assert paper.source.name == "arXiv: arXiv:1903.06107v2"
    assert paper.source.url == "https://arxiv.org/abs/1903.06107v2"
    assert paper.source.retrieved == TODAY
    assert not paper.source.placeholder
    assert not set(paper.source.url) & set(" ()<>")


@pytest.mark.parametrize(
    ("text", "toi", "aliases", "expected"),
    [
        ("Photometry of TOI-270.01 shows a clean transit.", TOI_270, ["TOI-270 c"], True),
        ("Photometry of TOI 270.01 shows a clean transit.", TOI_270, ["TOI-270 c"], True),
        ("Transmission spectroscopy of TOI-270 c.", TOI_270, ["TOI-270 c"], True),
        ("Transmission spectroscopy of TOI-270c.", TOI_270, ["TOI-270 c"], True),
        ("Transmission spectroscopy of TOI 270c.", TOI_270, ["TOI-270 c"], True),
        ("Transmission spectroscopy of TOI-270 d.", TOI_270, ["TOI-270 c"], False),
        ("Transmission spectroscopy of TOI-270 b.", TOI_270, ["TOI-270 c"], False),
        ("Phase curve of WASP-121 b with TESS.", TOI_495, ["WASP-121 b"], True),
        ("Phase curve of WASP-121b with TESS.", TOI_495, ["WASP-121 b"], True),
        ("Phase curve of WASP-1210 b.", TOI_495, ["WASP-121 b"], False),
        ("Radial velocities of TOI-1285 show a binary.", parse_toi("TOI-1285.01"), [], True),
        ("Photometry of TOI-1285.02.", parse_toi("TOI-1285.01"), [], False),
    ],
)
def test_mentions_candidate_checks_exact_object_names(text, toi, aliases, expected):
    assert mentions_candidate(text, toi, aliases) is expected


def test_network_error_is_reported_as_unavailable():
    def fail(query: str) -> str:
        raise requests.ConnectionError("arXiv did not respond")

    with pytest.raises(SourceUnavailableError, match="arXiv did not respond") as raised:
        ArxivPapers(ask=fail).search(TOI_270)
    assert raised.value.source == PAPER_ARCHIVE_NAME


def test_malformed_xml_is_reported_as_unavailable():
    with pytest.raises(SourceUnavailableError, match="invalid XML"):
        ArxivPapers(ask=lambda q: "<not-xml").search(TOI_270)
