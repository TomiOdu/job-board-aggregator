"""Run history / metrics tests."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.metrics import BASE_COLUMNS, RunMetrics, SourceMetrics, append_run


def build(new_today=5, total=100, status="passed", sources=("Adzuna", "Reed")) -> RunMetrics:
    m = RunMetrics(started_at=datetime(2026, 8, 20, 6, 0, tzinfo=timezone.utc))
    for name in sources:
        m.add_source(
            SourceMetrics(name=name, queries_attempted=8, queries_failed=0,
                          listings_kept=50, rejected_by_filter=100)
        )
    m.new_today = new_today
    m.total_in_dataset = total
    m.quality_status = status
    return m


def test_row_carries_run_and_per_source_metrics():
    row = build().to_row()

    assert row["run_date"] == "2026-08-20"
    assert row["sources_run"] == 2
    assert row["fetched_post_filter"] == 100      # 50 + 50
    assert row["new_today"] == 5
    assert row["quality_status"] == "passed"
    assert row["adzuna_kept"] == 50
    assert row["reed_status"] == "ok"


def test_skipped_and_failed_sources_are_recorded():
    m = RunMetrics()
    m.add_source(SourceMetrics(name="Adzuna", listings_kept=10, queries_attempted=8))
    m.add_source(SourceMetrics(name="Reed", configured=False))
    m.add_source(SourceMetrics(name="Other", failed=True, queries_attempted=8, queries_failed=8))

    row = m.to_row()
    assert row["sources_failed"] == 2
    assert row["reed_status"] == "skipped"
    assert row["other_status"] == "failed"


def test_appending_accumulates_runs(tmp_path):
    path = tmp_path / "run_history.csv"

    append_run(build(new_today=5), path)
    append_run(build(new_today=3), path)

    frame = pd.read_csv(path, encoding="utf-8-sig")
    assert len(frame) == 2
    assert list(frame.new_today) == [5, 3]
    assert list(frame.columns)[: len(BASE_COLUMNS)] == BASE_COLUMNS


def test_adding_a_source_later_does_not_break_the_file(tmp_path):
    """A new adapter widens the schema; old rows must survive."""
    path = tmp_path / "run_history.csv"

    append_run(build(sources=("Adzuna",)), path)
    append_run(build(sources=("Adzuna", "Reed")), path)

    frame = pd.read_csv(path, encoding="utf-8-sig")
    assert len(frame) == 2
    assert "reed_kept" in frame.columns
    assert pd.isna(frame.loc[0, "reed_kept"])     # absent on the earlier run
    assert frame.loc[1, "reed_kept"] == 50
