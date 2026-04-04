"""Scheduler engine for executing registered jobs on demand or by frequency."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fund_manager.scheduler.logging import SchedulerLogger
from fund_manager.scheduler.registry import SchedulerRegistry
from fund_manager.scheduler.types import (
    JobFrequency,
    JobResult,
    JobStatus,
    ScheduleEntry,
    TriggerSource,
)


def _build_run_id(entry_name: str) -> str:
    return f"scheduler-{entry_name}-{uuid4().hex[:8]}"


class SchedulerEngine:
    """Execute scheduled jobs and collect structured results.

    The engine is responsible for:
    - Running a single job by name and frequency.
    - Running all enabled jobs for a given frequency.
    - Logging start, success, and failure events.
    - Optionally persisting events to a SystemEventLogRepository.

    The engine does NOT own scheduling loop logic (timers, cron, etc.).
    That responsibility belongs to the runtime or a separate trigger loop.
    """

    def __init__(
        self,
        registry: SchedulerRegistry,
        *,
        scheduler_logger: SchedulerLogger | None = None,
        system_event_log_repo: Any | None = None,
    ) -> None:
        self._registry = registry
        self._logger = scheduler_logger or SchedulerLogger()
        self._event_repo = system_event_log_repo

    def run_job(
        self,
        name: str,
        frequency: JobFrequency,
        *,
        portfolio_id: int,
        trigger_source: str = TriggerSource.MANUAL,
    ) -> JobResult:
        entry = self._registry.get(name, frequency)
        if not entry.enabled:
            msg = f"Job {name!r} is disabled and cannot be executed."
            raise RuntimeError(msg)
        return self._execute_entry(
            entry,
            portfolio_id=portfolio_id,
            trigger_source=trigger_source,
        )

    def run_all_for_frequency(
        self,
        frequency: JobFrequency,
        *,
        portfolio_id: int,
        trigger_source: str = TriggerSource.SCHEDULED,
    ) -> Sequence[JobResult]:
        entries = self._registry.list_by_frequency(frequency)
        enabled = [entry for entry in entries if entry.enabled]
        results: list[JobResult] = []
        for entry in enabled:
            result = self._execute_entry(
                entry,
                portfolio_id=portfolio_id,
                trigger_source=trigger_source,
            )
            results.append(result)
        return tuple(results)

    def _execute_entry(
        self,
        entry: ScheduleEntry,
        *,
        portfolio_id: int,
        trigger_source: str,
    ) -> JobResult:
        run_id = _build_run_id(entry.name)
        started_at = datetime.now(tz=UTC)

        self._logger.log_started(
            entry_name=entry.name,
            frequency=entry.frequency,
            run_id=run_id,
            portfolio_id=portfolio_id,
            trigger_source=trigger_source,
        )

        try:
            payload = entry.job_fn(portfolio_id=portfolio_id, trigger_source=trigger_source)
            finished_at = datetime.now(tz=UTC)
            result = JobResult(
                entry_name=entry.name,
                frequency=entry.frequency,
                status=JobStatus.COMPLETED,
                run_id=run_id,
                started_at=started_at,
                finished_at=finished_at,
                portfolio_id=portfolio_id,
                trigger_source=trigger_source,
                payload=payload if isinstance(payload, dict) else {},
            )
            self._logger.log_completed(
                entry_name=entry.name,
                frequency=entry.frequency,
                run_id=run_id,
                portfolio_id=portfolio_id,
                trigger_source=trigger_source,
                started_at=started_at,
                finished_at=finished_at,
            )
        except Exception as exc:
            finished_at = datetime.now(tz=UTC)
            result = JobResult(
                entry_name=entry.name,
                frequency=entry.frequency,
                status=JobStatus.FAILED,
                run_id=run_id,
                started_at=started_at,
                finished_at=finished_at,
                portfolio_id=portfolio_id,
                trigger_source=trigger_source,
                error_message=f"{type(exc).__name__}: {exc}",
            )
            self._logger.log_failed(
                entry_name=entry.name,
                frequency=entry.frequency,
                run_id=run_id,
                portfolio_id=portfolio_id,
                trigger_source=trigger_source,
                error_message=result.error_message or "unknown",
                started_at=started_at,
                finished_at=finished_at,
            )

        if self._event_repo is not None:
            try:
                self._logger.persist_event(result, self._event_repo)
            except Exception:
                pass

        return result
