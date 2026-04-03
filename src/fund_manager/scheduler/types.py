"""Scheduler domain types for job registration and execution results."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol


class JobFrequency(StrEnum):
    """Supported scheduling frequencies."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class TriggerSource(StrEnum):
    """Origin of a scheduler invocation."""

    MANUAL = "manual"
    SCHEDULED = "scheduled"
    API = "api"


class JobStatus(StrEnum):
    """Status of a job execution."""

    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"


class JobFn(Protocol):
    """Protocol for callable job functions executed by the scheduler."""

    def __call__(
        self,
        *,
        portfolio_id: int,
        trigger_source: str,
    ) -> Any: ...


@dataclass(frozen=True)
class ScheduleEntry:
    """Immutable registration record for one scheduled job."""

    name: str
    frequency: JobFrequency
    job_fn: Callable[..., Any]
    description: str = ""
    enabled: bool = True
    portfolio_id: int | None = None

    def __hash__(self) -> int:
        return hash((self.name, self.frequency))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ScheduleEntry):
            return NotImplemented
        return self.name == other.name and self.frequency == other.frequency


@dataclass(frozen=True)
class JobResult:
    """Outcome of a single job execution."""

    entry_name: str
    frequency: JobFrequency
    status: JobStatus
    run_id: str
    started_at: datetime
    finished_at: datetime
    portfolio_id: int
    trigger_source: str
    error_message: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
