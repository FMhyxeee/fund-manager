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
from fund_manager.core.domain.metrics import PortfolioValuePoint
from fund_manager.core.serialization import serialize_for_json
from fund_manager.core.services import (
    AnalyticsService,
    PolicyService,
    PortfolioReadService,
    TransactionService,
)
from fund_manager.core.watchlist import FundWatchlistService
from fund_manager.storage.models import (
    DecisionFeedback,
    DecisionRun,
    FundMaster,
    NavSnapshot,
    ReviewReport,
)
from fund_manager.storage.repo import (
    DecisionFeedbackRepository,
    DecisionRunRepository,
    FundMasterRepository,
    ReviewReportRepository,
)

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
        self._decision_run_repo = DecisionRunRepository(session)
        self._decision_feedback_repo = DecisionFeedbackRepository(session)
        self._review_report_repo = ReviewReportRepository(session)
        self._policy_service = PolicyService(session)
        self._analytics_service = AnalyticsService()
        self._watchlist_service = FundWatchlistService(session)
        self._transaction_service = TransactionService(session)

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

    def get_active_policy(
        self,
        *,
        as_of_date: date,
        portfolio_id: int | None = None,
        portfolio_name: str | None = None,
    ) -> dict[str, Any]:
        """Return the active policy for one portfolio on one date."""
        portfolio = self._portfolio_read_service.resolve_portfolio_summary(
            portfolio_id=portfolio_id,
            portfolio_name=portfolio_name,
        )
        policy = self._policy_service.get_active_policy(
            portfolio_id=portfolio.portfolio_id,
            as_of_date=as_of_date,
        )
        if policy is None:
            msg = "Active policy not found."
            raise ValueError(msg)
        return {
            "portfolio": serialize_for_json(portfolio),
            "as_of_date": as_of_date.isoformat(),
            "policy": serialize_for_json(policy),
        }

    def list_decision_runs(
        self,
        *,
        portfolio_id: int | None = None,
        portfolio_name: str | None = None,
        decision_date: date | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """List recent decision runs, optionally scoped to one portfolio."""
        resolved_portfolio = None
        resolved_portfolio_id = portfolio_id
        if portfolio_id is not None or portfolio_name is not None:
            resolved_portfolio = self._portfolio_read_service.resolve_portfolio_summary(
                portfolio_id=portfolio_id,
                portfolio_name=portfolio_name,
            )
            resolved_portfolio_id = resolved_portfolio.portfolio_id

        decision_runs = self._decision_run_repo.list_recent(
            portfolio_id=resolved_portfolio_id,
            decision_date=decision_date,
            limit=limit,
        )
        return {
            "portfolio": (
                serialize_for_json(resolved_portfolio)
                if resolved_portfolio is not None
                else None
            ),
            "decision_date": decision_date.isoformat() if decision_date is not None else None,
            "limit": limit,
            "decision_runs": [
                _build_decision_run_summary_payload(decision_run) for decision_run in decision_runs
            ],
        }

    def get_decision_run(
        self,
        *,
        decision_run_id: int,
    ) -> dict[str, Any]:
        """Return one persisted decision run in detail form."""
        decision_run = self._decision_run_repo.get_detail_by_id(decision_run_id)
        if decision_run is None:
            msg = "Decision run not found."
            raise ValueError(msg)
        return {"decision_run": _build_decision_run_detail_payload(decision_run)}

    def list_decision_feedback(
        self,
        *,
        decision_run_id: int,
    ) -> dict[str, Any]:
        """Return append-only feedback history for one persisted decision run."""
        decision_run = self._decision_run_repo.get_by_id(decision_run_id)
        if decision_run is None:
            msg = "Decision run not found."
            raise ValueError(msg)
        feedback_entries = self._decision_feedback_repo.list_for_decision_run(decision_run_id)
        return {
            "decision_run_id": decision_run_id,
            "feedback_entries": [
                _build_decision_feedback_payload(feedback) for feedback in feedback_entries
            ],
        }

    def get_review_report(
        self,
        *,
        report_id: int,
    ) -> dict[str, Any]:
        """Return one persisted weekly review report."""
        review_report = self._review_report_repo.get_by_id(report_id)
        if review_report is None:
            msg = "Review report not found."
            raise ValueError(msg)
        return {"review_report": _build_review_report_payload(review_report)}

    def list_transactions(
        self,
        *,
        portfolio_id: int | None = None,
        portfolio_name: str | None = None,
        fund_code: str | None = None,
        trade_type: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Return authoritative transaction records for OpenClaw queries."""
        transactions = self._transaction_service.list_transactions(
            portfolio_id=portfolio_id,
            portfolio_name=portfolio_name,
            fund_code=fund_code,
            trade_type=trade_type,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
        )
        return {
            "filters": {
                "portfolio_id": portfolio_id,
                "portfolio_name": portfolio_name,
                "fund_code": fund_code,
                "trade_type": trade_type,
                "start_date": start_date.isoformat() if start_date is not None else None,
                "end_date": end_date.isoformat() if end_date is not None else None,
                "limit": limit,
            },
            "transactions": serialize_for_json(transactions),
        }

    def get_transaction(
        self,
        *,
        transaction_id: int,
    ) -> dict[str, Any]:
        """Return one authoritative transaction record."""
        transaction = self._transaction_service.get_transaction(transaction_id=transaction_id)
        return {"transaction": serialize_for_json(transaction)}

    def append_transaction(
        self,
        *,
        portfolio_id: int | None = None,
        portfolio_name: str | None = None,
        fund_code: str,
        fund_name: str | None = None,
        trade_date: date,
        trade_type: str,
        units: Decimal | None = None,
        gross_amount: Decimal | None = None,
        fee_amount: Decimal | None = None,
        nav_per_unit: Decimal | None = None,
        external_reference: str | None = None,
        source_name: str | None = "openclaw_mcp",
        source_reference: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Append one authoritative transaction and commit its deterministic side effects."""
        try:
            result = self._transaction_service.append_transaction(
                portfolio_id=portfolio_id,
                portfolio_name=portfolio_name,
                fund_code=fund_code,
                fund_name=fund_name,
                trade_date=trade_date,
                trade_type=trade_type,
                units=units,
                gross_amount=gross_amount,
                fee_amount=fee_amount,
                nav_per_unit=nav_per_unit,
                external_reference=external_reference,
                source_name=source_name,
                source_reference=source_reference,
                note=note,
            )
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise

        return {
            "transaction": serialize_for_json(result.transaction),
            "lot_sync": serialize_for_json(result.lot_sync),
            "linked_transaction_ids": list(result.linked_transaction_ids),
            "fund_created": result.fund_created,
            "fund_updated": result.fund_updated,
            "message": (
                "Appended authoritative transaction "
                f"{result.transaction.transaction_id} and rebuilt transaction-backed lots."
            ),
        }

    def get_watchlist_candidates(
        self,
        *,
        as_of_date: date,
        portfolio_id: int | None = None,
        portfolio_name: str | None = None,
        risk_profile: str = "balanced",
        max_results: int = 6,
        categories: tuple[str, ...] | None = None,
        include_high_overlap: bool = False,
    ) -> dict[str, Any]:
        """Return structured watchlist candidates for one portfolio context."""
        result = self._watchlist_service.build_watchlist_candidates(
            as_of_date=as_of_date,
            portfolio_id=portfolio_id,
            portfolio_name=portfolio_name,
            risk_profile=risk_profile,
            max_results=max_results,
            include_categories=categories,
            exclude_high_overlap=not include_high_overlap,
        )
        return serialize_for_json(result)

    def get_watchlist_candidate_fit(
        self,
        *,
        as_of_date: date,
        fund_code: str,
        portfolio_id: int | None = None,
        portfolio_name: str | None = None,
    ) -> dict[str, Any]:
        """Return how one watchlist candidate fits the current portfolio."""
        result = self._watchlist_service.analyze_candidate_fit(
            as_of_date=as_of_date,
            fund_code=fund_code,
            portfolio_id=portfolio_id,
            portfolio_name=portfolio_name,
        )
        return serialize_for_json(result)

    def get_watchlist_style_leaders(
        self,
        *,
        as_of_date: date,
        categories: tuple[str, ...] | None = None,
        max_per_category: int = 1,
    ) -> dict[str, Any]:
        """Return grouped watchlist style leaders from the curated universe."""
        result = self._watchlist_service.build_style_leaders(
            as_of_date=as_of_date,
            categories=categories,
            max_per_category=max_per_category,
        )
        return {
            "as_of_date": as_of_date.isoformat(),
            "leaders": serialize_for_json(result),
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


def _build_decision_run_summary_payload(decision_run: DecisionRun) -> dict[str, Any]:
    return serialize_for_json(
        {
            "id": decision_run.id,
            "portfolio_id": decision_run.portfolio_id,
            "portfolio_code": decision_run.portfolio.portfolio_code,
            "portfolio_name": decision_run.portfolio.portfolio_name,
            "policy_id": decision_run.policy_id,
            "policy_name": (
                decision_run.policy.policy_name if decision_run.policy is not None else None
            ),
            "run_id": decision_run.run_id,
            "workflow_name": decision_run.workflow_name,
            "decision_date": decision_run.decision_date,
            "trigger_source": decision_run.trigger_source,
            "summary": decision_run.summary,
            "final_decision": decision_run.final_decision,
            "confidence_score": (
                float(decision_run.confidence_score)
                if decision_run.confidence_score is not None
                else None
            ),
            "action_count": _count_actions(decision_run.actions_json),
            "created_by_agent": decision_run.created_by_agent,
            "created_at": decision_run.created_at,
        }
    )


def _build_decision_run_detail_payload(decision_run: DecisionRun) -> dict[str, Any]:
    payload = _build_decision_run_summary_payload(decision_run)
    payload["actions_json"] = serialize_for_json(decision_run.actions_json)
    payload["decision_summary_json"] = serialize_for_json(decision_run.decision_summary_json)
    return payload


def _build_decision_feedback_payload(feedback: DecisionFeedback) -> dict[str, Any]:
    return serialize_for_json(
        {
            "id": feedback.id,
            "decision_run_id": feedback.decision_run_id,
            "portfolio_id": feedback.portfolio_id,
            "fund_id": feedback.fund_id,
            "fund_code": feedback.fund.fund_code if feedback.fund is not None else None,
            "fund_name": feedback.fund.fund_name if feedback.fund is not None else None,
            "action_index": feedback.action_index,
            "action_type": feedback.action_type,
            "feedback_status": feedback.feedback_status,
            "feedback_date": feedback.feedback_date,
            "note": feedback.note,
            "created_by": feedback.created_by,
            "linked_transaction_ids": sorted(
                transaction_link.transaction_id for transaction_link in feedback.transaction_links
            ),
            "created_at": feedback.created_at,
        }
    )


def _build_review_report_payload(review_report: ReviewReport) -> dict[str, Any]:
    return serialize_for_json(
        {
            "id": review_report.id,
            "portfolio_id": review_report.portfolio_id,
            "portfolio_code": review_report.portfolio.portfolio_code,
            "portfolio_name": review_report.portfolio.portfolio_name,
            "run_id": review_report.run_id,
            "workflow_name": review_report.workflow_name,
            "period_type": review_report.period_type,
            "period_start": review_report.period_start,
            "period_end": review_report.period_end,
            "report_markdown": review_report.report_markdown,
            "summary_json": review_report.summary_json,
            "created_by_agent": review_report.created_by_agent,
            "created_at": review_report.created_at,
        }
    )


def _count_actions(actions_json: list[dict[str, Any]] | dict[str, Any] | None) -> int:
    if isinstance(actions_json, list):
        return len(actions_json)
    if isinstance(actions_json, dict):
        return 1
    return 0


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
