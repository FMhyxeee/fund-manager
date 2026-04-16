"""Deterministic fact packs prepared by workflows before any agent runtime runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class ReviewPositionFact:
    """Bounded position-level facts prepared by a workflow coordinator."""

    fund_code: str
    fund_name: str
    units: Decimal
    current_value_amount: Decimal | None
    weight_ratio: Decimal | None
    unrealized_pnl_amount: Decimal | None
    missing_nav: bool


@dataclass(frozen=True)
class WeeklyReviewFacts:
    """Structured deterministic facts sent to ReviewAgent for one weekly review run."""

    portfolio_id: int
    portfolio_code: str
    portfolio_name: str
    base_currency_code: str
    period_start: date
    period_end: date
    latest_valuation_date: date | None
    valuation_point_count: int
    position_count: int
    total_cost_amount: Decimal
    total_market_value_amount: Decimal | None
    unrealized_pnl_amount: Decimal | None
    daily_return_ratio: Decimal | None
    period_return_ratio: Decimal | None
    monthly_return_ratio: Decimal | None
    max_drawdown_ratio: Decimal | None
    missing_nav_fund_codes: tuple[str, ...]
    top_weight_positions: tuple[ReviewPositionFact, ...]
    top_gainers: tuple[ReviewPositionFact, ...]
    top_laggards: tuple[ReviewPositionFact, ...]
    accounting_assumptions_note: str


@dataclass(frozen=True)
class StrategyDebateFacts:
    """Structured deterministic evidence sent to strategy debate agents."""

    portfolio_id: int
    portfolio_code: str
    portfolio_name: str
    base_currency_code: str
    period_start: date
    period_end: date
    latest_valuation_date: date | None
    valuation_point_count: int
    position_count: int
    total_cost_amount: Decimal
    total_market_value_amount: Decimal | None
    unrealized_pnl_amount: Decimal | None
    period_return_ratio: Decimal | None
    weekly_return_ratio: Decimal | None
    monthly_return_ratio: Decimal | None
    max_drawdown_ratio: Decimal | None
    missing_nav_fund_codes: tuple[str, ...]
    top_weight_positions: tuple[ReviewPositionFact, ...]
    top_gainers: tuple[ReviewPositionFact, ...]
    top_laggards: tuple[ReviewPositionFact, ...]
    accounting_assumptions_note: str


__all__ = [
    "ReviewPositionFact",
    "StrategyDebateFacts",
    "WeeklyReviewFacts",
]
