"""Reed adapter.

Docs: https://www.reed.co.uk/developers/jobseeker
Register for a free API key, then set REED_API_KEY.

Reed authenticates with HTTP Basic, using the API key as the username and an
empty password.
"""
from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime

import config
from core import salary as salary_utils
from core.models import JobListing
from core.text import clean_text, truncate
from sources.base import JobSource, SearchQuery, SourceError, is_placeholder

logger = logging.getLogger(__name__)

BASE_URL = "https://www.reed.co.uk/api/1.0/search"

# Reed caps resultsToTake at 100.
MAX_PER_PAGE = 100

KM_PER_MILE = 1.60934

# The search endpoint omits contract type - that only appears on the per-job
# details endpoint, which would cost one extra call per listing. We infer it
# from the text instead, and leave it blank when there is no clear signal.
_CONTRACT_RE = re.compile(r"\bcontract\b|\bfixed[- ]term\b|\bftc\b|\binterim\b|\bday rate\b", re.I)
_PERMANENT_RE = re.compile(r"\bpermanent\b|\bperm\b", re.I)
_PART_TIME_RE = re.compile(r"\bpart[- ]time\b", re.I)
_FULL_TIME_RE = re.compile(r"\bfull[- ]time\b", re.I)


class ReedSource(JobSource):
    name = "Reed"

    def __init__(self) -> None:
        self.api_key = os.getenv("REED_API_KEY", "").strip()

    def is_configured(self) -> bool:
        return not is_placeholder(self.api_key)

    def fetch(self, query: SearchQuery) -> list[JobListing]:
        if not self.is_configured():
            raise SourceError("Reed: REED_API_KEY not set")

        listings: list[JobListing] = []
        skip = 0

        while len(listings) < query.limit:
            wanted = min(MAX_PER_PAGE, query.limit - len(listings))
            payload = self._get_json(
                BASE_URL, self._params(query, wanted, skip), auth=(self.api_key, "")
            )
            results = payload.get("results") or []

            if not results:
                break

            for item in results:
                listing = self._parse(item)
                if listing is not None:
                    listings.append(listing)

            if len(results) < wanted:
                break

            skip += len(results)
            time.sleep(config.REQUEST_DELAY_SECONDS)

        logger.info(
            "[Reed]   %-24s (%s) -> %d raw listings",
            query.keyword, "remote-uk" if query.remote_only else "london", len(listings),
        )
        return listings

    # -- internals ----------------------------------------------------------

    def _params(self, query: SearchQuery, take: int, skip: int) -> dict:
        keywords = f"{query.keyword} remote" if query.remote_only else query.keyword

        params = {
            "keywords": keywords,
            "resultsToTake": take,
            "resultsToSkip": skip,
        }

        if query.location:
            params["locationName"] = query.location
            if query.radius_km:
                # Reed measures distance in miles, unlike Adzuna's kilometres.
                params["distanceFromLocation"] = round(query.radius_km / KM_PER_MILE)

        return params

    @staticmethod
    def _parse_date(value: str) -> str:
        """Reed returns dd/mm/yyyy; we store ISO."""
        text = (value or "").strip()
        if not text:
            return ""
        try:
            return datetime.strptime(text, "%d/%m/%Y").date().isoformat()
        except ValueError:
            logger.debug("[Reed] unrecognised date format: %r", text)
            return ""

    def _parse(self, item: dict) -> JobListing | None:
        title = clean_text(item.get("jobTitle"))
        url = (item.get("jobUrl") or "").strip()
        if not title or not url:
            return None

        description_full = clean_text(item.get("jobDescription"))
        haystack = f"{title} {description_full}"

        contract_type = ""
        if _CONTRACT_RE.search(haystack):
            contract_type = "contract"
        elif _PERMANENT_RE.search(haystack):
            contract_type = "permanent"

        contract_time = ""
        if _PART_TIME_RE.search(haystack):
            contract_time = "part_time"
        elif _FULL_TIME_RE.search(haystack):
            contract_time = "full_time"

        # Reed gives bare numbers with no period, so core.salary infers it from
        # the magnitude (a 500 is a day rate, a 65000 is annual).
        minimum, maximum, currency, period = salary_utils.normalise(
            item.get("minimumSalary"),
            item.get("maximumSalary"),
            currency=clean_text(item.get("currency")),
            raw=haystack,
        )

        return JobListing(
            title=title,
            company=clean_text(item.get("employerName")),
            location=clean_text(item.get("locationName")),
            url=url,
            source=self.name,
            description=truncate(description_full, config.DESCRIPTION_MAX_CHARS),
            date_posted=self._parse_date(item.get("date")),
            contract_type=contract_type,
            contract_time=contract_time,
            salary_min=minimum,
            salary_max=maximum,
            salary_currency=currency,
            salary_period=period,
            salary_is_estimate=False,   # Reed only publishes advertiser figures
        )
