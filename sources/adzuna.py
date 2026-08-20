"""Adzuna adapter.

Docs: https://developer.adzuna.com/overview
Register for a free App ID + App Key, then set ADZUNA_APP_ID / ADZUNA_APP_KEY.
"""
from __future__ import annotations

import logging
import os
import time
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import config
from core import salary as salary_utils
from core.models import JobListing
from core.text import clean_text, truncate
from sources.base import JobSource, SearchQuery, SourceError, is_placeholder

logger = logging.getLogger(__name__)

# GB endpoint. The trailing element is the page number.
BASE_URL = "https://api.adzuna.com/v1/api/jobs/gb/search"

# Adzuna caps results_per_page at 50.
MAX_PER_PAGE = 50

# Adzuna stamps your App ID into every redirect URL as `utm_source`, which
# would then be published in the committed CSV. The link 403s if the parameter
# is missing entirely, but its value is not validated - so substitute a
# constant and the URL keeps working without exposing the credential.
UTM_SOURCE_PLACEHOLDER = "jobaggregator"


def sanitise_url(url: str) -> str:
    """Replace the App ID that Adzuna embeds in redirect URLs."""
    parts = urlparse(url)
    if not parts.query:
        return url

    params = [
        (key, UTM_SOURCE_PLACEHOLDER if key == "utm_source" else value)
        for key, value in parse_qsl(parts.query)
    ]
    return urlunparse(parts._replace(query=urlencode(params)))


class AdzunaSource(JobSource):
    name = "Adzuna"

    def __init__(self) -> None:
        self.app_id = os.getenv("ADZUNA_APP_ID", "").strip()
        self.app_key = os.getenv("ADZUNA_APP_KEY", "").strip()

    def is_configured(self) -> bool:
        return not is_placeholder(self.app_id) and not is_placeholder(self.app_key)

    def fetch(self, query: SearchQuery) -> list[JobListing]:
        if not self.is_configured():
            raise SourceError("Adzuna: ADZUNA_APP_ID / ADZUNA_APP_KEY not set")

        listings: list[JobListing] = []
        page = 1

        while len(listings) < query.limit:
            wanted = min(MAX_PER_PAGE, query.limit - len(listings))
            payload = self._get_json(f"{BASE_URL}/{page}", self._params(query, wanted))
            results = payload.get("results") or []

            if not results:
                break

            for item in results:
                listing = self._parse(item)
                if listing is not None:
                    listings.append(listing)

            # Short page means we have reached the end of the result set.
            if len(results) < wanted:
                break

            page += 1
            time.sleep(config.REQUEST_DELAY_SECONDS)

        logger.info(
            "[Adzuna] %-24s (%s) -> %d raw listings",
            query.keyword, "remote-uk" if query.remote_only else "london", len(listings),
        )
        return listings

    # -- internals ----------------------------------------------------------

    def _params(self, query: SearchQuery, per_page: int) -> dict:
        # Adzuna has no remote flag, so the remote pass adds the word to the
        # keyword query and drops the location; core.filters then confirms it.
        what = f"{query.keyword} remote" if query.remote_only else query.keyword

        params = {
            "app_id": self.app_id,
            "app_key": self.app_key,
            "results_per_page": per_page,
            "what": what,
            "max_days_old": query.max_days_old,
            "sort_by": "date",
            "content-type": "application/json",
        }

        if query.location:
            params["where"] = query.location
            if query.radius_km:
                params["distance"] = query.radius_km

        return params

    def _parse(self, item: dict) -> JobListing | None:
        title = clean_text(item.get("title"))
        url = (item.get("redirect_url") or "").strip()
        if not title or not url:
            return None
        url = sanitise_url(url)

        company = clean_text((item.get("company") or {}).get("display_name"))
        location = clean_text((item.get("location") or {}).get("display_name"))
        description = truncate(
            clean_text(item.get("description")), config.DESCRIPTION_MAX_CHARS
        )

        # Adzuna returns "2026-08-19T09:12:33Z"; we keep the date part.
        created = (item.get("created") or "")[:10]

        # Adzuna GB salaries are annual GBP. `salary_is_predicted` == "1" means
        # the figure is Adzuna's estimate rather than the advertiser's.
        predicted = str(item.get("salary_is_predicted", "0")) == "1"
        raw = "Adzuna estimate" if predicted else ""
        minimum, maximum, currency, period = salary_utils.normalise(
            item.get("salary_min"),
            item.get("salary_max"),
            currency="GBP" if (item.get("salary_min") or item.get("salary_max")) else "",
            period=salary_utils.ANNUAL if (item.get("salary_min") or item.get("salary_max")) else "",
            raw=raw,
        )

        return JobListing(
            title=title,
            company=company,
            location=location,
            url=url,
            source=self.name,
            description=description,
            date_posted=created,
            contract_type=clean_text(item.get("contract_type")),
            contract_time=clean_text(item.get("contract_time")),
            salary_min=minimum,
            salary_max=maximum,
            salary_currency=currency,
            salary_period=period,
            salary_is_estimate=predicted,
            salary_raw=raw,
        )
