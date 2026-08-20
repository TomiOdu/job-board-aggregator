"""Unit tests for the pure logic: salary parsing, title filtering, dedupe/merge.

Run with:  python -m pytest -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import salary
from core.dedupe import coarse_location, make_job_id, merge_with_master, normalise_url
from core.filters import apply_filters, title_matches
from core.models import JobListing


def listing(**overrides) -> JobListing:
    defaults = dict(
        title="Data Engineer",
        company="Acme Ltd",
        location="London",
        url="https://example.com/jobs/1",
        source="Adzuna",
        description="Build pipelines.",
    )
    defaults.update(overrides)
    return JobListing(**defaults)


# -- salary ----------------------------------------------------------------

def test_parses_annual_range():
    low, high, currency, period = salary.parse_salary_text("60,000 - 70,000 per annum")
    assert (low, high) == (60000.0, 70000.0)
    assert period == salary.ANNUAL


def test_parses_day_rate():
    low, _, _, period = salary.parse_salary_text("500 per day")
    assert low == 500.0
    assert period == salary.DAILY


def test_infers_period_from_magnitude():
    assert salary.infer_period(45) == salary.HOURLY
    assert salary.infer_period(550) == salary.DAILY
    assert salary.infer_period(65000) == salary.ANNUAL


def test_normalise_swaps_reversed_bounds_and_drops_zero():
    minimum, maximum, _, _ = salary.normalise(70000, 60000)
    assert (minimum, maximum) == (60000, 70000)
    minimum, maximum, _, _ = salary.normalise(0, 0)
    assert (minimum, maximum) == (None, None)


# -- title filter ----------------------------------------------------------

def test_keeps_target_titles():
    for good in [
        "Data Engineer",
        "Senior Analytics Engineer",
        "Lead Data Engineer (Remote)",
        "Analytics Engineering Manager",
        "dbt Analytics Engineer",
    ]:
        assert title_matches(good), good


def test_rejects_near_misses():
    for bad in ["Data Analyst", "Data Scientist", "BI Developer", "Software Engineer"]:
        assert not title_matches(bad), bad


def test_rejects_internships():
    for bad in [
        "Data Engineering Internship (Summer 2027)",
        "Data Engineer Intern",
        "Analytics Engineering Interns",
    ]:
        assert not title_matches(bad), bad


def test_internship_filter_does_not_catch_similar_words():
    """'International' and 'Internal' must survive the exclusion."""
    for good in [
        "Data Engineer, International Markets",
        "Data Engineer - Internal Tools",
    ]:
        assert title_matches(good), good


def test_remote_only_pass_drops_onsite_roles():
    kept, rejected = apply_filters(
        [
            listing(title="Data Engineer", description="Fully remote across the UK."),
            listing(title="Data Engineer", description="Onsite in Canary Wharf."),
        ],
        remote_only=True,
    )
    assert len(kept) == 1
    assert len(rejected) == 1
    assert kept[0].is_remote


# -- dedupe / merge --------------------------------------------------------

def test_url_normalisation_strips_tracking_params():
    assert normalise_url("https://www.example.com/job/1?utm=x&v=2") == "https://example.com/job/1"


def test_same_role_from_two_sources_collapses():
    a = listing(source="Adzuna", url="https://adzuna.com/land/ad/1")
    b = listing(source="Reed", url="https://reed.co.uk/jobs/2")
    assert make_job_id(a) == make_job_id(b)


def test_coarse_location_collapses_london_variants():
    for variant in ["London, UK", "South East London, London", "Sutton, London",
                    "Farringdon, Central London", "London"]:
        assert coarse_location(variant) == "london", variant


def test_coarse_location_strips_country_suffix():
    assert coarse_location("Manchester, UK") == "manchester"
    assert coarse_location("Leeds, England") == "leeds"


def test_coarse_location_keeps_different_cities_apart():
    assert coarse_location("Manchester, UK") != coarse_location("Bristol, UK")


def test_syndicated_advert_at_two_granularities_collapses():
    """The real Adzuna case: one advert, two ad IDs, two location strings."""
    a = listing(company="Aquent", location="South East London, London",
                url="https://adzuna.co.uk/jobs/land/ad/5849394735")
    b = listing(company="Aquent", location="London, UK",
                url="https://adzuna.co.uk/jobs/details/5849295228")
    assert make_job_id(a) == make_job_id(b)


def test_same_role_in_different_cities_stays_separate():
    a = listing(company="Acme Ltd", location="London, UK")
    b = listing(company="Acme Ltd", location="Manchester, UK")
    assert make_job_id(a) != make_job_id(b)


def test_anonymous_company_falls_back_to_url():
    a = listing(company="Confidential", url="https://example.com/jobs/1")
    b = listing(company="Confidential", url="https://example.com/jobs/2")
    assert make_job_id(a) != make_job_id(b)


def test_merge_flags_new_and_preserves_first_seen():
    existing_listing = listing()
    existing_listing.job_id = make_job_id(existing_listing)
    existing_listing.first_seen_date = "2026-08-01"
    existing_listing.last_seen_date = "2026-08-01"

    full, new_today = merge_with_master(
        [existing_listing],
        [listing(), listing(title="Analytics Engineer", url="https://example.com/jobs/9")],
        today="2026-08-20",
    )

    assert len(full) == 2
    assert len(new_today) == 1
    assert new_today[0].title == "Analytics Engineer"
    assert new_today[0].first_seen_date == "2026-08-20"

    seen_again = next(item for item in full if item.title == "Data Engineer")
    assert seen_again.first_seen_date == "2026-08-01"   # unchanged
    assert seen_again.last_seen_date == "2026-08-20"    # bumped


def test_real_salary_replaces_an_estimate_on_a_known_listing():
    known = listing(salary_min=50000, salary_max=50000, salary_is_estimate=True)
    known.job_id = make_job_id(known)
    known.first_seen_date = known.last_seen_date = "2026-08-01"

    incoming = listing(salary_min=70000, salary_max=85000, salary_is_estimate=False)
    full, _ = merge_with_master([known], [incoming], today="2026-08-20")

    updated = full[0]
    assert updated.salary_min == 70000
    assert updated.salary_is_estimate is False


def test_estimate_does_not_overwrite_a_real_salary():
    known = listing(salary_min=70000, salary_max=85000, salary_is_estimate=False)
    known.job_id = make_job_id(known)
    known.first_seen_date = known.last_seen_date = "2026-08-01"

    incoming = listing(salary_min=50000, salary_max=50000, salary_is_estimate=True)
    full, _ = merge_with_master([known], [incoming], today="2026-08-20")

    assert full[0].salary_min == 70000
    assert full[0].salary_is_estimate is False


def test_advertised_day_rate_beats_an_annualised_one():
    """Real case: Adzuna reports 169000/yr for a role Reed reports as 650/day."""
    known = listing(source="Adzuna", salary_min=169000, salary_max=169000,
                    salary_period="annual")
    known.job_id = make_job_id(known)
    known.first_seen_date = known.last_seen_date = "2026-08-19"

    incoming = listing(source="Reed", salary_min=650, salary_max=650,
                       salary_period="daily")
    full, _ = merge_with_master([known], [incoming], today="2026-08-20")

    assert full[0].salary_min == 650
    assert full[0].salary_period == "daily"


def test_annual_salary_is_not_replaced_by_another_annual():
    known = listing(salary_min=70000, salary_max=80000, salary_period="annual")
    known.job_id = make_job_id(known)
    known.first_seen_date = known.last_seen_date = "2026-08-19"

    incoming = listing(salary_min=65000, salary_max=75000, salary_period="annual")
    full, _ = merge_with_master([known], [incoming], today="2026-08-20")

    assert full[0].salary_min == 70000     # first one wins, no churn


def test_duplicates_within_one_batch_collapse():
    _, new_today = merge_with_master([], [listing(), listing(), listing()], today="2026-08-20")
    assert len(new_today) == 1


def test_second_run_same_day_still_reports_the_whole_day():
    """A manual run after the scheduled one must not shrink 'new today' to its
    own delta - the file would lose everything found that morning."""
    morning = listing(title="Data Engineer", url="https://example.com/1")
    full_am, new_am = merge_with_master([], [morning], today="2026-08-20")
    assert len(new_am) == 1

    afternoon = listing(title="Analytics Engineer", url="https://example.com/2")
    _, new_pm = merge_with_master(full_am, [morning, afternoon], today="2026-08-20")

    assert len(new_pm) == 2                                   # not just the new one
    assert {l.title for l in new_pm} == {"Data Engineer", "Analytics Engineer"}


def test_day_rate_wins_within_a_single_run_too():
    """The within-run path collapses duplicates before the master merge, so it
    needs the same salary preference - otherwise source order decides."""
    adzuna = listing(source="Adzuna", salary_min=169000, salary_max=169000,
                     salary_period="annual")
    reed = listing(source="Reed", salary_min=650, salary_max=650,
                   salary_period="daily")

    _, new_today = merge_with_master([], [adzuna, reed], today="2026-08-20")

    assert len(new_today) == 1
    assert new_today[0].salary_min == 650
    assert new_today[0].salary_period == "daily"


def test_real_salary_wins_within_a_single_run():
    estimated = listing(source="Adzuna", salary_min=50000, salary_max=50000,
                        salary_period="annual", salary_is_estimate=True)
    advertised = listing(source="Reed", salary_min=72000, salary_max=80000,
                         salary_period="annual", salary_is_estimate=False)

    _, new_today = merge_with_master([], [estimated, advertised], today="2026-08-20")

    assert new_today[0].salary_min == 72000
    assert new_today[0].salary_is_estimate is False
