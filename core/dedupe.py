"""Deduplication and merging into the running master dataset."""
from __future__ import annotations

import hashlib
import logging
import re
from urllib.parse import urlparse, urlunparse

from core.models import JobListing

logger = logging.getLogger(__name__)

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^a-z0-9 ]")

# Company names that identify nothing - several agencies post under these, so
# a title+company+location hash would wrongly merge unrelated roles.
_ANONYMOUS_COMPANIES = {"", "confidential", "private advertiser", "anonymous", "undisclosed"}

# Stripped before picking the broad area, so "London, UK" and "London" match.
_COUNTRY_TOKENS = {
    "uk", "united kingdom", "great britain", "gb",
    "england", "scotland", "wales", "northern ireland",
}


def _norm(value: str) -> str:
    """Lowercase, strip punctuation and collapse whitespace."""
    lowered = (value or "").lower().strip()
    return _WS.sub(" ", _PUNCT.sub(" ", lowered)).strip()


def normalise_url(url: str) -> str:
    """Drop query strings, fragments and trailing slashes.

    Adzuna redirect URLs carry per-request tracking parameters, so the raw URL
    is not stable between runs - the path is.
    """
    if not url:
        return ""
    try:
        parts = urlparse(url.strip())
    except ValueError:
        return url.strip().lower()
    netloc = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/")
    return urlunparse((parts.scheme.lower(), netloc, path, "", "", ""))


def coarse_location(location: str) -> str:
    """Reduce a location to its broad area, for stable hashing.

    Boards syndicate one advert under several location granularities - the
    same job turns up as "South East London, London" and "London, UK". Sources
    order these specific-to-general, so the last non-country component is the
    broad area. London is special-cased because it appears at both ends
    ("Sutton, London" vs "London, UK").
    """
    raw = (location or "").lower()
    if "london" in raw:
        return "london"

    parts = [_norm(part) for part in raw.split(",")]
    parts = [part for part in parts if part and part not in _COUNTRY_TOKENS]
    return parts[-1] if parts else ""


def make_job_id(listing: JobListing) -> str:
    """Stable id for a listing.

    Normally a hash of (title + company + coarse location) so the same role
    found via two sources, or syndicated twice at different location
    granularities, collapses into one row. When the company is anonymous that
    hash is not distinctive enough, so we fall back to the normalised URL.
    """
    company = _norm(listing.company)
    if company in _ANONYMOUS_COMPANIES:
        basis = normalise_url(listing.url) or f"{_norm(listing.title)}|{coarse_location(listing.location)}"
    else:
        basis = f"{_norm(listing.title)}|{company}|{coarse_location(listing.location)}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def dedupe_batch(listings: list[JobListing]) -> list[JobListing]:
    """Collapse duplicates within a single run, keeping the first occurrence."""
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    unique: list[JobListing] = []

    for listing in listings:
        listing.job_id = listing.job_id or make_job_id(listing)
        url_key = normalise_url(listing.url)
        if listing.job_id in seen_ids or (url_key and url_key in seen_urls):
            continue
        seen_ids.add(listing.job_id)
        if url_key:
            seen_urls.add(url_key)
        unique.append(listing)

    return unique


def merge_with_master(
    existing: list[JobListing], fetched: list[JobListing], today: str
) -> tuple[list[JobListing], list[JobListing]]:
    """Fold this run's listings into the running dataset.

    Returns (full_dataset, new_today). Listings already known keep their
    original first_seen_date and get last_seen_date bumped; genuinely new ones
    get both set to today.
    """
    by_id: dict[str, JobListing] = {}
    url_index: dict[str, str] = {}

    for listing in existing:
        listing.job_id = listing.job_id or make_job_id(listing)
        by_id[listing.job_id] = listing
        url_key = normalise_url(listing.url)
        if url_key:
            url_index[url_key] = listing.job_id

    new_today: list[JobListing] = []

    for listing in dedupe_batch(fetched):
        url_key = normalise_url(listing.url)
        known_id = listing.job_id if listing.job_id in by_id else url_index.get(url_key, "")

        if known_id:
            known = by_id[known_id]
            known.last_seen_date = today
            # Fill in a salary we did not have, and always prefer an
            # advertiser-published figure over a board's estimate.
            missing = known.salary_min is None
            upgrade = known.salary_is_estimate and not listing.salary_is_estimate
            if listing.salary_min is not None and (missing or upgrade):
                known.salary_min = listing.salary_min
                known.salary_max = listing.salary_max
                known.salary_currency = listing.salary_currency
                known.salary_period = listing.salary_period
                known.salary_is_estimate = listing.salary_is_estimate
                known.salary_raw = listing.salary_raw
            continue

        listing.first_seen_date = today
        listing.last_seen_date = today
        by_id[listing.job_id] = listing
        if url_key:
            url_index[url_key] = listing.job_id
        new_today.append(listing)

    full = sorted(
        by_id.values(),
        key=lambda item: (item.first_seen_date, item.date_posted, item.title),
        reverse=True,
    )
    return full, new_today
