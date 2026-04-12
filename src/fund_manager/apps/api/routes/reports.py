"""Report API routes."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_manager.apps.api.dependencies import get_db
from fund_manager.storage.models import ReviewReport
from fund_manager.storage.repo import ReviewReportRepository

router = APIRouter(prefix="/reports", tags=["reports"])


class ReportSummary(BaseModel):
    id: int
    portfolio_id: int
    period_type: str
    period_start: date
    period_end: date
    status: str


class ReportDetailResponse(ReportSummary):
    portfolio_code: str
    portfolio_name: str
    run_id: str | None = None
    workflow_name: str | None = None
    report_markdown: str
    summary_json: dict[str, Any] | None = None
    created_by_agent: str | None = None
    created_at: datetime


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
            status="completed",
        )
        for r in rows
    ]


@router.get("/{report_id}", response_model=ReportDetailResponse)
def get_report(
    report_id: int,
    session: Annotated[Session, Depends(get_db)],
) -> ReportDetailResponse:
    report = ReviewReportRepository(session).get_by_id(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return _build_report_detail_response(report)


def _build_report_detail_response(report: ReviewReport) -> ReportDetailResponse:
    return ReportDetailResponse(
        id=report.id,
        portfolio_id=report.portfolio_id,
        portfolio_code=report.portfolio.portfolio_code,
        portfolio_name=report.portfolio.portfolio_name,
        run_id=report.run_id,
        workflow_name=report.workflow_name,
        period_type=report.period_type,
        period_start=report.period_start,
        period_end=report.period_end,
        status="completed",
        report_markdown=report.report_markdown,
        summary_json=report.summary_json,
        created_by_agent=report.created_by_agent,
        created_at=report.created_at,
    )
