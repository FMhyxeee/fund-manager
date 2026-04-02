"""Controlled portfolio and workflow tools exposed to agents."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from fund_manager.agents.workflows import WeeklyReviewWorkflow, serialize_for_json
from fund_manager.core.services import PortfolioService
from fund_manager.storage.repo import PortfolioRepository


@dataclass(frozen=True)
class PortfolioSummaryDTO:
    """Minimal portfolio metadata safe to expose to agents."""

    portfolio_id: int
    portfolio_code: str
    portfolio_name: str
    base_currency_code: str
    is_default: bool


class PortfolioTools:
    """Typed agent-facing wrappers around deterministic portfolio services."""

    def __init__(
        self,
        session: Session,
        *,
        portfolio_service: PortfolioService | None = None,
        weekly_review_workflow: WeeklyReviewWorkflow | None = None,
    ) -> None:
        self._session = session
        self._portfolio_repo = PortfolioRepository(session)
        self._portfolio_service = portfolio_service or PortfolioService(session)
        self._weekly_review_workflow = weekly_review_workflow or WeeklyReviewWorkflow(
            session,
            portfolio_service=self._portfolio_service,
        )

    def list_portfolios(self) -> tuple[PortfolioSummaryDTO, ...]:
        """List available portfolios in a stable order for tool selection."""
        return tuple(
            PortfolioSummaryDTO(
                portfolio_id=portfolio.id,
                portfolio_code=portfolio.portfolio_code,
                portfolio_name=portfolio.portfolio_name,
                base_currency_code=portfolio.base_currency_code,
                is_default=portfolio.is_default,
            )
            for portfolio in self._portfolio_repo.list_all()
        )

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
        resolved_portfolio = self._resolve_portfolio(
            portfolio_id=portfolio_id,
            portfolio_name=portfolio_name,
        )
        snapshot = self._portfolio_service.get_portfolio_snapshot(
            resolved_portfolio.id,
            as_of_date=as_of_date,
            run_id=run_id,
            workflow_name=workflow_name,
        )
        return {
            "portfolio": serialize_for_json(
                PortfolioSummaryDTO(
                    portfolio_id=resolved_portfolio.id,
                    portfolio_code=resolved_portfolio.portfolio_code,
                    portfolio_name=resolved_portfolio.portfolio_name,
                    base_currency_code=resolved_portfolio.base_currency_code,
                    is_default=resolved_portfolio.is_default,
                )
            ),
            "snapshot": serialize_for_json(snapshot.to_dict()),
        }

    def get_position_breakdown(
        self,
        *,
        as_of_date: date,
        portfolio_id: int | None = None,
        portfolio_name: str | None = None,
    ) -> dict[str, Any]:
        """Return only the position breakdown for one portfolio."""
        resolved_portfolio = self._resolve_portfolio(
            portfolio_id=portfolio_id,
            portfolio_name=portfolio_name,
        )
        positions = self._portfolio_service.get_position_breakdown(
            resolved_portfolio.id,
            as_of_date=as_of_date,
        )
        return {
            "portfolio": serialize_for_json(
                PortfolioSummaryDTO(
                    portfolio_id=resolved_portfolio.id,
                    portfolio_code=resolved_portfolio.portfolio_code,
                    portfolio_name=resolved_portfolio.portfolio_name,
                    base_currency_code=resolved_portfolio.base_currency_code,
                    is_default=resolved_portfolio.is_default,
                )
            ),
            "as_of_date": as_of_date.isoformat(),
            "positions": serialize_for_json([asdict(position) for position in positions]),
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
        resolved_portfolio = self._resolve_portfolio(
            portfolio_id=portfolio_id,
            portfolio_name=portfolio_name,
        )
        result = self._weekly_review_workflow.run(
            portfolio_id=resolved_portfolio.id,
            period_start=period_start,
            period_end=period_end,
            trigger_source=trigger_source,
        )
        return serialize_for_json(asdict(result))

    def _resolve_portfolio(
        self,
        *,
        portfolio_id: int | None,
        portfolio_name: str | None,
    ) -> Any:
        if (portfolio_id is None) == (portfolio_name is None):
            msg = "Provide exactly one of portfolio_id or portfolio_name."
            raise ValueError(msg)

        if portfolio_id is not None:
            portfolio = self._portfolio_repo.get_by_id(portfolio_id)
            if portfolio is None:
                msg = f"Portfolio {portfolio_id} was not found."
                raise ValueError(msg)
            return portfolio

        assert portfolio_name is not None
        portfolio = self._portfolio_repo.get_by_name(portfolio_name)
        if portfolio is None:
            msg = f"Portfolio named '{portfolio_name}' was not found."
            raise ValueError(msg)
        return portfolio


__all__ = [
    "PortfolioSummaryDTO",
    "PortfolioTools",
]
