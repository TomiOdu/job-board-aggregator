"""Daily job aggregator: fetch -> filter -> dedupe -> merge -> write.

Run locally with:  python main.py
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

from dotenv import load_dotenv

import config
from core import metrics, quality, storage
from core.dedupe import merge_with_master
from core.filters import apply_filters
from core.logging_setup import setup_logging
from core.metrics import RunMetrics, SourceMetrics
from core.models import JobListing
from sources import AuthError, SearchQuery, SourceError, build_sources

logger = logging.getLogger(__name__)


def collect_from_source(source) -> tuple[list[JobListing], int, int, int]:
    """Run every keyword x pass query for one source.

    Returns (listings, rejected_count, queries_attempted, queries_failed).
    The caller needs the query counts to tell "this source genuinely found
    nothing" apart from "every query errored" - which look identical if you
    only count listings.
    """
    collected: list[JobListing] = []
    rejected_total = 0
    attempted = 0
    failed = 0

    for pass_ in config.SEARCH_PASSES:
        for keyword in config.KEYWORDS:
            if len(collected) >= config.MAX_RESULTS_PER_SOURCE:
                logger.info(
                    "[%s] hit MAX_RESULTS_PER_SOURCE (%d), stopping early",
                    source.name, config.MAX_RESULTS_PER_SOURCE,
                )
                return collected, rejected_total, attempted, failed

            query = SearchQuery(
                keyword=keyword,
                location=pass_.location,
                radius_km=pass_.radius_km,
                remote_only=pass_.remote_only,
                limit=min(
                    config.RESULTS_PER_QUERY,
                    config.MAX_RESULTS_PER_SOURCE - len(collected),
                ),
            )

            attempted += 1
            try:
                raw = source.fetch(query)
            except AuthError as exc:
                # Credentials are wrong - every remaining query would 401 too.
                logger.error("[%s] %s", source.name, exc)
                failed += attempted - failed
                return collected, rejected_total, attempted, failed
            except SourceError as exc:
                # One bad query should not kill the rest of the source.
                logger.error("[%s] query failed (%s): %s", source.name, keyword, exc)
                failed += 1
                continue

            kept, rejected = apply_filters(raw, remote_only=pass_.remote_only)
            rejected_total += len(rejected)
            collected.extend(kept)

            logger.debug(
                "[%s] %s/%s: %d raw, %d kept, %d rejected",
                source.name, pass_.name, keyword, len(raw), len(kept), len(rejected),
            )
            if rejected:
                logger.debug("[%s] rejected sample: %s", source.name, rejected[:5])

    return collected, rejected_total, attempted, failed


def run(only_sources: list[str] | None = None, dry_run: bool = False) -> int:
    today = date.today()
    today_iso = today.isoformat()

    sources = build_sources(only_sources)
    if not sources:
        logger.error("No sources selected - nothing to do")
        return 1

    run_metrics = RunMetrics()
    fetched: list[JobListing] = []
    failures = 0

    for source in sources:
        stats = SourceMetrics(name=source.name)
        run_metrics.add_source(stats)

        if not source.is_configured():
            logger.warning(
                "[%s] skipped - credentials not set (see .env.example)", source.name
            )
            stats.configured = False
            failures += 1
            continue

        try:
            listings, rejected, attempted, failed = collect_from_source(source)
        except Exception as exc:  # noqa: BLE001 - one source must never kill the run
            logger.exception("[%s] failed entirely: %s", source.name, exc)
            stats.failed = True
            failures += 1
            continue

        stats.queries_attempted = attempted
        stats.queries_failed = failed
        stats.listings_kept = len(listings)
        stats.rejected_by_filter = rejected

        # Every query erroring is a failure, not an empty result set. Without
        # this the run exits 0 having quietly fetched nothing.
        if attempted and failed == attempted:
            logger.error(
                "[%s] all %d queries failed - treating the source as failed", source.name, attempted
            )
            stats.failed = True
            failures += 1
            continue

        logger.info(
            "[%s] %d listings kept (%d rejected by title filter, %d/%d queries failed)",
            source.name, len(listings), rejected, failed, attempted,
        )
        fetched.extend(listings)

    if failures == len(sources):
        logger.error("Every source failed or was unconfigured - not touching the dataset")
        run_metrics.quality_status = "not_run"
        if not dry_run:
            metrics.append_run(run_metrics, config.RUN_HISTORY_CSV)
        return 1

    existing = storage.load_master(config.MASTER_CSV)
    full, new_today = merge_with_master(existing, fetched, today_iso)

    logger.info(
        "Run summary: %d fetched (post-filter), %d new today, %d total in dataset",
        len(fetched), len(new_today), len(full),
    )
    for listing in new_today[:10]:
        logger.info("  NEW  %s - %s (%s)", listing.title, listing.company, listing.source)
    if len(new_today) > 10:
        logger.info("  ... and %d more", len(new_today) - 10)

    run_metrics.new_today = len(new_today)
    run_metrics.total_in_dataset = len(full)

    # Quality gate runs before anything is written, so a failure leaves the
    # previous good dataset in place rather than overwriting it with bad data.
    logger.info("Running data quality checks...")
    results = quality.run_all(full, previous_count=len(existing), today=today_iso)
    safe_to_write, status = quality.report(results)
    run_metrics.quality_status = status

    if dry_run:
        logger.info("Dry run - no files written")
        return 0 if safe_to_write else 1

    if not safe_to_write:
        metrics.append_run(run_metrics, config.RUN_HISTORY_CSV)
        return 1

    storage.write_outputs(full, new_today, today)
    metrics.append_run(run_metrics, config.RUN_HISTORY_CSV)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch UK Data/Analytics Engineering jobs")
    parser.add_argument(
        "--sources", nargs="+", metavar="NAME",
        help="Only run these sources, e.g. --sources adzuna",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Fetch and report, but write no files"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug logging")
    args = parser.parse_args()

    # Explicit path so the run works from any working directory. Absent in CI,
    # where the values come from GitHub Actions secrets instead.
    load_dotenv(config.ROOT / ".env")
    setup_logging(verbose=args.verbose)

    try:
        return run(only_sources=args.sources, dry_run=args.dry_run)
    except KeyboardInterrupt:
        logger.warning("Interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
