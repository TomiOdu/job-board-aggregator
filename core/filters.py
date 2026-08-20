"""Strict title matching and remote detection."""
from __future__ import annotations

import re

import config
from core.models import JobListing

_TITLE_INCLUDE = [re.compile(p, re.I) for p in config.TITLE_PATTERNS]
_TITLE_EXCLUDE = [re.compile(p, re.I) for p in config.TITLE_EXCLUDE_PATTERNS]
_REMOTE = [re.compile(p, re.I) for p in config.REMOTE_PATTERNS]


def title_matches(title: str) -> bool:
    """True if the title is a Data/Analytics Engineering role we care about."""
    if not title:
        return False
    if any(pattern.search(title) for pattern in _TITLE_EXCLUDE):
        return False
    return any(pattern.search(title) for pattern in _TITLE_INCLUDE)


def looks_remote(listing: JobListing) -> bool:
    """Detect remote roles from the title, location and description text."""
    haystack = " ".join([listing.title, listing.location, listing.description])
    return any(pattern.search(haystack) for pattern in _REMOTE)


def apply_filters(
    listings: list[JobListing], remote_only: bool = False
) -> tuple[list[JobListing], list[str]]:
    """Keep only strict title matches; returns (kept, rejected_titles)."""
    kept: list[JobListing] = []
    rejected: list[str] = []

    for listing in listings:
        if not title_matches(listing.title):
            rejected.append(listing.title)
            continue
        listing.is_remote = looks_remote(listing)
        if remote_only and not listing.is_remote:
            rejected.append(listing.title)
            continue
        kept.append(listing)

    return kept, rejected
