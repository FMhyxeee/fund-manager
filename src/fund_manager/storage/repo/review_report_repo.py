"""Repository helpers for append-only review reports."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from fund_manager.storage.models import ReportPeriodType, ReviewReport


class ReviewReportRepository:
    """Persist generated review reports without rewriting history."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def append(
        self,
        *,
        portfolio_id: int,
        period_type: ReportPeriodType,
        period_start: date,
        period_end: date,
        report_markdown: str,
        summary_json: dict[str, Any] | None,
        created_by_agent: str | None,
        run_id: str | None = None,
        workflow_name: str | None = None,
    ) -> ReviewReport:
        """Append one persisted review report artifact."""
        review_report = ReviewReport(
            portfolio_id=portfolio_id,
            run_id=run_id,
            workflow_name=workflow_name,
            period_type=period_type,
            period_start=period_start,
            period_end=period_end,
            report_markdown=report_markdown,
            summary_json=summary_json,
            created_by_agent=created_by_agent,
        )
        self._session.add(review_report)
        self._session.flush()
        return review_report
