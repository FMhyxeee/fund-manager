"""Unit tests for the scheduler registry."""

from __future__ import annotations

import pytest

from fund_manager.scheduler.registry import SchedulerRegistry
from fund_manager.scheduler.types import JobFrequency, ScheduleEntry


def _make_entry(
    name: str = "test_job",
    frequency: JobFrequency = JobFrequency.DAILY,
) -> ScheduleEntry:
    return ScheduleEntry(
        name=name,
        frequency=frequency,
        job_fn=lambda *, portfolio_id, trigger_source: None,
        description="Test job.",
    )


class TestSchedulerRegistryRegister:
    def test_register_single_entry(self) -> None:
        registry = SchedulerRegistry()
        entry = _make_entry()
        registry.register(entry)
        assert registry.has("test_job", JobFrequency.DAILY)

    def test_register_multiple_entries(self) -> None:
        registry = SchedulerRegistry()
        daily = _make_entry(name="daily_job", frequency=JobFrequency.DAILY)
        weekly = _make_entry(name="weekly_job", frequency=JobFrequency.WEEKLY)
        monthly = _make_entry(name="monthly_job", frequency=JobFrequency.MONTHLY)
        registry.register(daily)
        registry.register(weekly)
        registry.register(monthly)
        assert len(registry.list_all()) == 3

    def test_register_duplicate_raises(self) -> None:
        registry = SchedulerRegistry()
        entry = _make_entry()
        registry.register(entry)
        with pytest.raises(ValueError, match="already registered"):
            registry.register(entry)


class TestSchedulerRegistryGet:
    def test_get_existing_entry(self) -> None:
        registry = SchedulerRegistry()
        entry = _make_entry()
        registry.register(entry)
        assert registry.get("test_job", JobFrequency.DAILY) is entry

    def test_get_missing_entry_raises(self) -> None:
        registry = SchedulerRegistry()
        with pytest.raises(KeyError, match="not registered"):
            registry.get("missing", JobFrequency.DAILY)


class TestSchedulerRegistryListByFrequency:
    def test_list_by_frequency_returns_matching(self) -> None:
        registry = SchedulerRegistry()
        daily_a = _make_entry(name="daily_a", frequency=JobFrequency.DAILY)
        daily_b = _make_entry(name="daily_b", frequency=JobFrequency.DAILY)
        weekly = _make_entry(name="weekly", frequency=JobFrequency.WEEKLY)
        registry.register(daily_a)
        registry.register(daily_b)
        registry.register(weekly)
        daily_entries = registry.list_by_frequency(JobFrequency.DAILY)
        assert len(daily_entries) == 2
        names = {e.name for e in daily_entries}
        assert names == {"daily_a", "daily_b"}

    def test_list_by_frequency_empty(self) -> None:
        registry = SchedulerRegistry()
        assert len(registry.list_by_frequency(JobFrequency.MONTHLY)) == 0


class TestSchedulerRegistryRemove:
    def test_remove_existing(self) -> None:
        registry = SchedulerRegistry()
        entry = _make_entry()
        registry.register(entry)
        registry.remove("test_job", JobFrequency.DAILY)
        assert not registry.has("test_job", JobFrequency.DAILY)

    def test_remove_missing_raises(self) -> None:
        registry = SchedulerRegistry()
        with pytest.raises(KeyError, match="not registered"):
            registry.remove("missing", JobFrequency.DAILY)


class TestSchedulerRegistryClear:
    def test_clear_removes_all(self) -> None:
        registry = SchedulerRegistry()
        registry.register(_make_entry(name="a"))
        registry.register(_make_entry(name="b", frequency=JobFrequency.WEEKLY))
        assert len(registry.list_all()) == 2
        registry.clear()
        assert len(registry.list_all()) == 0


class TestScheduleEntryEquality:
    def test_same_name_and_frequency_are_equal(self) -> None:
        a = _make_entry(name="x", frequency=JobFrequency.WEEKLY)
        b = _make_entry(name="x", frequency=JobFrequency.WEEKLY)
        assert a == b
        assert hash(a) == hash(b)

    def test_different_name_are_not_equal(self) -> None:
        a = _make_entry(name="x")
        b = _make_entry(name="y")
        assert a != b

    def test_different_frequency_are_not_equal(self) -> None:
        a = _make_entry(frequency=JobFrequency.DAILY)
        b = _make_entry(frequency=JobFrequency.WEEKLY)
        assert a != b
