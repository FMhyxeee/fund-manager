"""Scheduler registry for registering and looking up scheduled jobs."""

from __future__ import annotations

from collections.abc import Sequence

from fund_manager.scheduler.types import JobFrequency, ScheduleEntry


class SchedulerRegistry:
    """In-memory registry of scheduled jobs.

    Jobs are identified by (name, frequency) pairs. Duplicate registrations
    for the same pair raise an error to prevent silent overwrites.
    """

    def __init__(self) -> None:
        self._entries: dict[tuple[str, JobFrequency], ScheduleEntry] = {}

    def register(self, entry: ScheduleEntry) -> None:
        key = (entry.name, entry.frequency)
        if key in self._entries:
            msg = (
                f"Job {entry.name!r} with frequency {entry.frequency.value!r} "
                f"is already registered."
            )
            raise ValueError(msg)
        self._entries[key] = entry

    def get(self, name: str, frequency: JobFrequency) -> ScheduleEntry:
        key = (name, frequency)
        entry = self._entries.get(key)
        if entry is None:
            msg = f"Job {name!r} with frequency {frequency.value!r} is not registered."
            raise KeyError(msg)
        return entry

    def list_all(self) -> Sequence[ScheduleEntry]:
        return tuple(self._entries.values())

    def list_by_frequency(self, frequency: JobFrequency) -> Sequence[ScheduleEntry]:
        return tuple(entry for entry in self._entries.values() if entry.frequency == frequency)

    def remove(self, name: str, frequency: JobFrequency) -> None:
        key = (name, frequency)
        if key not in self._entries:
            msg = f"Job {name!r} with frequency {frequency.value!r} is not registered."
            raise KeyError(msg)
        del self._entries[key]

    def has(self, name: str, frequency: JobFrequency) -> bool:
        return (name, frequency) in self._entries

    def clear(self) -> None:
        self._entries.clear()
