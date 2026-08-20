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


def improve_salary(known: JobListing, incoming: JobListing) -> None:
    """Adopt `incoming`'s salary if it describes the job better than `known`'s.

    Applied whenever two records collapse into one, whether that happens
    within a single run or against the stored dataset.
    """
    if incoming.salary_min is None:
        return

    missing = known.salary_min is None
    # An advertiser's figure always beats a board's own prediction.
    upgrade = known.salary_is_estimate and not incoming.salary_is_estimate
    # Some boards annualise contract day rates (650/day -> 169,000/yr). When
    # two sources describe one job both ways, the day rate is what the advert
    # actually said, so it wins over the derived figure.
    as_advertised = (
        known.salary_period == "annual"
        and incoming.salary_period in ("daily", "hourly")
    )

    if missing or upgrade or as_advertised:
        known.salary_min = incoming.salary_min
        known.salary_max = incoming.salary_max
        known.salary_currency = incoming.salary_currency
        known.salary_period = incoming.salary_period
        known.salary_is_estimate = incoming.salary_is_estimate
        known.salary_raw = incoming.salary_raw


def dedupe_batch(listings: list[JobListing]) -> list[JobListing]:
    """Collapse duplicates within a single run.

    Keeps the first occurrence as the surviving row, but still lets a later
    duplicate contribute a better salary - otherwise whichever source happens
    to run first silently wins.
    """
    kept_by_id: dict[str, JobListing] = {}
    url_index: dict[str, str] = {}
    unique: list[JobListing] = []

    for listing in listings:
        listing.job_id = listing.job_id or make_job_id(listing)
        url_key = normalise_url(listing.url)

        known_id = listing.job_id if listing.job_id in kept_by_id else url_index.get(url_key, "")
        if known_id:
            improve_salary(kept_by_id[known_id], listing)
            continue

        kept_by_id[listing.job_id] = listing
        if url_key:
            url_index[url_key] = listing.job_id
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

    for listing in dedupe_batch(fetched):
        url_key = normalise_url(listing.url)
        known_id = listing.job_id if listing.job_id in by_id else url_index.get(url_key, "")

        if known_id:
            known = by_id[known_id]
            known.last_seen_date = today
            improve_salary(known, listing)
            continue

        listing.first_seen_date = today
        listing.last_seen_date = today
        by_id[listing.job_id] = listing
        if url_key:
            url_index[url_key] = listing.job_id

    full = sorted(
        by_id.values(),
        key=lambda item: (item.first_seen_date, item.date_posted, item.title),
        reverse=True,
    )
    # Derived from first_seen_date rather than "added by this run", so running
    # twice in a day still reports everything found today instead of just the
    # second run's delta.
    new_today = [item for item in full if item.first_seen_date == today]
    return full, new_today
