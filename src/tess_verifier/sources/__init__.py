"""Outside data sources (supporting actors in docs/use-cases.md)."""

from tess_verifier.sources.base import (
    CandidateNotFoundError,
    DataSources,
    SourceError,
    SourceUnavailableError,
)
from tess_verifier.sources.fake import fake_sources


def build_sources(kind: str = "fake") -> DataSources:
    """Return the data sources to use. Only placeholder data exist in v1."""
    if kind == "fake":
        return fake_sources()
    raise ValueError(f"Unknown data source '{kind}'. Only 'fake' is available in this version.")


__all__ = [
    "CandidateNotFoundError",
    "DataSources",
    "SourceError",
    "SourceUnavailableError",
    "build_sources",
    "fake_sources",
]
