"""End-to-end check that a failing quality gate protects the existing dataset.

The unit tests prove the checks classify correctly. This proves the pipeline
acts on that classification: no partial write, no clobbered master file.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
import main
from core.models import JobListing
from sources.base import JobSource, SearchQuery


class FakeSource(JobSource):
    name = "Fake"

    def __init__(self, listings):
        self.listings = listings

    def is_configured(self) -> bool:
        return True

    def fetch(self, query: SearchQuery):
        return [
            JobListing(title=t, company="Acme", location="London",
                       url=f"https://example.com/{t.replace(' ', '-')}",
                       source="Fake", description="Pipelines.")
            for t in self.listings
        ]


def point_config_at(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "ARCHIVE_DIR", tmp_path / "archive")
    monkeypatch.setattr(config, "MASTER_CSV", tmp_path / "master.csv")
    monkeypatch.setattr(config, "LATEST_XLSX", tmp_path / "latest.xlsx")
    monkeypatch.setattr(config, "NEW_TODAY_CSV", tmp_path / "new_today.csv")
    monkeypatch.setattr(config, "RUN_HISTORY_CSV", tmp_path / "run_history.csv")
    # One keyword and one pass keeps the fake source's output predictable.
    monkeypatch.setattr(config, "KEYWORDS", ["Data Engineer"])
    monkeypatch.setattr(config, "SEARCH_PASSES", config.SEARCH_PASSES[:1])


def test_failing_gate_leaves_the_previous_dataset_untouched(tmp_path, monkeypatch):
    point_config_at(tmp_path, monkeypatch)

    # First run: a healthy dataset gets written.
    monkeypatch.setattr(
        main, "build_sources",
        lambda only: [FakeSource(["Data Engineer", "Senior Data Engineer", "Lead Data Engineer"])],
    )
    assert main.run() == 0

    good = config.MASTER_CSV.read_text(encoding="utf-8-sig")
    assert config.MASTER_CSV.exists()
    assert len(good.splitlines()) == 4          # header + 3 rows

    # Second run: force the row-count check to fail by demanding the dataset
    # more than double, which mimics a source returning garbage.
    monkeypatch.setattr(config, "QUALITY_MIN_ROW_RETENTION", 2.0)
    monkeypatch.setattr(main, "build_sources", lambda only: [FakeSource(["Data Engineer"])])

    assert main.run() == 1                       # run fails loudly

    # The critical assertion: the good data is still there, byte for byte.
    assert config.MASTER_CSV.read_text(encoding="utf-8-sig") == good


def test_failed_run_is_still_recorded_in_run_history(tmp_path, monkeypatch):
    """A blocked write must not also lose the record that the run happened."""
    point_config_at(tmp_path, monkeypatch)

    monkeypatch.setattr(
        main, "build_sources", lambda only: [FakeSource(["Data Engineer", "Lead Data Engineer"])]
    )
    assert main.run() == 0

    monkeypatch.setattr(config, "QUALITY_MIN_ROW_RETENTION", 2.0)
    monkeypatch.setattr(main, "build_sources", lambda only: [FakeSource(["Data Engineer"])])
    assert main.run() == 1

    import pandas as pd
    history = pd.read_csv(config.RUN_HISTORY_CSV, encoding="utf-8-sig")
    assert len(history) == 2
    assert list(history.quality_status) == ["passed", "failed"]


def test_healthy_run_writes_every_output(tmp_path, monkeypatch):
    point_config_at(tmp_path, monkeypatch)
    monkeypatch.setattr(
        main, "build_sources", lambda only: [FakeSource(["Data Engineer", "Analytics Engineer"])]
    )

    assert main.run() == 0

    for path in (config.MASTER_CSV, config.LATEST_XLSX,
                 config.NEW_TODAY_CSV, config.RUN_HISTORY_CSV):
        assert path.exists(), path.name
