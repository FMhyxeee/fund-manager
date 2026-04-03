"""Portfolio API routes."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_manager.apps.api.dependencies import get_db
from fund_manager.core.services.portfolio_service import (
    PortfolioNotFoundError,
    PortfolioService,
)
from fund_manager.storage.models import Portfolio

router = APIRouter(prefix="/portfolios", tags=["portfolios"])


# --- Response models ---


class PositionSnapshot(BaseModel):
    fund_code: str
    fund_name: str
    units: Decimal
    average_cost_per_unit: Decimal
    total_cost: Decimal
    latest_nav: Decimal | None = None
    current_value: Decimal | None = None
    unrealized_pnl: Decimal | None = None
    weight: Decimal | None = None
    missing_nav: bool = False


class PortfolioSnapshotResponse(BaseModel):
    portfolio_id: int
    portfolio_code: str
    portfolio_name: str
    as_of_date: date
    position_count: int
    total_cost: Decimal
    total_market_value: Decimal | None = None
    unrealized_pnl: Decimal | None = None
    period_return: Decimal | None = None
    max_drawdown: Decimal | None = None
    missing_nav_fund_codes: list[str] = Field(default_factory=list)
    positions: list[PositionSnapshot] = Field(default_factory=list)


class PortfolioSummary(BaseModel):
    id: int
    portfolio_code: str
    portfolio_name: str


# --- Endpoints ---


@router.get("", response_model=list[PortfolioSummary])
def list_portfolios(session: Annotated[Session, Depends(get_db)]) -> list[PortfolioSummary]:
    rows = session.execute(select(Portfolio).order_by(Portfolio.id.asc())).scalars().all()
    return [
        PortfolioSummary(id=p.id, portfolio_code=p.portfolio_code, portfolio_name=p.portfolio_name)
        for p in rows
    ]


@router.get("/{portfolio_id}/snapshot", response_model=PortfolioSnapshotResponse)
def get_portfolio_snapshot(
    portfolio_id: int,
    as_of_date: Annotated[date | None, Query()] = None,
    session: Annotated[Session, Depends(get_db)] = None,
) -> PortfolioSnapshotResponse:
    service = PortfolioService(session)
    snapshot_date = as_of_date or date.today()
    try:
        snapshot = service.assemble_portfolio_snapshot(
            portfolio_id=portfolio_id,
            as_of_date=snapshot_date,
        )
    except PortfolioNotFoundError:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    positions = [
        PositionSnapshot(
            fund_code=p.fund_code,
            fund_name=p.fund_name,
            units=p.units,
            average_cost_per_unit=p.average_cost_per_unit,
            total_cost=p.total_cost_amount,
            latest_nav=p.latest_nav_per_unit,
            current_value=p.current_value_amount,
            unrealized_pnl=p.unrealized_pnl_amount,
            weight=p.weight_ratio,
            missing_nav=p.missing_nav,
        )
        for p in snapshot.positions
    ]

    return PortfolioSnapshotResponse(
        portfolio_id=snapshot.portfolio_id,
        portfolio_code=snapshot.portfolio_code,
        portfolio_name=snapshot.portfolio_name,
        as_of_date=snapshot.as_of_date,
        position_count=snapshot.position_count,
        total_cost=snapshot.total_cost_amount,
        total_market_value=snapshot.total_market_value_amount,
        unrealized_pnl=snapshot.unrealized_pnl_amount,
        period_return=snapshot.period_return_ratio,
        max_drawdown=snapshot.max_drawdown_ratio,
        missing_nav_fund_codes=list(snapshot.missing_nav_fund_codes),
        positions=positions,
    )
