"""Source registry.

To add a job board: write an adapter implementing JobSource, import it here
and add it to ALL_SOURCES. main.py picks it up automatically.
"""
from __future__ import annotations

from sources.adzuna import AdzunaSource
from sources.base import AuthError, JobSource, SearchQuery, SourceError
from sources.reed import ReedSource

ALL_SOURCES: list[type[JobSource]] = [
    AdzunaSource,
    ReedSource,
]


def build_sources(only: list[str] | None = None) -> list[JobSource]:
    """Instantiate the registered sources, optionally filtered by name."""
    wanted = {name.lower() for name in only} if only else None
    sources = [cls() for cls in ALL_SOURCES]
    if wanted is not None:
        sources = [source for source in sources if source.name.lower() in wanted]
    return sources


__all__ = [
    "ALL_SOURCES",
    "AuthError",
    "JobSource",
    "SearchQuery",
    "SourceError",
    "build_sources",
]
