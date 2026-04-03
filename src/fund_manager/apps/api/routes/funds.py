"""Fund API routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from fund_manager.apps.api.dependencies import get_db
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
