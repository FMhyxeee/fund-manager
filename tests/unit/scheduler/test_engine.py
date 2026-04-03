"""Unit tests for the scheduler engine."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from fund_manager.scheduler.engine import SchedulerEngine
from fund_manager.scheduler.logging import SchedulerLogger
from fund_manager.scheduler.registry import SchedulerRegistry
from fund_manager.scheduler.types import (
    JobFrequency,
    JobStatus,
    ScheduleEntry,
    TriggerSource,
)


def _make_entry(
    name: str = "test_job",
    frequency: JobFrequency = JobFrequency.DAILY,
    job_fn: Any = None,
    enabled: bool = True,
) -> ScheduleEntry:
    return ScheduleEntry(
        name=name,
        frequency=frequency,
        job_fn=job_fn or (lambda *, portfolio_id, trigger_source: None),
        enabled=enabled,
    )


class TestSchedulerEngineRunJob:
    def test_run_job_completes_successfully(self) -> None:
        registry = SchedulerRegistry()
        call_log: list[dict[str, Any]] = []
        entry = _make_entry(
            job_fn=lambda *, portfolio_id, trigger_source: call_log.append(
                {"portfolio_id": portfolio_id, "trigger_source": trigger_source}
            ),
        )
        registry.register(entry)
        engine = SchedulerEngine(registry)
        result = engine.run_job(
            "test_job",
            JobFrequency.DAILY,
            portfolio_id=1,
            trigger_source=TriggerSource.MANUAL,
        )
        assert result.status == JobStatus.COMPLETED
        assert result.entry_name == "test_job"
        assert result.frequency == JobFrequency.DAILY
        assert result.portfolio_id == 1
        assert result.trigger_source == TriggerSource.MANUAL
        assert result.error_message is None
        assert result.run_id.startswith("scheduler-test_job-")
        assert call_log == [{"portfolio_id": 1, "trigger_source": "manual"}]

    def test_run_job_captures_failure(self) -> None:
        registry = SchedulerRegistry()

        def failing_fn(*, portfolio_id: int, trigger_source: str) -> None:
            msg = "deliberate test failure"
            raise RuntimeError(msg)

        entry = _make_entry(job_fn=failing_fn)
        registry.register(entry)
        engine = SchedulerEngine(registry)
        result = engine.run_job(
            "test_job",
            JobFrequency.DAILY,
            portfolio_id=1,
            trigger_source=TriggerSource.SCHEDULED,
        )
        assert result.status == JobStatus.FAILED
        assert result.error_message is not None
        assert "deliberate test failure" in result.error_message

    def test_run_disabled_job_raises(self) -> None:
        registry = SchedulerRegistry()
        entry = _make_entry(enabled=False)
        registry.register(entry)
        engine = SchedulerEngine(registry)
        with pytest.raises(RuntimeError, match="disabled"):
            engine.run_job(
                "test_job",
                JobFrequency.DAILY,
                portfolio_id=1,
            )

    def test_run_missing_job_raises(self) -> None:
        registry = SchedulerRegistry()
        engine = SchedulerEngine(registry)
        with pytest.raises(KeyError):
            engine.run_job(
                "missing",
                JobFrequency.DAILY,
                portfolio_id=1,
            )


class TestSchedulerEngineRunAllForFrequency:
    def test_run_all_executes_enabled_jobs_only(self) -> None:
        registry = SchedulerRegistry()
        call_log: list[str] = []
        registry.register(
            _make_entry(
                name="enabled_a",
                job_fn=lambda *, portfolio_id, trigger_source: call_log.append("a"),
            )
        )
        registry.register(
            _make_entry(
                name="enabled_b",
                job_fn=lambda *, portfolio_id, trigger_source: call_log.append("b"),
            )
        )
        registry.register(
            _make_entry(
                name="disabled_c",
                enabled=False,
                job_fn=lambda *, portfolio_id, trigger_source: call_log.append("c"),
            )
        )
        registry.register(
            _make_entry(
                name="weekly_job",
                frequency=JobFrequency.WEEKLY,
                job_fn=lambda *, portfolio_id, trigger_source: call_log.append("w"),
            )
        )
        engine = SchedulerEngine(registry)
        results = engine.run_all_for_frequency(
            JobFrequency.DAILY,
            portfolio_id=1,
            trigger_source=TriggerSource.SCHEDULED,
        )
        assert len(results) == 2
        assert all(r.status == JobStatus.COMPLETED for r in results)
        assert set(call_log) == {"a", "b"}

    def test_run_all_continues_after_failure(self) -> None:
        registry = SchedulerRegistry()
        call_log: list[str] = []

        def fail_fn(*, portfolio_id: int, trigger_source: str) -> None:
            call_log.append("fail")
            raise RuntimeError("boom")

        registry.register(_make_entry(name="fail_job", job_fn=fail_fn))
        registry.register(
            _make_entry(
                name="ok_job",
                job_fn=lambda *, portfolio_id, trigger_source: call_log.append("ok"),
            )
        )
        engine = SchedulerEngine(registry)
        results = engine.run_all_for_frequency(
            JobFrequency.DAILY,
            portfolio_id=1,
            trigger_source=TriggerSource.SCHEDULED,
        )
        assert len(results) == 2
        statuses = [r.status for r in results]
        assert JobStatus.FAILED in statuses
        assert JobStatus.COMPLETED in statuses
        assert set(call_log) == {"fail", "ok"}

    def test_run_all_empty_frequency_returns_empty(self) -> None:
        registry = SchedulerRegistry()
        engine = SchedulerEngine(registry)
        results = engine.run_all_for_frequency(
            JobFrequency.MONTHLY,
            portfolio_id=1,
        )
        assert len(results) == 0


class TestSchedulerEngineEventPersistence:
    def test_persist_event_called_on_success(self) -> None:
        registry = SchedulerRegistry()
        registry.register(_make_entry())
        persisted: list[dict[str, Any]] = []

        class FakeEventRepo:
            def append(self, **kwargs: Any) -> None:
                persisted.append(kwargs)

        engine = SchedulerEngine(registry, system_event_log_repo=FakeEventRepo())
        result = engine.run_job(
            "test_job",
            JobFrequency.DAILY,
            portfolio_id=1,
        )
        assert result.status == JobStatus.COMPLETED
        assert len(persisted) == 1
        assert persisted[0]["event_type"] == "scheduler_completed"
        assert persisted[0]["run_id"] == result.run_id

    def test_persist_event_called_on_failure(self) -> None:
        registry = SchedulerRegistry()

        def fail_fn(*, portfolio_id: int, trigger_source: str) -> None:
            raise ValueError("test error")

        registry.register(_make_entry(job_fn=fail_fn))
        persisted: list[dict[str, Any]] = []

        class FakeEventRepo:
            def append(self, **kwargs: Any) -> None:
                persisted.append(kwargs)

        engine = SchedulerEngine(registry, system_event_log_repo=FakeEventRepo())
        result = engine.run_job(
            "test_job",
            JobFrequency.DAILY,
            portfolio_id=1,
        )
        assert result.status == JobStatus.FAILED
        assert len(persisted) == 1
        assert persisted[0]["event_type"] == "scheduler_failed"

    def test_persist_failure_does_not_suppress_result(self) -> None:
        registry = SchedulerRegistry()
        registry.register(_make_entry())

        class BrokenEventRepo:
            def append(self, **kwargs: Any) -> None:
                raise RuntimeError("repo broken")

        engine = SchedulerEngine(registry, system_event_log_repo=BrokenEventRepo())
        result = engine.run_job(
            "test_job",
            JobFrequency.DAILY,
            portfolio_id=1,
        )
        assert result.status == JobStatus.COMPLETED


class TestSchedulerLogger:
    def test_build_event_payload_completed(self) -> None:
        logger = SchedulerLogger()
        result = _make_completed_result()
        payload = logger.build_event_payload(result)
        assert payload["entry_name"] == "test_job"
        assert payload["status"] == "completed"
        assert payload["error_message"] is None

    def test_build_event_payload_failed(self) -> None:
        logger = SchedulerLogger()
        result = _make_failed_result()
        payload = logger.build_event_payload(result)
        assert payload["status"] == "failed"
        assert payload["error_message"] is not None


def _make_completed_result() -> Any:
    from fund_manager.scheduler.types import JobResult

    now = datetime(2026, 4, 3, 12, 0, 0)
    return JobResult(
        entry_name="test_job",
        frequency=JobFrequency.DAILY,
        status=JobStatus.COMPLETED,
        run_id="scheduler-test_job-abc12345",
        started_at=now,
        finished_at=now,
        portfolio_id=1,
        trigger_source="manual",
    )


def _make_failed_result() -> Any:
    from fund_manager.scheduler.types import JobResult

    now = datetime(2026, 4, 3, 12, 0, 0)
    return JobResult(
        entry_name="test_job",
        frequency=JobFrequency.DAILY,
        status=JobStatus.FAILED,
        run_id="scheduler-test_job-abc12345",
        started_at=now,
        finished_at=now,
        portfolio_id=1,
        trigger_source="manual",
        error_message="RuntimeError: test failure",
    )
