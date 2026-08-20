"""Reed response parsing, against a recorded-shape payload."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sources.base import SearchQuery
from sources.reed import ReedSource

SAMPLE = {
    "jobId": 54321098,
    "employerName": "Northwind Data Ltd",
    "jobTitle": "Analytics Engineer",
    "locationName": "London",
    "minimumSalary": 60000,
    "maximumSalary": 70000,
    "currency": "GBP",
    "date": "19/08/2026",
    "expirationDate": "30/09/2026",
    "jobDescription": "Permanent, full-time role building dbt models. Hybrid working.",
    "jobUrl": "https://www.reed.co.uk/jobs/analytics-engineer/54321098",
}


def parser() -> ReedSource:
    return ReedSource.__new__(ReedSource)


def test_parses_core_fields():
    listing = parser()._parse(SAMPLE)

    assert listing is not None
    assert listing.title == "Analytics Engineer"
    assert listing.company == "Northwind Data Ltd"
    assert listing.date_posted == "2026-08-19"          # dd/mm/yyyy -> ISO
    assert listing.salary_min == 60000
    assert listing.salary_period == "annual"            # inferred from magnitude
    assert listing.salary_currency == "GBP"
    assert listing.salary_is_estimate is False
    assert listing.source == "Reed"


def test_infers_contract_fields_from_text():
    listing = parser()._parse(SAMPLE)
    assert listing.contract_type == "permanent"
    assert listing.contract_time == "full_time"

    contract = dict(SAMPLE, jobDescription="6 month fixed-term contract, day rate negotiable.")
    assert parser()._parse(contract).contract_type == "contract"

    part = dict(SAMPLE, jobDescription="Part-time, 3 days a week.")
    assert parser()._parse(part).contract_time == "part_time"


def test_day_rate_magnitude_infers_daily_period():
    day_rate = dict(SAMPLE, minimumSalary=500, maximumSalary=600)
    listing = parser()._parse(day_rate)
    assert listing.salary_period == "daily"


def test_malformed_date_does_not_crash():
    bad = dict(SAMPLE, date="2026-08-19")   # ISO, not Reed's dd/mm/yyyy
    assert parser()._parse(bad).date_posted == ""


def test_skips_listing_without_url():
    assert parser()._parse(dict(SAMPLE, jobUrl="")) is None


def test_converts_radius_km_to_miles():
    query = SearchQuery(keyword="Data Engineer", location="London", radius_km=40,
                        remote_only=False, limit=50)
    params = parser()._params(query, take=50, skip=0)
    assert params["distanceFromLocation"] == 25      # 40km -> 25 miles
    assert params["locationName"] == "London"


def test_remote_pass_drops_location_and_extends_keywords():
    query = SearchQuery(keyword="Data Engineer", location=None, radius_km=None,
                        remote_only=True, limit=50)
    params = parser()._params(query, take=50, skip=0)
    assert "locationName" not in params
    assert params["keywords"] == "Data Engineer remote"
