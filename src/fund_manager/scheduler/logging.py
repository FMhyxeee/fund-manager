"""Structured logging adapter for scheduler lifecycle events."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fund_manager.scheduler.types import (
    JobFrequency,
    JobResult,
)

logger = logging.getLogger("fund_manager.scheduler")


class SchedulerLogger:
    """Logs scheduler start, success, and failure events.

    Events are written both to the Python logger and optionally to a
    SystemEventLogRepository for append-only persistence.
    """

    def log_started(
        self,
        *,
        entry_name: str,
        frequency: JobFrequency,
        run_id: str,
        portfolio_id: int,
        trigger_source: str,
    ) -> None:
        message = (
            f"Scheduler job started: name={entry_name}, "
            f"frequency={frequency.value}, run_id={run_id}, "
            f"portfolio_id={portfolio_id}, trigger={trigger_source}"
        )
        logger.info(message)

    def log_completed(
        self,
        *,
        entry_name: str,
        frequency: JobFrequency,
        run_id: str,
        portfolio_id: int,
        trigger_source: str,
        started_at: datetime,
        finished_at: datetime,
    ) -> None:
        duration_ms = (finished_at - started_at).total_seconds() * 1000
        message = (
            f"Scheduler job completed: name={entry_name}, "
            f"frequency={frequency.value}, run_id={run_id}, "
            f"portfolio_id={portfolio_id}, duration_ms={duration_ms:.1f}"
        )
        logger.info(message)

    def log_failed(
        self,
        *,
        entry_name: str,
        frequency: JobFrequency,
        run_id: str,
        portfolio_id: int,
        trigger_source: str,
        error_message: str,
        started_at: datetime,
        finished_at: datetime,
    ) -> None:
        duration_ms = (finished_at - started_at).total_seconds() * 1000
        message = (
            f"Scheduler job failed: name={entry_name}, "
            f"frequency={frequency.value}, run_id={run_id}, "
            f"portfolio_id={portfolio_id}, "
            f"error={error_message}, duration_ms={duration_ms:.1f}"
        )
        logger.error(message)

    def build_event_payload(self, result: JobResult) -> dict[str, Any]:
        return {
            "entry_name": result.entry_name,
            "frequency": result.frequency.value,
            "run_id": result.run_id,
            "portfolio_id": result.portfolio_id,
            "trigger_source": result.trigger_source,
            "status": result.status.value,
            "started_at": result.started_at.isoformat(),
            "finished_at": result.finished_at.isoformat(),
            "error_message": result.error_message,
            "payload": result.payload,
        }

    def persist_event(
        self,
        result: JobResult,
        system_event_log_repo: Any,
    ) -> None:
        event_type = f"scheduler_{result.status.value}"
        event_message = (
            f"Scheduler job {result.status.value}: {result.entry_name} ({result.frequency.value})"
        )
        system_event_log_repo.append(
            event_type=event_type,
            status=result.status.value,
            portfolio_id=result.portfolio_id,
            run_id=result.run_id,
            workflow_name="scheduler",
            event_message=event_message,
            payload_json=self.build_event_payload(result),
        )
