"""Central configuration.

Everything you are likely to want to tune lives here - keywords, location,
how many results to pull, and which job titles count as a match.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# --------------------------------------------------------------------------
# Search parameters
# --------------------------------------------------------------------------

KEYWORDS = [
    "Data Engineer",
    "Analytics Engineer",
    "Data Engineering",
    "dbt Analytics Engineer",
]

LONDON_LOCATION = "London"
# Adzuna's `distance` parameter is in kilometres. 40km is about 25 miles.
LONDON_RADIUS_KM = 40

# Ignore anything posted longer ago than this.
MAX_DAYS_OLD = 30

# Results requested per individual query (keyword x pass).
RESULTS_PER_QUERY = 50
# Hard ceiling per source per run, so a bad query cannot run up your API quota.
MAX_RESULTS_PER_SOURCE = 200


@dataclass(frozen=True)
class SearchPass:
    """One sweep of a source: a location scope plus whether it targets remote roles."""

    name: str
    location: str | None      # None = nationwide
    radius_km: int | None
    remote_only: bool


SEARCH_PASSES = [
    SearchPass("london", LONDON_LOCATION, LONDON_RADIUS_KM, remote_only=False),
    SearchPass("remote-uk", None, None, remote_only=True),
]


# --------------------------------------------------------------------------
# Title filtering (strict)
#
# A listing is kept only if its title matches one of TITLE_PATTERNS and none
# of TITLE_EXCLUDE_PATTERNS. Loosen by adding patterns here - e.g. add
# r"\bdata\s+platform\s+engineer\b" if you want those too.
# --------------------------------------------------------------------------

TITLE_PATTERNS = [
    r"\bdata\s+engineer(ing)?\b",
    r"\banalytics\s+engineer(ing)?\b",
    r"\bdbt\b.*\bengineer\b",
]

TITLE_EXCLUDE_PATTERNS: list[str] = [
    # Matches intern, interns, internship, internships - but not "internal"
    # or "international", which fail the word boundary.
    r"\bintern(ship)?s?\b",
    # e.g. add r"\btrainee\b" or r"\bplacement\b" to filter those too
]


# --------------------------------------------------------------------------
# Remote detection - matched against title, location and description
# --------------------------------------------------------------------------

REMOTE_PATTERNS = [
    r"\bfully[- ]remote\b",
    r"\bremote\b",
    r"\bwork from home\b",
    r"\bwfh\b",
    r"\bhome[- ]based\b",
]


# --------------------------------------------------------------------------
# Output paths
# --------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
ARCHIVE_DIR = DATA_DIR / "archive"
LOG_DIR = ROOT / "logs"

MASTER_CSV = DATA_DIR / "job_listings_master.csv"
LATEST_XLSX = DATA_DIR / "job_listings_latest.xlsx"
NEW_TODAY_CSV = DATA_DIR / "job_listings_new_today.csv"
RUN_HISTORY_CSV = DATA_DIR / "run_history.csv"


# --------------------------------------------------------------------------
# Data quality gate
#
# Fatal failures abort the write so the previous good dataset survives.
# --------------------------------------------------------------------------

# Fail if the merged dataset drops below this fraction of the previous run.
QUALITY_MIN_ROW_RETENTION = 0.5

# Plausible bounds per salary period; anything outside is flagged as a warning,
# usually meaning a figure landed in the wrong period bucket.
QUALITY_SALARY_BOUNDS = {
    "annual": (10_000, 500_000),
    "daily": (50, 3_000),
    "hourly": (5, 500),
}

# Write a dated copy of the workbook into data/archive/ on each run.
WRITE_ARCHIVE_COPY = True

# Truncate the description snippet to this many characters.
DESCRIPTION_MAX_CHARS = 400

# HTTP behaviour.
REQUEST_DELAY_SECONDS = 0.5
REQUEST_TIMEOUT_SECONDS = 20
MAX_RETRIES = 3
