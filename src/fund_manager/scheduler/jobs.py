"""Pre-wired job definitions for daily, weekly, and monthly workflows."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fund_manager.scheduler.types import JobFrequency, ScheduleEntry


def _build_weekly_period_bounds(as_of: date) -> tuple[date, date]:
    period_end = as_of
    period_start = period_end - timedelta(days=6)
    return period_start, period_end


def _build_monthly_period_bounds(as_of: date) -> tuple[date, date]:
    period_end = as_of
    period_start = period_end.replace(day=1)
    return period_start, period_end


def make_daily_snapshot_job(
    session: Any,
    *,
    as_of_date: date | None = None,
) -> ScheduleEntry:
    from fund_manager.core.services import PortfolioService

    as_of = as_of_date or date.today()

    def job_fn(*, portfolio_id: int, trigger_source: str) -> dict[str, Any]:
        portfolio_service = PortfolioService(session)
        snapshot = portfolio_service.get_portfolio_snapshot(
            portfolio_id,
            as_of_date=as_of,
            workflow_name="daily_snapshot",
        )
        return {"snapshot_id": snapshot.position_count, "as_of_date": as_of.isoformat()}

    return ScheduleEntry(
        name="daily_snapshot",
        frequency=JobFrequency.DAILY,
        job_fn=job_fn,
        description="Refresh portfolio snapshot with latest NAV data.",
    )


def make_weekly_review_job(
    session: Any,
    *,
    as_of_date: date | None = None,
) -> ScheduleEntry:
    from fund_manager.agents.workflows.weekly_review import WeeklyReviewWorkflow

    as_of = as_of_date or date.today()
    period_start, period_end = _build_weekly_period_bounds(as_of)

    def job_fn(*, portfolio_id: int, trigger_source: str) -> dict[str, Any]:
        workflow = WeeklyReviewWorkflow(session)
        result = workflow.run(
            portfolio_id=portfolio_id,
            period_start=period_start,
            period_end=period_end,
            trigger_source=trigger_source,
        )
        return {"report_id": result.report_record_id, "run_id": result.run_id}

    return ScheduleEntry(
        name="weekly_review",
        frequency=JobFrequency.WEEKLY,
        job_fn=job_fn,
        description="Run the weekly review workflow and persist the report.",
    )


def make_monthly_strategy_job(
    session: Any,
    *,
    as_of_date: date | None = None,
) -> ScheduleEntry:
    from fund_manager.agents.workflows.strategy_debate import StrategyDebateWorkflow

    as_of = as_of_date or date.today()
    period_start, period_end = _build_monthly_period_bounds(as_of)

    def job_fn(*, portfolio_id: int, trigger_source: str) -> dict[str, Any]:
        workflow = StrategyDebateWorkflow(session)
        result = workflow.run(
            portfolio_id=portfolio_id,
            period_start=period_start,
            period_end=period_end,
            trigger_source=trigger_source,
        )
        return {
            "strategy_proposal_id": result.strategy_proposal_record_id,
            "run_id": result.run_id,
        }

    return ScheduleEntry(
        name="monthly_strategy_debate",
        frequency=JobFrequency.MONTHLY,
        job_fn=job_fn,
        description="Run the multi-agent strategy debate and persist the proposal.",
    )


def register_default_jobs(
    session: Any,
    registry: Any,
    *,
    as_of_date: date | None = None,
) -> None:
    registry.register(make_daily_snapshot_job(session, as_of_date=as_of_date))
    registry.register(make_weekly_review_job(session, as_of_date=as_of_date))
    registry.register(make_monthly_strategy_job(session, as_of_date=as_of_date))
