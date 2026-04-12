"""Controlled portfolio and workflow tools exposed to agents."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from fund_manager.agents.workflows import WeeklyReviewWorkflow
from fund_manager.core.serialization import serialize_for_json
from fund_manager.core.services import PortfolioReadService, PortfolioService, PortfolioSummaryDTO


class PortfolioTools:
    """Typed agent-facing wrappers around deterministic portfolio services."""

    def __init__(
        self,
        session: Session,
        *,
        portfolio_read_service: PortfolioReadService | None = None,
        portfolio_service: PortfolioService | None = None,
        weekly_review_workflow: WeeklyReviewWorkflow | None = None,
    ) -> None:
        self._portfolio_service = portfolio_service or PortfolioService(session)
        self._portfolio_read_service = portfolio_read_service or PortfolioReadService(
            session,
            portfolio_service=self._portfolio_service,
        )
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
