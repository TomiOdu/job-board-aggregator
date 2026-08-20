"""Data quality gate, run after the merge and before anything is written.

A scheduled pipeline nobody watches needs to fail loudly rather than quietly
write bad data. Fatal failures abort the write, so the previous good dataset
survives untouched; warnings are logged and the run continues.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date

import config
from core.models import JobListing

logger = logging.getLogger(__name__)

FATAL = "fatal"
WARN = "warn"

_URL_RE = re.compile(r"^https?://", re.I)

# Fields that must be populated on every row for the output to be usable.
REQUIRED_FIELDS = ("job_id", "title", "url", "source", "first_seen_date", "last_seen_date")


@dataclass
class CheckResult:
    name: str
    passed: bool
    severity: str
    detail: str

    @property
    def blocking(self) -> bool:
        return not self.passed and self.severity == FATAL


def _ok(name: str, detail: str = "") -> CheckResult:
    return CheckResult(name, True, FATAL, detail)


def check_no_duplicate_ids(listings: list[JobListing]) -> CheckResult:
    """Duplicate job_ids mean dedupe is broken and rows will be double-counted."""
    seen: set[str] = set()
    dupes: set[str] = set()
    for listing in listings:
        if listing.job_id in seen:
            dupes.add(listing.job_id)
        seen.add(listing.job_id)

    if dupes:
        return CheckResult(
            "no_duplicate_ids", False, FATAL,
            f"{len(dupes)} duplicated job_id(s), e.g. {sorted(dupes)[:3]}",
        )
    return _ok("no_duplicate_ids", f"{len(listings)} unique ids")


def check_required_fields(listings: list[JobListing]) -> CheckResult:
    """Every row needs the fields that make it identifiable and clickable."""
    missing: dict[str, int] = {}
    for listing in listings:
        for field in REQUIRED_FIELDS:
            if not str(getattr(listing, field, "") or "").strip():
                missing[field] = missing.get(field, 0) + 1

    if missing:
        return CheckResult(
            "required_fields", False, FATAL,
            "empty values: " + ", ".join(f"{k}={v}" for k, v in sorted(missing.items())),
        )
    return _ok("required_fields", f"all {len(REQUIRED_FIELDS)} present on every row")


def check_row_count_stable(current: int, previous: int) -> CheckResult:
    """The dataset is append-only, so it should never shrink.

    A sudden collapse means a source returned garbage or the master file was
    partially read - either way, do not overwrite the good copy with it.
    """
    if previous == 0:
        return _ok("row_count_stable", f"first run, {current} rows")

    if current < previous * config.QUALITY_MIN_ROW_RETENTION:
        return CheckResult(
            "row_count_stable", False, FATAL,
            f"dataset collapsed from {previous} to {current} rows "
            f"(below {config.QUALITY_MIN_ROW_RETENTION:.0%} retention)",
        )
    if current < previous:
        return CheckResult(
            "row_count_stable", False, WARN,
            f"dataset shrank from {previous} to {current} rows",
        )
    return _ok("row_count_stable", f"{previous} -> {current} rows")


def check_salary_ranges(listings: list[JobListing]) -> CheckResult:
    """Catch figures that landed in the wrong period bucket."""
    odd: list[str] = []
    for listing in listings:
        bounds = config.QUALITY_SALARY_BOUNDS.get(listing.salary_period)
        if not bounds or listing.salary_min is None:
            continue
        low, high = bounds
        if not (low <= listing.salary_min <= high):
            odd.append(f"{listing.title[:35]} = {listing.salary_min:,.0f} {listing.salary_period}")

    if odd:
        return CheckResult(
            "salary_ranges", False, WARN,
            f"{len(odd)} outside expected bounds, e.g. {odd[:2]}",
        )
    return _ok("salary_ranges", "all within expected bounds")


def check_dates_sane(listings: list[JobListing], today: str) -> CheckResult:
    """Postings dated in the future, or seen before they were first seen."""
    problems: list[str] = []
    for listing in listings:
        if listing.date_posted and listing.date_posted > today:
            problems.append(f"{listing.title[:30]} posted {listing.date_posted}")
        if listing.first_seen_date and listing.last_seen_date:
            if listing.first_seen_date > listing.last_seen_date:
                problems.append(f"{listing.title[:30]} first_seen > last_seen")

    if problems:
        return CheckResult("dates_sane", False, WARN, f"{len(problems)} odd, e.g. {problems[:2]}")
    return _ok("dates_sane", "no future or inverted dates")


def check_urls_usable(listings: list[JobListing]) -> CheckResult:
    """The URL column is the point of the whole spreadsheet."""
    bad = [l.url for l in listings if not _URL_RE.match(l.url or "")]
    if bad:
        return CheckResult("urls_usable", False, WARN, f"{len(bad)} malformed, e.g. {bad[:2]}")
    return _ok("urls_usable", "all rows have an http(s) URL")


def run_all(listings: list[JobListing], previous_count: int, today: str | None = None) -> list[CheckResult]:
    """Run every check and return the results in report order."""
    today = today or date.today().isoformat()
    return [
        check_no_duplicate_ids(listings),
        check_required_fields(listings),
        check_row_count_stable(len(listings), previous_count),
        check_salary_ranges(listings),
        check_dates_sane(listings, today),
        check_urls_usable(listings),
    ]


def report(results: list[CheckResult]) -> tuple[bool, str]:
    """Log every check and return (safe_to_write, one_word_status)."""
    blocking = [r for r in results if r.blocking]
    warnings = [r for r in results if not r.passed and r.severity == WARN]

    for result in results:
        if result.passed:
            logger.info("  PASS  %-20s %s", result.name, result.detail)
        elif result.severity == WARN:
            logger.warning("  WARN  %-20s %s", result.name, result.detail)
        else:
            logger.error("  FAIL  %-20s %s", result.name, result.detail)

    if blocking:
        logger.error(
            "Quality gate FAILED (%d blocking) - refusing to overwrite the dataset",
            len(blocking),
        )
        return False, "failed"

    if warnings:
        return True, "passed_with_warnings"
    return True, "passed"
