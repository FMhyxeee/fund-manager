"""Deterministic portfolio metrics.

Accounting assumptions:
- Ratios are returned as decimal fractions, so ``0.050000`` means 5.0%.
- Returns are simple holding-period returns and do not adjust for cash flows.
- Max drawdown is reported as a negative peak-to-trough ratio.
- Non-zero holdings require an explicit NAV before market-value-based metrics can
  be computed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from fund_manager.core.domain.decimal_constants import MONEY_QUANTIZER, RATIO_QUANTIZER, ZERO

ACCOUNTING_ASSUMPTIONS_NOTE = (
    "Returns are simple holding-period returns expressed as ratios, max drawdown "
    "is negative from peak to trough, and non-zero holdings require a NAV before "
    "market-value-based metrics can be produced."
)


class MetricsError(ValueError):
    """Base exception for deterministic metric failures."""


class InvalidMetricInputError(MetricsError):
    """Raised when a metric input violates accounting expectations."""


class MissingNavError(MetricsError):
    """Raised when market-value-based metrics are requested without a NAV."""

    def __init__(self, *, fund_code: str | None = None) -> None:
        target = f"fund '{fund_code}'" if fund_code is not None else "position"
        super().__init__(f"Missing NAV for {target}; cannot compute market-value-based metrics.")
        self.fund_code = fund_code


class InvalidTimeSeriesError(MetricsError):
    """Raised when a valuation series is malformed or unordered."""


@dataclass(frozen=True)
class PositionValuationInput:
    """Deterministic inputs for valuing one position."""

    fund_code: str
    units: Decimal
    total_cost_amount: Decimal
    nav_per_unit: Decimal | None


@dataclass(frozen=True)
class PortfolioValuePoint:
    """One dated market value observation for portfolio-level time series metrics."""

    as_of_date: date
    market_value_amount: Decimal


def quantize_money(value: Decimal) -> Decimal:
    """Normalize a money value to storage-facing precision."""
    return value.quantize(MONEY_QUANTIZER, rounding=ROUND_HALF_UP)


def quantize_ratio(value: Decimal) -> Decimal:
    """Normalize a ratio value to storage-facing precision."""
    return value.quantize(RATIO_QUANTIZER, rounding=ROUND_HALF_UP)


def current_value(
    units: Decimal,
    nav_per_unit: Decimal | None,
    *,
    fund_code: str | None = None,
) -> Decimal:
    """Compute the current market value for one position."""
    _require_non_negative(units, field_name="units")
    if units == ZERO:
        return quantize_money(ZERO)
    if nav_per_unit is None:
        raise MissingNavError(fund_code=fund_code)
    _require_non_negative(nav_per_unit, field_name="nav_per_unit")
    return quantize_money(units * nav_per_unit)


def unrealized_pnl(
    total_cost_amount: Decimal,
    current_value_amount: Decimal,
) -> Decimal:
    """Compute unrealized profit and loss from cost and market value."""
    _require_non_negative(total_cost_amount, field_name="total_cost_amount")
    _require_non_negative(current_value_amount, field_name="current_value_amount")
    return quantize_money(current_value_amount - total_cost_amount)


def weight(
    position_value_amount: Decimal,
    portfolio_value_amount: Decimal,
) -> Decimal:
    """Compute a position weight from market value."""
    _require_non_negative(position_value_amount, field_name="position_value_amount")
    _require_non_negative(portfolio_value_amount, field_name="portfolio_value_amount")
    if portfolio_value_amount == ZERO:
        if position_value_amount == ZERO:
            return quantize_ratio(ZERO)
        msg = (
            "Cannot compute weight with a zero portfolio market value and a non-zero "
            "position market value."
        )
        raise InvalidMetricInputError(msg)
    return quantize_ratio(position_value_amount / portfolio_value_amount)


def daily_return(points: Sequence[PortfolioValuePoint]) -> Decimal | None:
    """Compute the return between the two most recent valuation points."""
    validated_points = _validate_time_series(points)
    if len(validated_points) < 2:
        return None
    return _simple_return(
        beginning_value_amount=validated_points[-2].market_value_amount,
        ending_value_amount=validated_points[-1].market_value_amount,
    )


def period_return(points: Sequence[PortfolioValuePoint]) -> Decimal | None:
    """Compute the holding-period return across the provided valuation series."""
    validated_points = _validate_time_series(points)
    if len(validated_points) < 2:
        return None
    return _simple_return(
        beginning_value_amount=validated_points[0].market_value_amount,
        ending_value_amount=validated_points[-1].market_value_amount,
    )


def max_drawdown(points: Sequence[PortfolioValuePoint]) -> Decimal | None:
    """Compute the worst peak-to-trough decline in a valuation series."""
    validated_points = _validate_time_series(points)
    if not validated_points:
        return None

    peak_value = validated_points[0].market_value_amount
    worst_drawdown = ZERO

    for point in validated_points:
        value = point.market_value_amount
        if value > peak_value:
            peak_value = value
            continue
        if peak_value == ZERO:
            continue

        drawdown = (value - peak_value) / peak_value
        if drawdown < worst_drawdown:
            worst_drawdown = drawdown

    return quantize_ratio(worst_drawdown)


def _simple_return(
    *,
    beginning_value_amount: Decimal,
    ending_value_amount: Decimal,
) -> Decimal | None:
    _require_non_negative(beginning_value_amount, field_name="beginning_value_amount")
    _require_non_negative(ending_value_amount, field_name="ending_value_amount")
    if beginning_value_amount == ZERO:
        return None
    return quantize_ratio((ending_value_amount - beginning_value_amount) / beginning_value_amount)


def _validate_time_series(points: Sequence[PortfolioValuePoint]) -> tuple[PortfolioValuePoint, ...]:
    previous_date: date | None = None
    validated_points: list[PortfolioValuePoint] = []

    for point in points:
        _require_non_negative(point.market_value_amount, field_name="market_value_amount")
        if previous_date is not None and point.as_of_date <= previous_date:
            msg = "Portfolio valuation points must be in strictly increasing date order."
            raise InvalidTimeSeriesError(msg)
        validated_points.append(point)
        previous_date = point.as_of_date

    return tuple(validated_points)


def _require_non_negative(value: Decimal, *, field_name: str) -> None:
    if value < ZERO:
        msg = f"{field_name} cannot be negative."
        raise InvalidMetricInputError(msg)


__all__ = [
    "ACCOUNTING_ASSUMPTIONS_NOTE",
    "InvalidMetricInputError",
    "InvalidTimeSeriesError",
    "MetricsError",
    "MissingNavError",
    "PortfolioValuePoint",
    "PositionValuationInput",
    "current_value",
    "daily_return",
    "max_drawdown",
    "period_return",
    "quantize_money",
    "quantize_ratio",
    "unrealized_pnl",
    "weight",
]
