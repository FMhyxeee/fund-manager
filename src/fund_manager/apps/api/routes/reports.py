"""Report API routes."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_manager.apps.api.dependencies import get_db
from fund_manager.storage.models import ReviewReport

router = APIRouter(prefix="/reports", tags=["reports"])


class ReportSummary(BaseModel):
    id: int
    portfolio_id: int
    period_type: str
    period_start: date
    period_end: date
    status: str


@router.get("", response_model=list[ReportSummary])
def list_reports(
    portfolio_id: Annotated[int | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    session: Annotated[Session, Depends(get_db)] = None,
) -> list[ReportSummary]:
    stmt = select(ReviewReport).order_by(ReviewReport.id.desc()).limit(limit)
    if portfolio_id is not None:
        stmt = stmt.where(ReviewReport.portfolio_id == portfolio_id)
    rows = session.execute(stmt).scalars().all()
    return [
        ReportSummary(
            id=r.id,
            portfolio_id=r.portfolio_id,
            period_type=r.period_type,
            period_start=r.period_start,
            period_end=r.period_end,
            status=r.status,
        )
        for r in rows
    ]
