"""Read-only portfolio service utilities for API callers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from fund_manager.core.services.portfolio_service import (
    PortfolioPositionDTO,
    PortfolioService,
    PortfolioSnapshotDTO,
)
from fund_manager.storage.models import Portfolio
from fund_manager.storage.repo import PortfolioRepository
from fund_manager.storage.repo.protocols import PortfolioRepositoryProtocol


@dataclass(frozen=True)
class PortfolioSummaryDTO:
    """Minimal portfolio metadata safe to expose to read-oriented callers."""

    portfolio_id: int
    portfolio_code: str
    portfolio_name: str
    base_currency_code: str
    is_default: bool


@dataclass(frozen=True)
class PortfolioSnapshotReadResult:
    """One resolved portfolio plus its deterministic snapshot DTO."""

    portfolio: PortfolioSummaryDTO
    snapshot: PortfolioSnapshotDTO


@dataclass(frozen=True)
class PositionBreakdownReadResult:
    """One resolved portfolio plus its deterministic position breakdown."""

    portfolio: PortfolioSummaryDTO
    as_of_date: date
    positions: tuple[PortfolioPositionDTO, ...]


class PortfolioReadService:
    """Resolve portfolios and expose deterministic read models for callers."""

    def __init__(
        self,
        session: Session,
        *,
        portfolio_service: PortfolioService | None = None,
        portfolio_repo: PortfolioRepositoryProtocol | None = None,
    ) -> None:
        self._portfolio_service = portfolio_service or PortfolioService(session)
        self._portfolio_repo = portfolio_repo or PortfolioRepository(session)

    def list_portfolios(self) -> tuple[PortfolioSummaryDTO, ...]:
        """List available portfolios in a stable order for read-only consumers."""
        return tuple(
            self._to_summary_dto(portfolio)
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
    ) -> PortfolioSnapshotReadResult:
        """Resolve one portfolio and load its deterministic snapshot."""
        portfolio = self._resolve_portfolio(
            portfolio_id=portfolio_id,
            portfolio_name=portfolio_name,
        )
        snapshot = self._portfolio_service.get_portfolio_snapshot(
            portfolio.id,
            as_of_date=as_of_date,
            run_id=run_id,
            workflow_name=workflow_name,
        )
        return PortfolioSnapshotReadResult(
            portfolio=self._to_summary_dto(portfolio),
            snapshot=snapshot,
        )

    def resolve_portfolio_summary(
        self,
        *,
        portfolio_id: int | None = None,
        portfolio_name: str | None = None,
    ) -> PortfolioSummaryDTO:
        """Resolve one portfolio selector to the stable summary DTO."""
        portfolio = self._resolve_portfolio(
            portfolio_id=portfolio_id,
            portfolio_name=portfolio_name,
        )
        return self._to_summary_dto(portfolio)

    def get_position_breakdown(
        self,
        *,
        as_of_date: date,
        portfolio_id: int | None = None,
        portfolio_name: str | None = None,
    ) -> PositionBreakdownReadResult:
        """Resolve one portfolio and load only its deterministic positions."""
        portfolio = self._resolve_portfolio(
            portfolio_id=portfolio_id,
            portfolio_name=portfolio_name,
        )
        positions = self._portfolio_service.get_position_breakdown(
            portfolio.id,
            as_of_date=as_of_date,
        )
        return PositionBreakdownReadResult(
            portfolio=self._to_summary_dto(portfolio),
            as_of_date=as_of_date,
            positions=positions,
        )

    def _resolve_portfolio(
        self,
        *,
        portfolio_id: int | None,
        portfolio_name: str | None,
    ) -> Portfolio:
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

    def _to_summary_dto(self, portfolio: Portfolio) -> PortfolioSummaryDTO:
        return PortfolioSummaryDTO(
            portfolio_id=portfolio.id,
            portfolio_code=portfolio.portfolio_code,
            portfolio_name=portfolio.portfolio_name,
            base_currency_code=portfolio.base_currency_code,
            is_default=portfolio.is_default,
        )


__all__ = [
    "PortfolioReadService",
    "PortfolioSnapshotReadResult",
    "PortfolioSummaryDTO",
    "PositionBreakdownReadResult",
]
