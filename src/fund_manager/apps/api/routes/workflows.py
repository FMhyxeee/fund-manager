"""Workflow API routes for triggering manual workflow runs."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from fund_manager.apps.api.dependencies import get_db
from fund_manager.agents.workflows.weekly_review import WeeklyReviewWorkflow
from fund_manager.core.services.portfolio_service import PortfolioNotFoundError
from fund_manager.storage.models import Portfolio
from sqlalchemy import select

router = APIRouter(prefix="/workflows", tags=["workflows"])


class WeeklyReviewRunRequest(BaseModel):
    portfolio_id: int
    period_start: date | None = None
    period_end: date | None = None


class WeeklyReviewRunResponse(BaseModel):
    run_id: str
    portfolio_id: int
    period_start: date
    period_end: date
    report_record_id: int
    message: str


@router.post("/weekly-review/run", response_model=WeeklyReviewRunResponse)
def run_weekly_review(
    request: WeeklyReviewRunRequest,
    session: Annotated[Session, Depends(get_db)],
) -> WeeklyReviewRunResponse:
    portfolio = session.execute(
        select(Portfolio).where(Portfolio.id == request.portfolio_id)
    ).scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    period_start = request.period_start
    period_end = request.period_end
    if period_end is None:
        period_end = date.today()
    if period_start is None:
        from datetime import timedelta
        period_start = period_end - timedelta(days=7)

    workflow = WeeklyReviewWorkflow(session)
    try:
        result = workflow.run(
            portfolio_id=request.portfolio_id,
            period_start=period_start,
            period_end=period_end,
        )
    except PortfolioNotFoundError:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    session.commit()

    return WeeklyReviewRunResponse(
        run_id=result.run_id,
        portfolio_id=result.portfolio_id,
        period_start=result.period_start,
        period_end=result.period_end,
        report_record_id=result.report_record_id,
        message=f"Weekly review completed. Run ID: {result.run_id}",
    )
