"""Data quality gate tests."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import quality
from core.models import JobListing


def listing(**overrides) -> JobListing:
    defaults = dict(
        title="Data Engineer", company="Acme", location="London",
        url="https://example.com/1", source="Adzuna",
        job_id="abc123", first_seen_date="2026-08-20", last_seen_date="2026-08-20",
    )
    defaults.update(overrides)
    return JobListing(**defaults)


def test_clean_dataset_passes_every_check():
    results = quality.run_all([listing()], previous_count=1, today="2026-08-20")
    assert all(r.passed for r in results), [r for r in results if not r.passed]

    safe, status = quality.report(results)
    assert safe is True
    assert status == "passed"


def test_duplicate_ids_block_the_write():
    results = quality.run_all(
        [listing(), listing()], previous_count=2, today="2026-08-20"
    )
    safe, status = quality.report(results)
    assert safe is False
    assert status == "failed"


def test_missing_required_field_blocks_the_write():
    results = quality.run_all([listing(url="")], previous_count=1, today="2026-08-20")
    assert quality.report(results)[0] is False


def test_collapsed_dataset_blocks_the_write():
    """The dataset is append-only - halving means something went wrong upstream."""
    rows = [listing(job_id=f"id{i}") for i in range(10)]
    result = quality.check_row_count_stable(len(rows), previous=100)
    assert result.blocking


def test_small_shrink_warns_but_does_not_block():
    result = quality.check_row_count_stable(95, previous=100)
    assert not result.passed
    assert result.severity == quality.WARN
    assert not result.blocking


def test_first_run_is_not_treated_as_a_collapse():
    assert quality.check_row_count_stable(50, previous=0).passed


def test_salary_outside_bounds_warns_only():
    """A day rate mislabelled as annual should be flagged, not fatal."""
    odd = listing(salary_min=650, salary_period="annual")
    result = quality.check_salary_ranges([odd])
    assert not result.passed
    assert result.severity == quality.WARN


def test_future_posting_date_warns():
    result = quality.check_dates_sane([listing(date_posted="2027-01-01")], today="2026-08-20")
    assert not result.passed
    assert result.severity == quality.WARN


def test_inverted_seen_dates_warn():
    bad = listing(first_seen_date="2026-08-20", last_seen_date="2026-08-01")
    assert not quality.check_dates_sane([bad], today="2026-08-20").passed


def test_malformed_url_warns():
    assert not quality.check_urls_usable([listing(url="not-a-url")]).passed


def test_warnings_alone_still_allow_the_write():
    results = quality.run_all(
        [listing(salary_min=650, salary_period="annual")],
        previous_count=1, today="2026-08-20",
    )
    safe, status = quality.report(results)
    assert safe is True
    assert status == "passed_with_warnings"
