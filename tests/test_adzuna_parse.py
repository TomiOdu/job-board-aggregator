"""Adzuna response parsing, against a recorded-shape payload."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sources.adzuna import AdzunaSource, sanitise_url

SAMPLE = {
    "id": "4212345678",
    "title": "Senior <strong>Data Engineer</strong>",
    "company": {"display_name": "Acme Analytics Ltd"},
    "location": {"display_name": "City of London, London", "area": ["UK", "London"]},
    "salary_min": 70000,
    "salary_max": 85000,
    "salary_is_predicted": "0",
    "contract_type": "permanent",
    "contract_time": "full_time",
    "created": "2026-08-19T09:12:33Z",
    # Real shape: Adzuna appends utm_source=<your App ID>.
    "redirect_url": "https://www.adzuna.co.uk/jobs/details/4212345678?utm_medium=api&utm_source=a1b2c3d4",
    "description": "Build &amp; own batch pipelines in <b>dbt</b> and Airflow. Hybrid, 2 days in office.",
}


def test_parses_core_fields():
    listing = AdzunaSource.__new__(AdzunaSource)._parse(SAMPLE)

    assert listing is not None
    assert listing.title == "Senior Data Engineer"          # HTML stripped
    assert listing.company == "Acme Analytics Ltd"
    assert listing.date_posted == "2026-08-19"              # timestamp -> date
    assert listing.salary_min == 70000
    assert listing.salary_period == "annual"
    assert listing.salary_currency == "GBP"
    assert listing.contract_type == "permanent"
    assert "&" in listing.description                       # entity unescaped
    assert listing.source == "Adzuna"


def test_flags_predicted_salary():
    payload = dict(SAMPLE, salary_is_predicted="1")
    listing = AdzunaSource.__new__(AdzunaSource)._parse(payload)
    assert listing.salary_is_estimate is True
    assert listing.salary_raw == "Adzuna estimate"


def test_advertised_salary_not_flagged_as_estimate():
    listing = AdzunaSource.__new__(AdzunaSource)._parse(SAMPLE)
    assert listing.salary_is_estimate is False
    assert listing.salary_raw == ""


def test_app_id_is_stripped_from_the_redirect_url():
    """Adzuna puts the App ID in utm_source; it must not reach committed output."""
    listing = AdzunaSource.__new__(AdzunaSource)._parse(SAMPLE)
    assert "a1b2c3d4" not in listing.url
    assert "utm_source=jobaggregator" in listing.url


def test_sanitise_url_keeps_the_parameter_present():
    """The link 403s without utm_source, so replace the value, never drop it."""
    cleaned = sanitise_url("https://www.adzuna.co.uk/jobs/details/42?utm_medium=api&utm_source=a1b2c3d4")
    assert "utm_source=jobaggregator" in cleaned
    assert "utm_medium=api" in cleaned
    assert "a1b2c3d4" not in cleaned


def test_sanitise_url_leaves_a_query_less_url_alone():
    assert sanitise_url("https://example.com/jobs/1") == "https://example.com/jobs/1"


def test_skips_listing_without_url():
    payload = dict(SAMPLE, redirect_url="")
    assert AdzunaSource.__new__(AdzunaSource)._parse(payload) is None
