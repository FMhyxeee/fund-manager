"""Deterministic service wrappers around core portfolio metrics."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from fund_manager.core.domain.metrics import (
    ACCOUNTING_ASSUMPTIONS_NOTE,
    MissingNavError,
    PortfolioValuePoint,
    PositionValuationInput,
    current_value,
    daily_return,
    max_drawdown,
    period_return,
    quantize_money,
    unrealized_pnl,
    weight,
)


@dataclass(frozen=True)
class PositionMetrics:
    """Computed metrics for one position."""

    fund_code: str
    units: Decimal
    total_cost_amount: Decimal
    nav_per_unit: Decimal | None
    current_value_amount: Decimal | None
    unrealized_pnl_amount: Decimal | None
    weight_ratio: Decimal | None
    missing_nav: bool


@dataclass(frozen=True)
class PortfolioMetrics:
    """Computed portfolio-level metrics and supporting position breakdown."""

    total_cost_amount: Decimal
    total_market_value_amount: Decimal | None
    unrealized_pnl_amount: Decimal | None
    daily_return_ratio: Decimal | None
    period_return_ratio: Decimal | None
    max_drawdown_ratio: Decimal | None
    missing_nav_fund_codes: tuple[str, ...]
    position_metrics: tuple[PositionMetrics, ...]
    accounting_assumptions_note: str = ACCOUNTING_ASSUMPTIONS_NOTE


class AnalyticsService:
    """Compose pure metric functions into position and portfolio summaries."""

    def compute_position_metrics(
        self,
        positions: Sequence[PositionValuationInput],
    ) -> tuple[PositionMetrics, ...]:
        """Value each position and compute weights when all NAVs are present."""
        preliminary_metrics: list[PositionMetrics] = []
        missing_nav_fund_codes: list[str] = []

        for position in positions:
            position_current_value = self._try_current_value(position)
            position_unrealized_pnl = (
                None
                if position_current_value is None
                else unrealized_pnl(position.total_cost_amount, position_current_value)
            )
            missing_nav = position_current_value is None and position.units != Decimal("0")
            if missing_nav:
                missing_nav_fund_codes.append(position.fund_code)

            preliminary_metrics.append(
                PositionMetrics(
                    fund_code=position.fund_code,
                    units=position.units,
                    total_cost_amount=position.total_cost_amount,
                    nav_per_unit=position.nav_per_unit,
                    current_value_amount=position_current_value,
                    unrealized_pnl_amount=position_unrealized_pnl,
                    weight_ratio=None,
                    missing_nav=missing_nav,
                )
            )

        if missing_nav_fund_codes:
            return tuple(preliminary_metrics)

        total_market_value_amount = quantize_money(
            sum(
                (
                    metric.current_value_amount
                    for metric in preliminary_metrics
                    if metric.current_value_amount is not None
                ),
                start=Decimal("0"),
            )
        )

        return tuple(
            PositionMetrics(
                fund_code=metric.fund_code,
                units=metric.units,
                total_cost_amount=metric.total_cost_amount,
                nav_per_unit=metric.nav_per_unit,
                current_value_amount=metric.current_value_amount,
                unrealized_pnl_amount=metric.unrealized_pnl_amount,
                weight_ratio=weight(
                    metric.current_value_amount or Decimal("0"),
                    total_market_value_amount,
                ),
                missing_nav=metric.missing_nav,
            )
            for metric in preliminary_metrics
        )

    def compute_portfolio_metrics(
        self,
        positions: Sequence[PositionValuationInput],
        *,
        valuation_history: Sequence[PortfolioValuePoint] = (),
    ) -> PortfolioMetrics:
        """Compute portfolio aggregates and time-series metrics."""
        position_metrics = self.compute_position_metrics(positions)
        missing_nav_fund_codes = tuple(
            metric.fund_code for metric in position_metrics if metric.missing_nav
        )
        total_cost_amount = quantize_money(
            sum((position.total_cost_amount for position in positions), start=Decimal("0"))
        )

        total_market_value_amount: Decimal | None
        unrealized_pnl_amount: Decimal | None
        if missing_nav_fund_codes:
            total_market_value_amount = None
            unrealized_pnl_amount = None
        else:
            total_market_value_amount = quantize_money(
                sum(
                    (
                        metric.current_value_amount
                        for metric in position_metrics
                        if metric.current_value_amount is not None
                    ),
                    start=Decimal("0"),
                )
            )
            unrealized_pnl_amount = quantize_money(
                sum(
                    (
                        metric.unrealized_pnl_amount
                        for metric in position_metrics
                        if metric.unrealized_pnl_amount is not None
                    ),
                    start=Decimal("0"),
                )
            )

        return PortfolioMetrics(
            total_cost_amount=total_cost_amount,
            total_market_value_amount=total_market_value_amount,
            unrealized_pnl_amount=unrealized_pnl_amount,
            daily_return_ratio=daily_return(valuation_history),
            period_return_ratio=period_return(valuation_history),
            max_drawdown_ratio=max_drawdown(valuation_history),
            missing_nav_fund_codes=missing_nav_fund_codes,
            position_metrics=position_metrics,
        )

    def _try_current_value(self, position: PositionValuationInput) -> Decimal | None:
        try:
            return current_value(
                position.units,
                position.nav_per_unit,
                fund_code=position.fund_code,
            )
        except MissingNavError:
            if position.units == Decimal("0"):
                raise
            return None


__all__ = [
    "AnalyticsService",
    "PortfolioMetrics",
    "PositionMetrics",
]
