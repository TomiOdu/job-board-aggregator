"""Failure semantics of the orchestrator.

The bug these guard against: per-query errors were swallowed inside
collect_from_source, so a run where every query 401'd still exited 0 and
reported success with an empty dataset - a silently green CI build.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from core.models import JobListing
from sources.base import AuthError, JobSource, SearchQuery, SourceError, is_placeholder


class FakeSource(JobSource):
    def __init__(self, name, error=None, listings=None):
        self.name = name
        self.error = error
        self.listings = listings or []
        self.calls = 0

    def is_configured(self) -> bool:
        return True

    def fetch(self, query: SearchQuery):
        self.calls += 1
        if self.error:
            raise self.error
        return list(self.listings)


def good_listing():
    return JobListing(
        title="Data Engineer", company="Acme", location="London",
        url="https://example.com/1", source="Fake", description="Pipelines.",
    )


def test_all_queries_failing_exits_nonzero(monkeypatch):
    source = FakeSource("Fake", error=SourceError("boom"))
    monkeypatch.setattr(main, "build_sources", lambda only: [source])
    assert main.run(dry_run=True) == 1


def test_auth_error_stops_after_one_query(monkeypatch):
    source = FakeSource("Fake", error=AuthError("bad key"))
    monkeypatch.setattr(main, "build_sources", lambda only: [source])
    assert main.run(dry_run=True) == 1
    # Must not keep hammering the API with credentials it knows are rejected.
    assert source.calls == 1


def test_one_source_failing_does_not_sink_the_run(monkeypatch):
    broken = FakeSource("Broken", error=SourceError("boom"))
    working = FakeSource("Working", listings=[good_listing()])
    monkeypatch.setattr(main, "build_sources", lambda only: [broken, working])
    assert main.run(dry_run=True) == 0


def test_unconfigured_source_is_skipped_not_called(monkeypatch):
    source = FakeSource("Fake")
    source.is_configured = lambda: False
    monkeypatch.setattr(main, "build_sources", lambda only: [source])
    assert main.run(dry_run=True) == 1
    assert source.calls == 0


def test_placeholder_credentials_are_not_configured():
    assert is_placeholder("your_adzuna_app_id")
    assert is_placeholder("")
    assert is_placeholder("   ")
    assert not is_placeholder("a1b2c3d4")
