"""Per-run metrics, appended to data/run_history.csv.

A scheduled pipeline is only trustworthy if you can see how it has behaved
over time. One row per run makes trends chartable straight from the CSV:
listings found per day, which source is degrading, how often the quality gate
trips, how long runs take.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# Run-level columns always come first; per-source columns are appended after,
# so adding a source widens the file instead of breaking its schema.
BASE_COLUMNS = [
    "run_id",
    "run_date",
    "started_at_utc",
    "duration_seconds",
    "sources_run",
    "sources_failed",
    "fetched_post_filter",
    "rejected_by_filter",
    "new_today",
    "total_in_dataset",
    "quality_status",
]


@dataclass
class SourceMetrics:
    """What one source did during a run."""

    name: str
    configured: bool = True
    queries_attempted: int = 0
    queries_failed: int = 0
    listings_kept: int = 0
    rejected_by_filter: int = 0
    failed: bool = False


@dataclass
class RunMetrics:
    """Everything worth recording about a single run."""

    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    sources: list[SourceMetrics] = field(default_factory=list)
    new_today: int = 0
    total_in_dataset: int = 0
    quality_status: str = "not_run"

    def add_source(self, metrics: SourceMetrics) -> None:
        self.sources.append(metrics)

    def to_row(self) -> dict[str, object]:
        finished = datetime.now(timezone.utc)
        row: dict[str, object] = {
            "run_id": self.started_at.strftime("%Y%m%dT%H%M%SZ"),
            "run_date": self.started_at.date().isoformat(),
            "started_at_utc": self.started_at.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_seconds": round((finished - self.started_at).total_seconds(), 1),
            "sources_run": len(self.sources),
            "sources_failed": sum(1 for s in self.sources if s.failed or not s.configured),
            "fetched_post_filter": sum(s.listings_kept for s in self.sources),
            "rejected_by_filter": sum(s.rejected_by_filter for s in self.sources),
            "new_today": self.new_today,
            "total_in_dataset": self.total_in_dataset,
            "quality_status": self.quality_status,
        }

        for source in self.sources:
            key = source.name.lower()
            row[f"{key}_kept"] = source.listings_kept
            row[f"{key}_queries_failed"] = source.queries_failed
            row[f"{key}_status"] = (
                "skipped" if not source.configured else "failed" if source.failed else "ok"
            )

        return row


def append_run(metrics: RunMetrics, path: Path) -> None:
    """Append this run to the history file, preserving any older columns."""
    row = metrics.to_row()
    path.parent.mkdir(parents=True, exist_ok=True)

    frame = pd.DataFrame([row])
    if path.exists():
        existing = pd.read_csv(path, encoding="utf-8-sig")
        # A newly added source introduces columns the old file lacks (and a
        # removed one leaves columns behind); union them rather than lose data.
        frame = pd.concat([existing, frame], ignore_index=True)

    ordered = BASE_COLUMNS + [c for c in frame.columns if c not in BASE_COLUMNS]
    frame = frame.reindex(columns=ordered)
    frame.to_csv(path, index=False, encoding="utf-8-sig")

    logger.info(
        "Run recorded in %s (%d runs total, this one took %ss)",
        path.name, len(frame), row["duration_seconds"],
    )
