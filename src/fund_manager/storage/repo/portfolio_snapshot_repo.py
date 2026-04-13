"""Repository helpers for append-only portfolio snapshot rows."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_manager.storage.models import PortfolioSnapshot


class PortfolioSnapshotRepository:
    """Persist deterministic portfolio snapshot records."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_run_id(self, run_id: str) -> PortfolioSnapshot | None:
        """Fetch one portfolio snapshot by run ID."""
        statement = select(PortfolioSnapshot).where(PortfolioSnapshot.run_id == run_id).limit(1)
        return self._session.execute(statement).scalars().first()

    def append(
        self,
        *,
        portfolio_id: int,
        snapshot_date: date,
        total_cost_amount: Decimal,
        total_market_value_amount: Decimal,
        unrealized_pnl_amount: Decimal,
        daily_return_ratio: Decimal | None,
        weekly_return_ratio: Decimal | None,
        monthly_return_ratio: Decimal | None,
        max_drawdown_ratio: Decimal | None,
        run_id: str | None = None,
        workflow_name: str | None = None,
        total_cash_amount: Decimal | None = None,
        realized_pnl_amount: Decimal | None = None,
        cash_ratio: Decimal | None = None,
    ) -> PortfolioSnapshot:
        """Append one deterministic portfolio snapshot row."""
        portfolio_snapshot = PortfolioSnapshot(
            portfolio_id=portfolio_id,
            run_id=run_id,
            workflow_name=workflow_name,
            snapshot_date=snapshot_date,
            total_cost_amount=total_cost_amount,
            total_market_value_amount=total_market_value_amount,
            total_cash_amount=total_cash_amount,
            unrealized_pnl_amount=unrealized_pnl_amount,
            realized_pnl_amount=realized_pnl_amount,
            cash_ratio=cash_ratio,
            daily_return_ratio=daily_return_ratio,
            weekly_return_ratio=weekly_return_ratio,
            monthly_return_ratio=monthly_return_ratio,
            max_drawdown_ratio=max_drawdown_ratio,
        )
        self._session.add(portfolio_snapshot)
        self._session.flush()
        return portfolio_snapshot
