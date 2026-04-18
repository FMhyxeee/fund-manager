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
    PortfolioSnapshotDTO,
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


class PositionBreakdownResponse(BaseModel):
    portfolio_id: int
    portfolio_code: str
    portfolio_name: str
    as_of_date: date
    positions: list[PositionSnapshot] = Field(default_factory=list)


class PortfolioMetricsResponse(BaseModel):
    portfolio_id: int
    portfolio_code: str
    portfolio_name: str
    as_of_date: date
    metrics: dict[str, object]


class PortfolioValuationPointResponse(BaseModel):
    as_of_date: date
    market_value_amount: Decimal


class PortfolioValuationHistoryResponse(BaseModel):
    portfolio_id: int
    portfolio_code: str
    portfolio_name: str
    start_date: date | None = None
    end_date: date
    valuation_history: list[PortfolioValuationPointResponse] = Field(default_factory=list)


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
    session: Annotated[Session, Depends(get_db)],
    as_of_date: Annotated[date | None, Query()] = None,
) -> PortfolioSnapshotResponse:
    snapshot = _load_snapshot_or_404(
        session,
        portfolio_id=portfolio_id,
        as_of_date=as_of_date or date.today(),
    )

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
        positions=_build_position_snapshots(snapshot),
    )


@router.get("/{portfolio_id}/positions", response_model=PositionBreakdownResponse)
def get_position_breakdown(
    portfolio_id: int,
    session: Annotated[Session, Depends(get_db)],
    as_of_date: Annotated[date | None, Query()] = None,
) -> PositionBreakdownResponse:
    snapshot = _load_snapshot_or_404(
        session,
        portfolio_id=portfolio_id,
        as_of_date=as_of_date or date.today(),
    )
    return PositionBreakdownResponse(
        portfolio_id=snapshot.portfolio_id,
        portfolio_code=snapshot.portfolio_code,
        portfolio_name=snapshot.portfolio_name,
        as_of_date=snapshot.as_of_date,
        positions=_build_position_snapshots(snapshot),
    )


@router.get("/{portfolio_id}/metrics", response_model=PortfolioMetricsResponse)
def get_portfolio_metrics(
    portfolio_id: int,
    session: Annotated[Session, Depends(get_db)],
    as_of_date: Annotated[date | None, Query()] = None,
) -> PortfolioMetricsResponse:
    snapshot = _load_snapshot_or_404(
        session,
        portfolio_id=portfolio_id,
        as_of_date=as_of_date or date.today(),
    )
    top_positions = sorted(
        _build_position_snapshots(snapshot),
        key=lambda position: position.current_value or Decimal("0"),
        reverse=True,
    )[:5]
    return PortfolioMetricsResponse(
        portfolio_id=snapshot.portfolio_id,
        portfolio_code=snapshot.portfolio_code,
        portfolio_name=snapshot.portfolio_name,
        as_of_date=snapshot.as_of_date,
        metrics={
            "position_count": snapshot.position_count,
            "total_cost_amount": snapshot.total_cost_amount,
            "total_market_value_amount": snapshot.total_market_value_amount,
            "unrealized_pnl_amount": snapshot.unrealized_pnl_amount,
            "daily_return_ratio": snapshot.daily_return_ratio,
            "weekly_return_ratio": snapshot.weekly_return_ratio,
            "monthly_return_ratio": snapshot.monthly_return_ratio,
            "period_return_ratio": snapshot.period_return_ratio,
            "max_drawdown_ratio": snapshot.max_drawdown_ratio,
            "missing_nav_fund_codes": list(snapshot.missing_nav_fund_codes),
            "top_positions": [position.model_dump(mode="json") for position in top_positions],
        },
    )


@router.get(
    "/{portfolio_id}/valuation-history",
    response_model=PortfolioValuationHistoryResponse,
)
def get_portfolio_valuation_history(
    portfolio_id: int,
    session: Annotated[Session, Depends(get_db)],
    end_date: Annotated[date | None, Query()] = None,
    start_date: Annotated[date | None, Query()] = None,
) -> PortfolioValuationHistoryResponse:
    snapshot = _load_snapshot_or_404(
        session,
        portfolio_id=portfolio_id,
        as_of_date=end_date or date.today(),
    )
    valuation_history = [
        PortfolioValuationPointResponse(
            as_of_date=point.as_of_date,
            market_value_amount=point.market_value_amount,
        )
        for point in snapshot.valuation_history
        if start_date is None or point.as_of_date >= start_date
    ]
    return PortfolioValuationHistoryResponse(
        portfolio_id=snapshot.portfolio_id,
        portfolio_code=snapshot.portfolio_code,
        portfolio_name=snapshot.portfolio_name,
        start_date=start_date,
        end_date=snapshot.as_of_date,
        valuation_history=valuation_history,
    )


def _load_snapshot_or_404(
    session: Session,
    *,
    portfolio_id: int,
    as_of_date: date,
) -> PortfolioSnapshotDTO:
    service = PortfolioService(session)
    try:
        return service.assemble_portfolio_snapshot(
            portfolio_id=portfolio_id,
            as_of_date=as_of_date,
        )
    except PortfolioNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Portfolio not found") from exc


def _build_position_snapshots(snapshot: PortfolioSnapshotDTO) -> list[PositionSnapshot]:
    return [
        PositionSnapshot(
            fund_code=position.fund_code,
            fund_name=position.fund_name,
            units=position.units,
            average_cost_per_unit=position.average_cost_per_unit,
            total_cost=position.total_cost_amount,
            latest_nav=position.latest_nav_per_unit,
            current_value=position.current_value_amount,
            unrealized_pnl=position.unrealized_pnl_amount,
            weight=position.weight_ratio,
            missing_nav=position.missing_nav,
        )
        for position in snapshot.positions
    ]
