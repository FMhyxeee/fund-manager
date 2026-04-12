"""Read-oriented service layer for exposing fund-manager capabilities via MCP."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_manager.core.domain.decimal_constants import AMOUNT_QUANTIZER, RATIO_QUANTIZER, ZERO
from fund_manager.core.serialization import serialize_for_json
from fund_manager.core.domain.metrics import PortfolioValuePoint
from fund_manager.core.services import AnalyticsService, PortfolioReadService
from fund_manager.storage.models import FundMaster, NavSnapshot
from fund_manager.storage.repo import FundMasterRepository

RebalanceMode = Literal["none", "monthly"]


@dataclass(frozen=True)
class ModelAllocation:
    """One model-portfolio allocation input."""

    fund_code: str
    weight: Decimal


class FundManagerMCPService:
    """Composable MCP-oriented facade over deterministic fund-manager services."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._portfolio_read_service = PortfolioReadService(session)
        self._fund_repo = FundMasterRepository(session)
        self._analytics_service = AnalyticsService()

    def list_portfolios(self) -> dict[str, Any]:
        """List portfolios in stable display order."""
        portfolios = self._portfolio_read_service.list_portfolios()
        return {"portfolios": serialize_for_json(portfolios)}

    def get_portfolio_snapshot(
        self,
        *,
        as_of_date: date,
        portfolio_id: int | None = None,
        portfolio_name: str | None = None,
    ) -> dict[str, Any]:
        """Return a JSON-safe portfolio snapshot."""
        result = self._portfolio_read_service.get_portfolio_snapshot(
            as_of_date=as_of_date,
            portfolio_id=portfolio_id,
            portfolio_name=portfolio_name,
        )
        return {
            "portfolio": serialize_for_json(result.portfolio),
            "snapshot": serialize_for_json(result.snapshot.to_dict()),
        }

    def get_position_breakdown(
        self,
        *,
        as_of_date: date,
        portfolio_id: int | None = None,
        portfolio_name: str | None = None,
    ) -> dict[str, Any]:
        """Return only the position breakdown for one portfolio."""
        result = self._portfolio_read_service.get_position_breakdown(
            as_of_date=as_of_date,
            portfolio_id=portfolio_id,
            portfolio_name=portfolio_name,
        )
        return {
            "portfolio": serialize_for_json(result.portfolio),
            "as_of_date": result.as_of_date.isoformat(),
            "positions": serialize_for_json(result.positions),
        }

    def get_fund_profile(self, *, fund_code: str) -> dict[str, Any]:
        """Return one fund master record as a JSON-safe payload."""
        fund = self._fund_repo.get_by_code(fund_code)
        if fund is None:
            msg = f"Fund '{fund_code}' was not found."
            raise ValueError(msg)
        return {"fund": serialize_for_json(_serialize_fund(fund))}

    def get_fund_nav_history(
        self,
        *,
        fund_code: str,
        start_date: date,
        end_date: date,
    ) -> dict[str, Any]:
        """Return normalized NAV history for one fund."""
        fund = self._fund_repo.get_by_code(fund_code)
        if fund is None:
            msg = f"Fund '{fund_code}' was not found."
            raise ValueError(msg)

        nav_rows = self._session.execute(
            select(NavSnapshot)
            .where(
                NavSnapshot.fund_id == fund.id,
                NavSnapshot.nav_date >= start_date,
                NavSnapshot.nav_date <= end_date,
            )
            .order_by(NavSnapshot.nav_date.asc(), NavSnapshot.id.asc())
        ).scalars().all()
        return {
            "fund": serialize_for_json(_serialize_fund(fund)),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "points": serialize_for_json(
                [
                    {
                        "nav_date": nav.nav_date,
                        "unit_nav_amount": nav.unit_nav_amount,
                        "accumulated_nav_amount": nav.accumulated_nav_amount,
                        "daily_return_ratio": nav.daily_return_ratio,
                        "source_name": nav.source_name,
                    }
                    for nav in nav_rows
                ]
            ),
        }

    def get_portfolio_valuation_history(
        self,
        *,
        end_date: date,
        start_date: date | None = None,
        portfolio_id: int | None = None,
        portfolio_name: str | None = None,
    ) -> dict[str, Any]:
        """Return valuation history assembled from canonical lots and NAV snapshots."""
        snapshot_result = self._portfolio_read_service.get_portfolio_snapshot(
            as_of_date=end_date,
            portfolio_id=portfolio_id,
            portfolio_name=portfolio_name,
        )
        snapshot_payload = serialize_for_json(snapshot_result.snapshot.to_dict())
        valuation_history = snapshot_payload["valuation_history"]
        if start_date is not None:
            valuation_history = [
                point
                for point in valuation_history
                if point["as_of_date"] >= start_date.isoformat()
            ]
        return {
            "portfolio": serialize_for_json(snapshot_result.portfolio),
            "start_date": start_date.isoformat() if start_date is not None else None,
            "end_date": end_date.isoformat(),
            "valuation_history": valuation_history,
        }

    def get_portfolio_metrics(
        self,
        *,
        as_of_date: date,
        portfolio_id: int | None = None,
        portfolio_name: str | None = None,
    ) -> dict[str, Any]:
        """Return a compact metrics summary derived from one portfolio snapshot."""
        snapshot_result = self._portfolio_read_service.get_portfolio_snapshot(
            as_of_date=as_of_date,
            portfolio_id=portfolio_id,
            portfolio_name=portfolio_name,
        )
        snapshot = serialize_for_json(snapshot_result.snapshot.to_dict())
        positions = snapshot["positions"]
        top_positions = sorted(
            positions,
            key=lambda position: Decimal(position["current_value_amount"] or str(ZERO)),
            reverse=True,
        )[:5]
        return {
            "portfolio": serialize_for_json(snapshot_result.portfolio),
            "as_of_date": as_of_date.isoformat(),
            "metrics": {
                "position_count": snapshot["position_count"],
                "total_cost_amount": snapshot["total_cost_amount"],
                "total_market_value_amount": snapshot["total_market_value_amount"],
                "unrealized_pnl_amount": snapshot["unrealized_pnl_amount"],
                "daily_return_ratio": snapshot["daily_return_ratio"],
                "weekly_return_ratio": snapshot["weekly_return_ratio"],
                "monthly_return_ratio": snapshot["monthly_return_ratio"],
                "period_return_ratio": snapshot["period_return_ratio"],
                "max_drawdown_ratio": snapshot["max_drawdown_ratio"],
                "missing_nav_fund_codes": snapshot["missing_nav_fund_codes"],
                "top_positions": top_positions,
            },
        }

    def simulate_model_portfolio(
        self,
        *,
        allocations: Sequence[ModelAllocation],
        start_date: date,
        end_date: date,
        rebalance: RebalanceMode = "none",
    ) -> dict[str, Any]:
        """Backtest a simple model portfolio from normalized fund weights."""
        if rebalance not in {"none", "monthly"}:
            msg = "rebalance must be one of: none, monthly."
            raise ValueError(msg)
        normalized_allocations = _normalize_allocations(allocations)
        funds = self._resolve_funds(normalized_allocations)
        nav_histories = {
            fund.fund_code: self._load_nav_history_for_fund(
                fund.id,
                start_date=start_date,
                end_date=end_date,
            )
            for fund in funds
        }
        candidate_dates = sorted(
            {
                nav_date
                for history in nav_histories.values()
                for nav_date in history
            }
        )
        if not candidate_dates:
            msg = "No NAV history is available for the requested date range."
            raise ValueError(msg)

        latest_navs: dict[str, Decimal] = {}
        units_by_fund_code: dict[str, Decimal] | None = None
        valuation_history: list[PortfolioValuePoint] = []
        last_rebalance_month: tuple[int, int] | None = None

        for candidate_date in candidate_dates:
            for fund_code, history in nav_histories.items():
                nav = history.get(candidate_date)
                if nav is not None:
                    latest_navs[fund_code] = nav
            if len(latest_navs) != len(normalized_allocations):
                continue

            if units_by_fund_code is None:
                units_by_fund_code = {
                    allocation.fund_code: allocation.weight / latest_navs[allocation.fund_code]
                    for allocation in normalized_allocations
                }
                last_rebalance_month = (candidate_date.year, candidate_date.month)
            elif rebalance == "monthly":
                rebalance_month = (candidate_date.year, candidate_date.month)
                if rebalance_month != last_rebalance_month:
                    total_value = sum(
                        units_by_fund_code[fund_code] * latest_navs[fund_code]
                        for fund_code in units_by_fund_code
                    )
                    units_by_fund_code = {
                        allocation.fund_code: (
                            total_value * allocation.weight / latest_navs[allocation.fund_code]
                        )
                        for allocation in normalized_allocations
                    }
                    last_rebalance_month = rebalance_month

            assert units_by_fund_code is not None
            total_value = sum(
                units_by_fund_code[fund_code] * latest_navs[fund_code]
                for fund_code in units_by_fund_code
            )
            valuation_history.append(
                PortfolioValuePoint(
                    as_of_date=candidate_date,
                    market_value_amount=_quantize_decimal(total_value),
                )
            )

        if not valuation_history:
            msg = "No complete valuation history could be assembled for the requested funds."
            raise ValueError(msg)

        performance_metrics = self._analytics_service.compute_performance_metrics(
            valuation_history,
            as_of_date=valuation_history[-1].as_of_date,
        )
        return {
            "allocations": serialize_for_json(normalized_allocations),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "rebalance": rebalance,
            "valuation_history": serialize_for_json(valuation_history),
            "metrics": serialize_for_json(performance_metrics),
        }

    def _resolve_funds(self, allocations: Sequence[ModelAllocation]) -> list[FundMaster]:
        funds: list[FundMaster] = []
        for allocation in allocations:
            fund = self._fund_repo.get_by_code(allocation.fund_code)
            if fund is None:
                msg = f"Fund '{allocation.fund_code}' was not found."
                raise ValueError(msg)
            funds.append(fund)
        return funds

    def _load_nav_history_for_fund(
        self,
        fund_id: int,
        *,
        start_date: date,
        end_date: date,
    ) -> dict[date, Decimal]:
        nav_rows = self._session.execute(
            select(NavSnapshot.nav_date, NavSnapshot.unit_nav_amount)
            .where(
                NavSnapshot.fund_id == fund_id,
                NavSnapshot.nav_date >= start_date,
                NavSnapshot.nav_date <= end_date,
            )
            .order_by(NavSnapshot.nav_date.asc(), NavSnapshot.id.asc())
        ).all()
        return {nav_date: unit_nav_amount for nav_date, unit_nav_amount in nav_rows}


