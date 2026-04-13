"""Controlled portfolio and workflow tools exposed to agents."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from fund_manager.agents.workflows import DailyDecisionWorkflow, WeeklyReviewWorkflow
from fund_manager.core.serialization import serialize_for_json
from fund_manager.core.services import (
    DecisionFeedbackService,
    PolicyService,
    PortfolioReadService,
    PortfolioService,
    PortfolioSummaryDTO,
)
from fund_manager.core.watchlist import FundWatchlistService
from fund_manager.storage.models import DecisionFeedbackStatus, DecisionRun
from fund_manager.storage.repo import DecisionRunRepository


class PortfolioTools:
    """Typed agent-facing wrappers around deterministic portfolio services."""

    def __init__(
        self,
        session: Session,
        *,
        portfolio_read_service: PortfolioReadService | None = None,
        portfolio_service: PortfolioService | None = None,
        policy_service: PolicyService | None = None,
        decision_run_repo: DecisionRunRepository | None = None,
        decision_feedback_service: DecisionFeedbackService | None = None,
        daily_decision_workflow: DailyDecisionWorkflow | None = None,
        weekly_review_workflow: WeeklyReviewWorkflow | None = None,
    ) -> None:
        self._portfolio_service = portfolio_service or PortfolioService(session)
        self._portfolio_read_service = portfolio_read_service or PortfolioReadService(
            session,
            portfolio_service=self._portfolio_service,
        )
        self._policy_service = policy_service or PolicyService(session)
        self._decision_run_repo = decision_run_repo or DecisionRunRepository(session)
        self._decision_feedback_service = (
            decision_feedback_service or DecisionFeedbackService(session)
        )
        self._watchlist_service = FundWatchlistService(session)
        self._daily_decision_workflow = daily_decision_workflow or DailyDecisionWorkflow(session)
        self._weekly_review_workflow = weekly_review_workflow or WeeklyReviewWorkflow(
            session,
            portfolio_service=self._portfolio_service,
        )

    def list_portfolios(self) -> tuple[PortfolioSummaryDTO, ...]:
        """List available portfolios in a stable order for tool selection."""
        return self._portfolio_read_service.list_portfolios()

    def get_portfolio_snapshot(
        self,
        *,
        as_of_date: date,
        portfolio_id: int | None = None,
        portfolio_name: str | None = None,
        run_id: str | None = None,
        workflow_name: str | None = None,
    ) -> dict[str, Any]:
        """Return a JSON-safe structured portfolio snapshot."""
        result = self._portfolio_read_service.get_portfolio_snapshot(
            as_of_date=as_of_date,
            portfolio_id=portfolio_id,
            portfolio_name=portfolio_name,
            run_id=run_id,
            workflow_name=workflow_name,
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
            "positions": serialize_for_json([asdict(position) for position in result.positions]),
        }

    def get_portfolio_metrics(
        self,
        *,
        as_of_date: date,
        portfolio_id: int | None = None,
        portfolio_name: str | None = None,
    ) -> dict[str, Any]:
        """Return a compact metrics summary derived from one portfolio snapshot."""
        result = self._portfolio_read_service.get_portfolio_snapshot(
            as_of_date=as_of_date,
            portfolio_id=portfolio_id,
            portfolio_name=portfolio_name,
        )
        snapshot = serialize_for_json(result.snapshot.to_dict())
        positions = snapshot["positions"]
        top_positions = sorted(
            positions,
            key=lambda position: Decimal(position["current_value_amount"] or "0.0000"),
            reverse=True,
        )[:5]
        return {
            "portfolio": serialize_for_json(result.portfolio),
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

    def get_portfolio_valuation_history(
        self,
        *,
        end_date: date,
        start_date: date | None = None,
        portfolio_id: int | None = None,
        portfolio_name: str | None = None,
    ) -> dict[str, Any]:
        """Return valuation history assembled from canonical lots and NAV snapshots."""
        result = self._portfolio_read_service.get_portfolio_snapshot(
            as_of_date=end_date,
            portfolio_id=portfolio_id,
            portfolio_name=portfolio_name,
        )
        snapshot = serialize_for_json(result.snapshot.to_dict())
        valuation_history = snapshot["valuation_history"]
        if start_date is not None:
            valuation_history = [
                point
                for point in valuation_history
                if point["as_of_date"] >= start_date.isoformat()
            ]
        return {
            "portfolio": serialize_for_json(result.portfolio),
            "start_date": start_date.isoformat() if start_date is not None else None,
            "end_date": end_date.isoformat(),
            "valuation_history": valuation_history,
        }

    def get_active_policy(
        self,
        *,
        as_of_date: date,
        portfolio_id: int | None = None,
        portfolio_name: str | None = None,
    ) -> dict[str, Any]:
        """Return the active policy for one portfolio on one date."""
        resolved_portfolio = self._portfolio_read_service.resolve_portfolio_summary(
            portfolio_id=portfolio_id,
            portfolio_name=portfolio_name,
        )
        policy = self._policy_service.get_active_policy(
            portfolio_id=resolved_portfolio.portfolio_id,
            as_of_date=as_of_date,
        )
        if policy is None:
            msg = "Active policy not found."
            raise ValueError(msg)
        return {
            "portfolio": serialize_for_json(resolved_portfolio),
            "as_of_date": as_of_date.isoformat(),
            "policy": serialize_for_json(policy),
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

    def get_decision_run(self, *, decision_run_id: int) -> dict[str, Any]:
        """Return one persisted decision run in detail form."""
        decision_run = self._decision_run_repo.get_detail_by_id(decision_run_id)
        if decision_run is None:
            msg = "Decision run not found."
            raise ValueError(msg)
        return {"decision_run": _build_decision_run_detail_payload(decision_run)}

    def run_daily_decision(
        self,
        *,
        decision_date: date,
        portfolio_id: int | None = None,
        portfolio_name: str | None = None,
        trigger_source: str = "agent",
    ) -> dict[str, Any]:
        """Run the deterministic daily decision workflow and return a JSON-safe summary."""
        resolved_portfolio = self._portfolio_read_service.resolve_portfolio_summary(
            portfolio_id=portfolio_id,
            portfolio_name=portfolio_name,
        )
        result = self._daily_decision_workflow.run(
            portfolio_id=resolved_portfolio.portfolio_id,
            decision_date=decision_date,
            trigger_source=trigger_source,
        )
        return {
            "run_id": result.run_id,
            "workflow_name": result.workflow_name,
            "portfolio_id": result.portfolio_id,
            "decision_date": result.decision_date.isoformat(),
            "decision_run_id": result.decision_run_record_id,
            "final_decision": result.decision.final_decision,
            "action_count": result.decision.action_count,
            "decision": serialize_for_json(result.decision.to_dict()),
        }

    def record_decision_feedback(
        self,
        *,
        decision_run_id: int,
        action_index: int,
        feedback_status: DecisionFeedbackStatus | str,
        feedback_date: date | None = None,
        note: str | None = None,
        created_by: str | None = None,
        reconcile_existing_transactions: bool = True,
    ) -> dict[str, Any]:
        """Side-effecting tool: persist manual feedback for one deterministic decision action."""
        resolved_status = (
            feedback_status
            if isinstance(feedback_status, DecisionFeedbackStatus)
            else DecisionFeedbackStatus(feedback_status)
        )
        result = self._decision_feedback_service.record_feedback(
            decision_run_id=decision_run_id,
            action_index=action_index,
            feedback_status=resolved_status,
            feedback_date=feedback_date,
            note=note,
            created_by=created_by,
            reconcile_existing_transactions=reconcile_existing_transactions,
        )
        return {
            "feedback_id": result.feedback_id,
            "decision_run_id": result.decision_run_id,
            "portfolio_id": result.portfolio_id,
            "fund_id": result.fund_id,
            "action_index": result.action_index,
            "action_type": result.action_type,
            "feedback_status": result.feedback_status.value,
            "feedback_date": result.feedback_date.isoformat(),
            "linked_transaction_ids": list(result.linked_transaction_ids),
            "message": (
                f"Recorded {result.feedback_status.value} feedback for action "
                f"{result.action_index}."
            ),
        }

    def run_weekly_review(
        self,
        *,
        period_start: date,
        period_end: date,
        portfolio_id: int | None = None,
        portfolio_name: str | None = None,
        trigger_source: str = "agent",
    ) -> dict[str, Any]:
        """Run the manual weekly review workflow and return a JSON-safe artifact summary."""
        resolved_portfolio = self._portfolio_read_service.resolve_portfolio_summary(
            portfolio_id=portfolio_id,
            portfolio_name=portfolio_name,
        )
        result = self._weekly_review_workflow.run(
            portfolio_id=resolved_portfolio.portfolio_id,
            period_start=period_start,
            period_end=period_end,
            trigger_source=trigger_source,
        )
        return serialize_for_json(asdict(result))


__all__ = [
    "PortfolioSummaryDTO",
    "PortfolioTools",
]


def _build_decision_run_detail_payload(decision_run: DecisionRun) -> dict[str, Any]:
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
            "actions_json": decision_run.actions_json,
            "decision_summary_json": decision_run.decision_summary_json,
        }
    )


def _count_actions(actions_json: list[dict[str, Any]] | dict[str, Any] | None) -> int:
    if isinstance(actions_json, list):
        return len(actions_json)
    if isinstance(actions_json, dict):
        return 1
    return 0
