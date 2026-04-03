"""CLI entry point for manually triggering scheduler jobs."""

from __future__ import annotations

import argparse
import sys
from datetime import date

from fund_manager.scheduler.engine import SchedulerEngine
from fund_manager.scheduler.jobs import register_default_jobs
from fund_manager.scheduler.logging import SchedulerLogger
from fund_manager.scheduler.registry import SchedulerRegistry
from fund_manager.scheduler.types import JobFrequency, TriggerSource
from fund_manager.storage.db import get_session_factory
from fund_manager.storage.repo import SystemEventLogRepository


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Manually trigger scheduled workflow jobs for local development.",
    )
    parser.add_argument(
        "frequency",
        choices=[f.value for f in JobFrequency],
        help="Job frequency to run.",
    )
    parser.add_argument(
        "--portfolio-id",
        type=int,
        required=True,
        help="Portfolio ID to run the job against.",
    )
    parser.add_argument(
        "--as-of-date",
        type=lambda s: date.fromisoformat(s),
        default=None,
        help="Override the as-of date (YYYY-MM-DD). Defaults to today.",
    )
    parser.add_argument(
        "--job-name",
        default=None,
        help="Run a specific job by name instead of all jobs for the frequency.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    frequency = JobFrequency(args.frequency)
    as_of_date = args.as_of_date or date.today()
    trigger_source = TriggerSource.MANUAL

    session_factory = get_session_factory()

    with session_factory() as session:
        registry = SchedulerRegistry()
        register_default_jobs(session, registry, as_of_date=as_of_date)

        event_repo = SystemEventLogRepository(session)
        engine = SchedulerEngine(
            registry,
            scheduler_logger=SchedulerLogger(),
            system_event_log_repo=event_repo,
        )

        if args.job_name:
            result = engine.run_job(
                args.job_name,
                frequency,
                portfolio_id=args.portfolio_id,
                trigger_source=trigger_source,
            )
            results = [result]
        else:
            results = list(
                engine.run_all_for_frequency(
                    frequency,
                    portfolio_id=args.portfolio_id,
                    trigger_source=trigger_source,
                )
            )

        session.commit()

    for result in results:
        status_marker = "OK" if result.status.value == "completed" else "FAIL"
        print(
            f"[{status_marker}] {result.entry_name} "
            f"run_id={result.run_id} "
            f"portfolio_id={result.portfolio_id}",
            file=sys.stdout,
        )
        if result.error_message:
            print(f"  error: {result.error_message}", file=sys.stderr)

    if any(r.status.value == "failed" for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
