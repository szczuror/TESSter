"""Saved archive answers, replayed without the network when they exist on disk.

Saving what the source protocols return sits as one layer around ``DataSources``, so it does not
depend on how each archive is read. When a saved file has an answer for a source, that answer is
used automatically; when the file or a section of it is missing (for instance, an archive that
was not connected when the file was saved), the call goes through to the wrapped source.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from tesster.models import (
    CatalogEntry,
    CentroidMeasurement,
    NearbyStar,
    Paper,
    ToiId,
    TransitMetrics,
)
from tesster.sources.base import DataSources, SourceNotConnectedError
from tesster.vetting.checks.neighbors import NEARBY_RADIUS_ARCMIN

SAVED_DIR = Path(__file__).resolve().parent / "saved"
"""Default folder with saved archive answers for the reference candidates."""


class SavedSources:
    """Wraps DataSources and answers from JSON files in ``folder`` when they exist."""

    def __init__(self, inner: DataSources, folder: Path = SAVED_DIR) -> None:
        self._inner = inner
        self._folder = folder
        self._cache: dict[str, dict[str, Any] | None] = {}

    def _saved(self, toi: ToiId) -> dict[str, Any] | None:
        key = str(toi)
        if key not in self._cache:
            path = self._folder / f"{key}.json"
            if path.is_file():
                self._cache[key] = json.loads(path.read_text(encoding="utf-8"))
            else:
                self._cache[key] = None
        return self._cache[key]

    def get_candidate(self, toi: ToiId) -> CatalogEntry:
        raw = self._saved(toi)
        if raw is not None and "candidate" in raw:
            return CatalogEntry.model_validate(raw["candidate"])
        return self._inner.catalog.get_candidate(toi)

    def search(self, toi: ToiId, aliases: Sequence[str] = ()) -> list[Paper]:
        raw = self._saved(toi)
        if raw is not None and "papers" in raw:
            return [Paper.model_validate(p) for p in raw["papers"]]
        return self._inner.papers.search(toi, aliases)

    def stars_near(self, candidate: CatalogEntry, radius_arcmin: float) -> list[NearbyStar]:
        raw = self._saved(candidate.toi)
        if raw is not None and "stars" in raw:
            limit_arcsec = radius_arcmin * 60.0
            return [s for s in _unpack_stars(raw["stars"]) if s.separation_arcsec <= limit_arcsec]
        return self._inner.stars.stars_near(candidate, radius_arcmin)

    def transit_metrics(self, candidate: CatalogEntry) -> TransitMetrics | None:
        raw = self._saved(candidate.toi)
        if raw is not None and "transit_metrics" in raw:
            metrics = raw["transit_metrics"]
            return None if metrics is None else TransitMetrics.model_validate(metrics)
        return self._inner.light_curves.transit_metrics(candidate)

    def centroid(self, candidate: CatalogEntry) -> CentroidMeasurement | None:
        raw = self._saved(candidate.toi)
        if raw is not None and "centroid" in raw:
            centroid = raw["centroid"]
            return None if centroid is None else CentroidMeasurement.model_validate(centroid)
        return self._inner.light_curves.centroid(candidate)


def use_saved(sources: DataSources, folder: Path = SAVED_DIR) -> DataSources:
    """Wrap ``sources`` so saved answers in ``folder`` are used automatically when they exist."""
    saved = SavedSources(sources, folder)
    return DataSources(
        catalog=saved,
        papers=saved,
        stars=saved,
        light_curves=saved,
        placeholder=sources.placeholder,
    )


def save_candidate(
    toi: ToiId,
    sources: DataSources,
    folder: Path = SAVED_DIR,
    *,
    radius_arcmin: float = NEARBY_RADIUS_ARCMIN,
) -> Path:
    """Query the connected sources in ``sources`` for ``toi`` and write the answers to ``folder``.

    Sources that raise ``SourceNotConnectedError`` are left out of the file, so a later run falls
    through to the wrapped source until those archives are connected and saved too.
    """
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{toi}.json"
    data: dict[str, Any] = {}
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))

    entry = sources.catalog.get_candidate(toi)
    data["candidate"] = entry.model_dump(mode="json")

    try:
        papers = sources.papers.search(toi, entry.aliases)
    except SourceNotConnectedError:
        pass
    else:
        data["papers"] = [p.model_dump(mode="json") for p in papers]

    try:
        stars = sources.stars.stars_near(entry, radius_arcmin)
    except SourceNotConnectedError:
        pass
    else:
        data["stars"] = _pack_stars(stars)

    try:
        metrics = sources.light_curves.transit_metrics(entry)
    except SourceNotConnectedError:
        pass
    else:
        data["transit_metrics"] = None if metrics is None else metrics.model_dump(mode="json")

    try:
        centroid = sources.light_curves.centroid(entry)
    except SourceNotConnectedError:
        pass
    else:
        data["centroid"] = None if centroid is None else centroid.model_dump(mode="json")

    path.write_text(_to_json(data), encoding="utf-8")
    return path


def _pack_stars(stars: Sequence[NearbyStar]) -> list[dict[str, Any]]:
    """Nearby stars grouped by source, one ``[tic_id, separation_arcsec, tmag]`` row per star.

    A crowded field has over a thousand stars from one cone search, so writing the source once
    keeps the saved file small.
    """
    groups: dict[str, dict[str, Any]] = {}
    for star in stars:
        source = star.source.model_dump(mode="json")
        key = json.dumps(source, sort_keys=True)
        group = groups.setdefault(key, {"source": source, "rows": []})
        group["rows"].append([star.tic_id, star.separation_arcsec, star.tmag])
    return list(groups.values())


def _unpack_stars(groups: list[dict[str, Any]]) -> list[NearbyStar]:
    return [
        NearbyStar(tic_id=tic_id, separation_arcsec=separation, tmag=tmag, source=group["source"])
        for group in groups
        for tic_id, separation, tmag in group["rows"]
    ]


def _to_json(data: dict[str, Any]) -> str:
    """Indented JSON with every list of plain values (such as a star row) on one line."""
    return _dump(data, 0) + "\n"


def _dump(value: Any, level: int) -> str:
    def plain(item: Any) -> bool:
        return not isinstance(item, dict | list)

    if isinstance(value, list) and all(plain(item) for item in value):
        return json.dumps(value, ensure_ascii=False)
    if not isinstance(value, dict | list) or not value:
        return json.dumps(value, ensure_ascii=False)
    inner = "  " * (level + 1)
    if isinstance(value, dict):
        items = [
            f"{inner}{json.dumps(k, ensure_ascii=False)}: {_dump(v, level + 1)}"
            for k, v in value.items()
        ]
        opening, closing = "{", "}"
    else:
        items = [f"{inner}{_dump(v, level + 1)}" for v in value]
        opening, closing = "[", "]"
    return opening + "\n" + ",\n".join(items) + "\n" + "  " * level + closing
