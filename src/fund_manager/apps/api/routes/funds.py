"""Fund API routes."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_manager.apps.api.dependencies import get_db
from fund_manager.storage.models import NavSnapshot
from fund_manager.storage.repo import FundMasterRepository

router = APIRouter(prefix="/funds", tags=["funds"])


class FundProfileResponse(BaseModel):
    fund_code: str
    fund_name: str
    fund_type: str | None = None
    base_currency_code: str = "CNY"
    company_name: str | None = None
    manager_name: str | None = None
    risk_level: str | None = None
    benchmark_name: str | None = None
    fund_status: str | None = None
    source_name: str | None = None


class FundNavPointResponse(BaseModel):
    nav_date: date
    unit_nav_amount: Decimal | None = None
    accumulated_nav_amount: Decimal | None = None
    daily_return_ratio: Decimal | None = None
    source_name: str | None = None


class FundNavHistoryResponse(BaseModel):
    fund_code: str
    fund_name: str
    start_date: date
    end_date: date
    points: list[FundNavPointResponse] = Field(default_factory=list)


@router.get("/{fund_code}", response_model=FundProfileResponse)
def get_fund_profile(
    fund_code: str,
    session: Annotated[Session, Depends(get_db)],
) -> FundProfileResponse:
    repo = FundMasterRepository(session)
    fund = repo.get_by_code(fund_code)
    if fund is None:
        raise HTTPException(status_code=404, detail="Fund not found")
    return FundProfileResponse(
        fund_code=fund.fund_code,
        fund_name=fund.fund_name,
        fund_type=fund.fund_type,
        base_currency_code=fund.base_currency_code,
        company_name=fund.company_name,
        manager_name=fund.manager_name,
        risk_level=fund.risk_level,
        benchmark_name=fund.benchmark_name,
        fund_status=fund.fund_status,
        source_name=fund.source_name,
    )


@router.get("/{fund_code}/nav-history", response_model=FundNavHistoryResponse)
def get_fund_nav_history(
    fund_code: str,
    start_date: Annotated[date, Query()],
    end_date: Annotated[date, Query()],
    session: Annotated[Session, Depends(get_db)],
) -> FundNavHistoryResponse:
    repo = FundMasterRepository(session)
    fund = repo.get_by_code(fund_code)
    if fund is None:
        raise HTTPException(status_code=404, detail="Fund not found")

    rows = (
        session.execute(
            select(NavSnapshot)
            .where(
                NavSnapshot.fund_id == fund.id,
                NavSnapshot.nav_date >= start_date,
                NavSnapshot.nav_date <= end_date,
            )
            .order_by(NavSnapshot.nav_date.asc(), NavSnapshot.id.asc())
        )
        .scalars()
        .all()
    )
    return FundNavHistoryResponse(
        fund_code=fund.fund_code,
        fund_name=fund.fund_name,
        start_date=start_date,
        end_date=end_date,
        points=[
            FundNavPointResponse(
                nav_date=row.nav_date,
                unit_nav_amount=row.unit_nav_amount,
                accumulated_nav_amount=row.accumulated_nav_amount,
                daily_return_ratio=row.daily_return_ratio,
                source_name=row.source_name,
            )
            for row in rows
        ],
    )
