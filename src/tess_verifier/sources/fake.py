"""Placeholder implementations of all sources, read from fixtures/candidates.json.

The fixtures use made-up TOI numbers (TOI-9000x.01) so they cannot be mistaken for real
candidates. Source links point to the real services from docs/useful-links.md, and every
source is marked as placeholder, so reports show a warning banner.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date
from importlib import resources
from typing import Any

from tess_verifier.models import (
    CatalogEntry,
    CentroidMeasurement,
    NearbyStar,
    Paper,
    Source,
    ToiId,
    TransitMetrics,
    parse_toi,
)
from tess_verifier.sources.base import (
    CandidateNotFoundError,
    DataSources,
    SourceUnavailableError,
)

PAPER_ARCHIVE_NAME = "Paper archive (NASA ADS / arXiv)"
STAR_CATALOG_NAME = "Star catalog (TIC at MAST)"
LIGHT_CURVE_ARCHIVE_NAME = "Light-curve archive (TESS data at MAST)"


def load_fixtures() -> dict[str, Any]:
    text = resources.files("tess_verifier.sources").joinpath("fixtures/candidates.json")
    return json.loads(text.read_text(encoding="utf-8"))


class FixtureSources:
    """Implements every source protocol from one fixture file."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        data = data if data is not None else load_fixtures()
        retrieved = date.fromisoformat(data["retrieved"])
        self._sources = {
            key: Source(name=s["name"], url=s["url"], retrieved=retrieved, placeholder=True)
            for key, s in data["sources"].items()
        }
        self._candidates = {str(parse_toi(c["toi"])): c for c in data["candidates"]}

    def scenarios(self) -> list[tuple[str, str, str]]:
        """(TOI, scenario, expected verdict) for every placeholder candidate."""
        return [(toi, c["scenario"], c["expected_verdict"]) for toi, c in self._candidates.items()]

    def _raw(self, toi: ToiId) -> dict[str, Any]:
        try:
            return self._candidates[str(toi)]
        except KeyError:
            raise CandidateNotFoundError(toi) from None

    def _check_reachable(self, raw: dict[str, Any], key: str, name: str) -> None:
        if key in raw.get("unavailable", []):
            raise SourceUnavailableError(name, "simulated outage in the placeholder data")

    def get_candidate(self, toi: ToiId) -> CatalogEntry:
        raw = self._raw(toi)
        fields = {
            k: raw[k]
            for k in (
                "tic_id",
                "tmag",
                "ra_deg",
                "dec_deg",
                "period_days",
                "epoch_btjd",
                "duration_hours",
                "depth_ppm",
                "stellar_radius_rsun",
                "disposition",
                "disposition_date",
                "aliases",
            )
        }
        return CatalogEntry(toi=toi, source=self._sources["catalog"], **fields)

    def search(self, toi: ToiId, aliases: Sequence[str] = ()) -> list[Paper]:
        raw = self._raw(toi)
        self._check_reachable(raw, "papers", PAPER_ARCHIVE_NAME)
        archive = self._sources["papers"]
        return [
            Paper(
                id=p["id"],
                title=p["title"],
                year=p["year"],
                abstract=p["abstract"],
                source=archive.model_copy(update={"name": f"{archive.name}: {p['id']}"}),
            )
            for p in raw["papers"]
        ]

    def stars_near(self, candidate: CatalogEntry, radius_arcmin: float) -> list[NearbyStar]:
        raw = self._raw(candidate.toi)
        self._check_reachable(raw, "stars", STAR_CATALOG_NAME)
        return [
            NearbyStar(**s, source=self._sources["stars"])
            for s in raw["neighbors"]
            if s["separation_arcsec"] <= radius_arcmin * 60
        ]

    def transit_metrics(self, candidate: CatalogEntry) -> TransitMetrics | None:
        raw = self._raw(candidate.toi)
        self._check_reachable(raw, "light_curves", LIGHT_CURVE_ARCHIVE_NAME)
        metrics = raw["transit_metrics"]
        if metrics is None:
            return None
        return TransitMetrics(**metrics, source=self._sources["light_curves"])

    def centroid(self, candidate: CatalogEntry) -> CentroidMeasurement | None:
        raw = self._raw(candidate.toi)
        self._check_reachable(raw, "light_curves", LIGHT_CURVE_ARCHIVE_NAME)
        centroid = raw["centroid"]
        if centroid is None:
            return None
        return CentroidMeasurement(**centroid, source=self._sources["light_curves"])


def fake_sources() -> DataSources:
    fixtures = FixtureSources()
    return DataSources(
        catalog=fixtures,
        papers=fixtures,
        stars=fixtures,
        light_curves=fixtures,
        placeholder=True,
    )
