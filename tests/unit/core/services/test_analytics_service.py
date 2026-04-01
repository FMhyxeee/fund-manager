"""Unit tests for the deterministic analytics service."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fund_manager.core.domain.metrics import PortfolioValuePoint, PositionValuationInput
from fund_manager.core.services.analytics_service import AnalyticsService


def test_compute_position_metrics_with_complete_navs_computes_weights() -> None:
    service = AnalyticsService()

    result = service.compute_position_metrics(
        [
            PositionValuationInput(
                fund_code="000001",
                units=Decimal("10.000000"),
                total_cost_amount=Decimal("10.0000"),
                nav_per_unit=Decimal("1.50000000"),
            ),
            PositionValuationInput(
                fund_code="000002",
                units=Decimal("5.000000"),
                total_cost_amount=Decimal("12.0000"),
                nav_per_unit=Decimal("2.00000000"),
            ),
        ]
    )

    assert result[0].current_value_amount == Decimal("15.0000")
    assert result[0].unrealized_pnl_amount == Decimal("5.0000")
    assert result[0].weight_ratio == Decimal("0.600000")
    assert result[0].missing_nav is False
    assert result[1].current_value_amount == Decimal("10.0000")
    assert result[1].unrealized_pnl_amount == Decimal("-2.0000")
    assert result[1].weight_ratio == Decimal("0.400000")
    assert result[1].missing_nav is False


def test_compute_position_metrics_surfaces_missing_nav_and_withholds_weights() -> None:
    service = AnalyticsService()

    result = service.compute_position_metrics(
        [
            PositionValuationInput(
                fund_code="000001",
                units=Decimal("10.000000"),
                total_cost_amount=Decimal("10.0000"),
                nav_per_unit=Decimal("1.50000000"),
            ),
            PositionValuationInput(
                fund_code="000002",
                units=Decimal("5.000000"),
                total_cost_amount=Decimal("12.0000"),
                nav_per_unit=None,
            ),
        ]
    )

    assert result[0].current_value_amount == Decimal("15.0000")
    assert result[0].weight_ratio is None
    assert result[1].current_value_amount is None
    assert result[1].unrealized_pnl_amount is None
    assert result[1].weight_ratio is None
    assert result[1].missing_nav is True


def test_compute_portfolio_metrics_aggregates_positions_and_time_series() -> None:
    service = AnalyticsService()

    result = service.compute_portfolio_metrics(
        [
            PositionValuationInput(
                fund_code="000001",
                units=Decimal("10.000000"),
                total_cost_amount=Decimal("10.0000"),
                nav_per_unit=Decimal("1.50000000"),
            ),
            PositionValuationInput(
                fund_code="000002",
                units=Decimal("5.000000"),
                total_cost_amount=Decimal("12.0000"),
                nav_per_unit=Decimal("2.00000000"),
            ),
        ],
        valuation_history=[
            PortfolioValuePoint(date(2026, 3, 1), Decimal("20.0000")),
            PortfolioValuePoint(date(2026, 3, 2), Decimal("22.0000")),
            PortfolioValuePoint(date(2026, 3, 3), Decimal("25.0000")),
        ],
    )

    assert result.total_cost_amount == Decimal("22.0000")
    assert result.total_market_value_amount == Decimal("25.0000")
    assert result.unrealized_pnl_amount == Decimal("3.0000")
    assert result.daily_return_ratio == Decimal("0.136364")
    assert result.period_return_ratio == Decimal("0.250000")
    assert result.max_drawdown_ratio == Decimal("0.000000")
    assert result.missing_nav_fund_codes == ()
    assert "simple holding-period returns" in result.accounting_assumptions_note


def test_compute_portfolio_metrics_with_missing_nav_marks_portfolio_incomplete() -> None:
    service = AnalyticsService()

    result = service.compute_portfolio_metrics(
        [
            PositionValuationInput(
                fund_code="000001",
                units=Decimal("10.000000"),
                total_cost_amount=Decimal("10.0000"),
                nav_per_unit=Decimal("1.50000000"),
            ),
            PositionValuationInput(
                fund_code="000002",
                units=Decimal("1.000000"),
                total_cost_amount=Decimal("2.0000"),
                nav_per_unit=None,
            ),
        ]
    )

    assert result.total_cost_amount == Decimal("12.0000")
    assert result.total_market_value_amount is None
    assert result.unrealized_pnl_amount is None
    assert result.daily_return_ratio is None
    assert result.period_return_ratio is None
    assert result.max_drawdown_ratio is None
    assert result.missing_nav_fund_codes == ("000002",)
