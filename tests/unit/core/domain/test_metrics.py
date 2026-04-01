"""Unit tests for deterministic portfolio metrics."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from fund_manager.core.domain.metrics import (
    InvalidMetricInputError,
    InvalidTimeSeriesError,
    MissingNavError,
    PortfolioValuePoint,
    current_value,
    daily_return,
    max_drawdown,
    period_return,
    unrealized_pnl,
    weight,
)


def test_current_value_quantizes_money_with_nav() -> None:
    result = current_value(
        Decimal("10.123456"),
        Decimal("1.23456789"),
        fund_code="000001",
    )

    assert result == Decimal("12.4981")


def test_current_value_returns_zero_for_zero_units_without_nav() -> None:
    assert current_value(Decimal("0"), None, fund_code="000001") == Decimal("0.0000")


def test_current_value_requires_nav_for_non_zero_holdings() -> None:
    with pytest.raises(MissingNavError) as exc_info:
        current_value(Decimal("1.000000"), None, fund_code="000001")

    assert "fund '000001'" in str(exc_info.value)


def test_unrealized_pnl_subtracts_total_cost_from_market_value() -> None:
    assert unrealized_pnl(Decimal("100.0000"), Decimal("110.1234")) == Decimal("10.1234")


def test_weight_returns_zero_only_for_empty_position_in_empty_portfolio() -> None:
    assert weight(Decimal("0.0000"), Decimal("0.0000")) == Decimal("0.000000")

    with pytest.raises(InvalidMetricInputError):
        weight(Decimal("1.0000"), Decimal("0.0000"))


def test_daily_return_uses_two_most_recent_points() -> None:
    points = [
        PortfolioValuePoint(date(2026, 3, 1), Decimal("100.0000")),
        PortfolioValuePoint(date(2026, 3, 2), Decimal("110.0000")),
        PortfolioValuePoint(date(2026, 3, 3), Decimal("121.0000")),
    ]

    assert daily_return(points) == Decimal("0.100000")


def test_period_return_returns_none_for_insufficient_history_or_zero_start() -> None:
    single_point = [PortfolioValuePoint(date(2026, 3, 1), Decimal("100.0000"))]
    zero_start = [
        PortfolioValuePoint(date(2026, 3, 1), Decimal("0.0000")),
        PortfolioValuePoint(date(2026, 3, 2), Decimal("10.0000")),
    ]

    assert period_return(single_point) is None
    assert period_return(zero_start) is None


def test_series_metrics_require_strictly_increasing_dates() -> None:
    unordered_points = [
        PortfolioValuePoint(date(2026, 3, 2), Decimal("100.0000")),
        PortfolioValuePoint(date(2026, 3, 1), Decimal("101.0000")),
    ]
    duplicate_day_points = [
        PortfolioValuePoint(date(2026, 3, 1), Decimal("100.0000")),
        PortfolioValuePoint(date(2026, 3, 1), Decimal("101.0000")),
    ]

    with pytest.raises(InvalidTimeSeriesError):
        daily_return(unordered_points)

    with pytest.raises(InvalidTimeSeriesError):
        max_drawdown(duplicate_day_points)


def test_max_drawdown_tracks_worst_peak_to_trough_loss() -> None:
    points = [
        PortfolioValuePoint(date(2026, 3, 1), Decimal("100.0000")),
        PortfolioValuePoint(date(2026, 3, 2), Decimal("120.0000")),
        PortfolioValuePoint(date(2026, 3, 3), Decimal("90.0000")),
        PortfolioValuePoint(date(2026, 3, 4), Decimal("95.0000")),
        PortfolioValuePoint(date(2026, 3, 5), Decimal("80.0000")),
        PortfolioValuePoint(date(2026, 3, 6), Decimal("130.0000")),
    ]

    assert max_drawdown(points) == Decimal("-0.333333")


def test_max_drawdown_returns_zero_for_empty_or_non_declining_series() -> None:
    rising_points = [
        PortfolioValuePoint(date(2026, 3, 1), Decimal("0.0000")),
        PortfolioValuePoint(date(2026, 3, 2), Decimal("10.0000")),
        PortfolioValuePoint(date(2026, 3, 3), Decimal("12.0000")),
    ]

    assert max_drawdown([]) is None
    assert max_drawdown(rising_points) == Decimal("0.000000")