def _serialize_fund(fund: FundMaster) -> dict[str, Any]:
    return {
        "fund_code": fund.fund_code,
        "fund_name": fund.fund_name,
        "fund_type": fund.fund_type,
        "base_currency_code": fund.base_currency_code,
        "company_name": fund.company_name,
        "manager_name": fund.manager_name,
        "risk_level": fund.risk_level,
        "benchmark_name": fund.benchmark_name,
        "fund_status": fund.fund_status,
        "source_name": fund.source_name,
    }


def _normalize_allocations(allocations: Sequence[ModelAllocation]) -> tuple[ModelAllocation, ...]:
    if not allocations:
        msg = "allocations must not be empty."
        raise ValueError(msg)
    total_weight = sum((allocation.weight for allocation in allocations), start=ZERO)
    if total_weight <= ZERO:
        msg = "allocation weights must sum to a positive value."
        raise ValueError(msg)
    return tuple(
        ModelAllocation(
            fund_code=allocation.fund_code,
            weight=(allocation.weight / total_weight).quantize(RATIO_QUANTIZER),
        )
        for allocation in allocations
    )


def _quantize_decimal(value: Decimal) -> Decimal:
    return value.quantize(AMOUNT_QUANTIZER)


__all__ = ["FundManagerMCPService", "ModelAllocation", "RebalanceMode"]
