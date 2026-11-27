"""Paper archive: searches arXiv and keeps only papers confirmed to mention the candidate
(UC-01 step 3, FR-04, FR-14, NFR-02)."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Callable, Sequence
from datetime import date

import requests

from tesster.models import Paper, Source, ToiId
from tesster.sources.base import PAPER_ARCHIVE_NAME, SourceUnavailableError

ARXIV_API_URL = "https://export.arxiv.org/api/query"
ARXIV_SOURCE_NAME = "arXiv"
TIME_LIMIT_SECONDS = 30.0
MAX_QUERY_RESULTS = 15
MAX_PAPERS = 5

_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
_PLANET_LETTER_RE = re.compile(r"^(.+?)\s+([b-z])$", re.IGNORECASE)


def ask_arxiv(query: str, timeout: float = TIME_LIMIT_SECONDS) -> str:
    """Fetch the Atom XML feed for ``query`` from the arXiv API, or raise SourceUnavailableError."""
    try:
        response = requests.get(
            ARXIV_API_URL,
            params={
                "search_query": query,
                "max_results": str(MAX_QUERY_RESULTS),
                "sortBy": "relevance",
                "sortOrder": "descending",
            },
            timeout=timeout,
        )
        response.raise_for_status()
        return response.text
    except requests.RequestException as exc:
        raise SourceUnavailableError(PAPER_ARCHIVE_NAME, _summary(exc)) from exc


class ArxivPapers:
    """Implements PaperArchive using the public arXiv API."""

    def __init__(
        self,
        ask: Callable[[str], str] | None = None,
        today: Callable[[], date] = date.today,
        max_papers: int = MAX_PAPERS,
    ) -> None:
        self._ask = ask
        self._today = today
        self._max_papers = max_papers

    def search(self, toi: ToiId, aliases: Sequence[str] = ()) -> list[Paper]:
        query = build_query(toi, aliases)
        ask = self._ask if self._ask is not None else ask_arxiv
        try:
            xml_text = ask(query)
        except requests.RequestException as exc:
            raise SourceUnavailableError(PAPER_ARCHIVE_NAME, _summary(exc)) from exc
        entries = _parse_feed(xml_text, self._today())
        verified = [
            paper
            for paper in entries
            if mentions_candidate(f"{paper.title} {paper.abstract}", toi, aliases)
        ]
        return verified[: self._max_papers]


def build_query(toi: ToiId, aliases: Sequence[str] = ()) -> str:
    """Build an arXiv search query covering the TOI number and any known aliases."""
    terms: list[str] = [
        f"TOI-{toi.star}.{toi.candidate:02d}",
        f"TOI {toi.star}.{toi.candidate:02d}",
    ]
    for alias in aliases:
        cleaned = " ".join(alias.split())
        if not cleaned:
            continue
        if cleaned not in terms:
            terms.append(cleaned)
        if match := _PLANET_LETTER_RE.match(cleaned):
            compact = f"{match[1]}{match[2]}"
            if compact not in terms:
                terms.append(compact)
    if not aliases:
        for base in (f"TOI-{toi.star}", f"TOI {toi.star}"):
            if base not in terms:
                terms.append(base)
    return " OR ".join(f'all:"{term}"' for term in terms)


def mentions_candidate(text: str, toi: ToiId, aliases: Sequence[str] = ()) -> bool:
    """NFR-02: confirm in code that ``text`` mentions the candidate or one of its aliases."""
    return any(pattern.search(text) is not None for pattern in _mention_patterns(toi, aliases))


def _mention_patterns(toi: ToiId, aliases: Sequence[str]) -> list[re.Pattern[str]]:
    patterns: list[re.Pattern[str]] = [
        re.compile(rf"\bTOI[-\s]+{toi.star}\.{toi.candidate:02d}(?!\d)", re.IGNORECASE),
    ]
    for alias in aliases:
        cleaned = " ".join(alias.split())
        if not cleaned:
            continue
        if match := _PLANET_LETTER_RE.match(cleaned):
            host = _flexible_name_pattern(match[1])
            letter = re.escape(match[2])
            patterns.append(re.compile(rf"\b{host}[-\s]?{letter}\b", re.IGNORECASE))
        else:
            patterns.append(re.compile(rf"\b{_flexible_name_pattern(cleaned)}\b", re.IGNORECASE))
    if not aliases and toi.candidate == 1:
        # When no planet alias is known, allow 'TOI-1234' or 'TOI-1234 b' unless it names
        # another candidate suffix (.02, .03, ...) or another planet letter (c..z).
        patterns.append(
            re.compile(
                rf"\bTOI[-\s]+{toi.star}(?!\.(?!01\b)\d|[-\s]*[c-z]\b)\b",
                re.IGNORECASE,
            )
        )
    return patterns


def _flexible_name_pattern(name: str) -> str:
    """Match a star/object name allowing spaces or hyphens between tokens."""
    parts = [re.escape(part) for part in re.split(r"[-\s]+", name.strip()) if part]
    return r"[-\s]+".join(parts)


def _parse_feed(xml_text: str, retrieved: date) -> list[Paper]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise SourceUnavailableError(PAPER_ARCHIVE_NAME, " returned invalid XML") from exc

    papers: list[Paper] = []
    seen_ids: set[str] = set()
    for entry in root.findall("atom:entry", _ATOM_NS):
        raw_id = (entry.findtext("atom:id", "", _ATOM_NS) or "").strip()
        title = _clean_whitespace(entry.findtext("atom:title", "", _ATOM_NS) or "")
        abstract = _clean_whitespace(entry.findtext("atom:summary", "", _ATOM_NS) or "")
        published = (entry.findtext("atom:published", "", _ATOM_NS) or "").strip()
        if not raw_id or not title:
            continue
        paper_id, url = _normalize_arxiv_id(raw_id)
        if paper_id in seen_ids:
            continue
        year = _parse_year(published)
        if year is None:
            continue
        seen_ids.add(paper_id)
        papers.append(
            Paper(
                id=paper_id,
                title=title,
                year=year,
                abstract=abstract,
                source=Source(
                    name=f"{ARXIV_SOURCE_NAME}: {paper_id}",
                    url=url,
                    retrieved=retrieved,
                ),
            )
        )
    return papers


def _normalize_arxiv_id(raw_url: str) -> tuple[str, str]:
    url = raw_url.replace("http://", "https://", 1)
    short = url.rsplit("/abs/", 1)[-1].strip("/")
    paper_id = f"arXiv:{short}" if not short.startswith("arXiv:") else short
    return paper_id, f"https://arxiv.org/abs/{short}"


def _parse_year(timestamp: str) -> int | None:
    try:
        return int(timestamp[:4])
    except ValueError:
        return None


def _clean_whitespace(text: str) -> str:
    return " ".join(text.split())


def _summary(exc: Exception) -> str:
    lines = str(exc).strip().splitlines()
    return lines[0][:200] if lines else type(exc).__name__
