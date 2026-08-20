"""The JobSource interface.

Adding a new job board means writing one class here that implements `fetch`
and `is_configured`, then registering it in sources/__init__.py. Nothing in
main.py needs to change.
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import requests

import config
from core.models import JobListing

logger = logging.getLogger(__name__)


class SourceError(RuntimeError):
    """Raised when a source cannot complete a fetch. Caught per-source in main."""


class AuthError(SourceError):
    """Credentials were rejected. Fatal for the source - retrying won't help."""


# Values copied straight out of .env.example, which are not real credentials.
PLACEHOLDER_PREFIXES = ("your_", "your-", "<", "changeme")


def is_placeholder(value: str) -> bool:
    """True if a credential is missing or still the .env.example placeholder."""
    cleaned = (value or "").strip().lower()
    return not cleaned or cleaned.startswith(PLACEHOLDER_PREFIXES)


@dataclass(frozen=True)
class SearchQuery:
    """A single query to run against a source."""

    keyword: str
    location: str | None      # None = nationwide
    radius_km: int | None
    remote_only: bool
    limit: int
    max_days_old: int = config.MAX_DAYS_OLD


class JobSource(ABC):
    """Base class for every job board adapter."""

    #: Short name used in the `source` column and in log lines.
    name: str = "base"

    @abstractmethod
    def is_configured(self) -> bool:
        """True if the credentials this source needs are present."""

    @abstractmethod
    def fetch(self, query: SearchQuery) -> list[JobListing]:
        """Run one query and return normalised listings.

        Implementations should raise SourceError on unrecoverable failures;
        main.py logs those and carries on with the other sources.
        """

    # -- shared HTTP helper -------------------------------------------------

    def _get_json(self, url: str, params: dict, auth: tuple[str, str] | None = None) -> dict:
        """GET with retries and backoff. Raises SourceError when it gives up.

        `auth` is an optional (username, password) pair for HTTP Basic, which
        is how Reed authenticates.
        """
        last_error: Exception | None = None

        for attempt in range(1, config.MAX_RETRIES + 1):
            try:
                response = requests.get(
                    url,
                    params=params,
                    auth=auth,
                    timeout=config.REQUEST_TIMEOUT_SECONDS,
                    headers={"User-Agent": "job-board-aggregator/1.0"},
                )
            except requests.RequestException as exc:
                last_error = exc
                logger.warning(
                    "[%s] request failed (attempt %d/%d): %s",
                    self.name, attempt, config.MAX_RETRIES, exc,
                )
            else:
                if response.status_code == 200:
                    try:
                        return response.json()
                    except ValueError as exc:
                        raise SourceError(f"{self.name}: response was not JSON") from exc

                if response.status_code in (401, 403):
                    raise AuthError(
                        f"{self.name}: authentication failed (HTTP {response.status_code}) "
                        "- check your API credentials"
                    )

                if response.status_code == 429 or response.status_code >= 500:
                    last_error = SourceError(f"HTTP {response.status_code}")
                    logger.warning(
                        "[%s] HTTP %d (attempt %d/%d), backing off",
                        self.name, response.status_code, attempt, config.MAX_RETRIES,
                    )
                else:
                    raise SourceError(
                        f"{self.name}: HTTP {response.status_code} - {response.text[:200]}"
                    )

            if attempt < config.MAX_RETRIES:
                time.sleep(2 ** (attempt - 1))

        raise SourceError(f"{self.name}: gave up after {config.MAX_RETRIES} attempts ({last_error})")
