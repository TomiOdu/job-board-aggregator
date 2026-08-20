"""The canonical listing model every source adapter must produce."""
from __future__ import annotations

from dataclasses import asdict, dataclass

# Column order used in the CSV and Excel outputs.
COLUMNS = [
    "job_id",
    "first_seen_date",
    "last_seen_date",
    "title",
    "company",
    "location",
    "is_remote",
    "salary_min",
    "salary_max",
    "salary_currency",
    "salary_period",
    "salary_is_estimate",
    "salary_raw",
    "contract_type",
    "contract_time",
    "date_posted",
    "source",
    "url",
    "description",
]

# Columns that should end up numeric in the spreadsheet.
NUMERIC_COLUMNS = ["salary_min", "salary_max"]


@dataclass
class JobListing:
    """One job posting, normalised into a source-independent shape."""

    title: str
    company: str
    location: str
    url: str
    source: str
    description: str = ""
    date_posted: str = ""        # ISO date, e.g. "2026-08-19"
    contract_type: str = ""      # permanent | contract | temporary
    contract_time: str = ""      # full_time | part_time
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str = ""
    salary_period: str = ""      # annual | daily | hourly
    # True when the figure is the board's own prediction rather than a salary
    # the advertiser published. Adzuna returns these for ~1 in 3 listings.
    salary_is_estimate: bool = False
    salary_raw: str = ""
    is_remote: bool = False

    # Populated by the dedupe/merge stage, not by adapters.
    job_id: str = ""
    first_seen_date: str = ""
    last_seen_date: str = ""

    def to_row(self) -> dict[str, object]:
        """Flatten to a dict in COLUMNS order, ready for CSV/DataFrame output."""
        raw = asdict(self)
        return {col: raw.get(col, "") for col in COLUMNS}

    @classmethod
    def from_row(cls, row: dict[str, object]) -> "JobListing":
        """Rebuild from a CSV row (all values arrive as strings)."""

        def num(key: str) -> float | None:
            value = str(row.get(key, "") or "").strip()
            if not value:
                return None
            try:
                return float(value)
            except ValueError:
                return None

        def text(key: str) -> str:
            return str(row.get(key, "") or "").strip()

        return cls(
            title=text("title"),
            company=text("company"),
            location=text("location"),
            url=text("url"),
            source=text("source"),
            description=text("description"),
            date_posted=text("date_posted"),
            contract_type=text("contract_type"),
            contract_time=text("contract_time"),
            salary_min=num("salary_min"),
            salary_max=num("salary_max"),
            salary_currency=text("salary_currency"),
            salary_period=text("salary_period"),
            salary_raw=text("salary_raw"),
            salary_is_estimate=text("salary_is_estimate").lower() in {"true", "1", "yes"},
            is_remote=text("is_remote").lower() in {"true", "1", "yes"},
            job_id=text("job_id"),
            first_seen_date=text("first_seen_date"),
            last_seen_date=text("last_seen_date"),
        )
