"""Unit tests for scheduler job factory functions."""

from __future__ import annotations

from datetime import date

from fund_manager.scheduler.jobs import (
    _build_monthly_period_bounds,
    _build_weekly_period_bounds,
)


class TestBuildWeeklyPeriodBounds:
    def test_weekly_bounds(self) -> None:
        period_start, period_end = _build_weekly_period_bounds(date(2026, 3, 15))
        assert period_start == date(2026, 3, 9)
        assert period_end == date(2026, 3, 15)

    def test_weekly_bounds_same_day(self) -> None:
        period_start, period_end = _build_weekly_period_bounds(date(2026, 1, 1))
        assert period_start == date(2025, 12, 26)
        assert period_end == date(2026, 1, 1)


class TestBuildMonthlyPeriodBounds:
    def test_monthly_bounds(self) -> None:
        period_start, period_end = _build_monthly_period_bounds(date(2026, 3, 15))
        assert period_start == date(2026, 3, 1)
        assert period_end == date(2026, 3, 15)

    def test_monthly_bounds_first_day(self) -> None:
        period_start, period_end = _build_monthly_period_bounds(date(2026, 1, 1))
        assert period_start == date(2026, 1, 1)
        assert period_end == date(2026, 1, 1)
