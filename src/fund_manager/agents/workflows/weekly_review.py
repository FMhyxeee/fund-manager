"""Manual weekly review workflow orchestration."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, cast
from uuid import uuid4

from sqlalchemy.orm import Session

from fund_manager.agents.runtime import (
    ManualReviewAgent,
    ReviewAgent,
    ReviewAgentOutput,
    ReviewPositionFact,
    WeeklyReviewFacts,
)
from fund_manager.core.serialization import serialize_for_json
from fund_manager.core.domain.metrics import PortfolioValuePoint
from fund_manager.core.services import AnalyticsService, PortfolioService
from fund_manager.reports import WeeklyReviewMarkdownExporter
from fund_manager.storage.models import ReportPeriodType
from fund_manager.storage.repo import (
    AgentDebateLogRepository,
    PortfolioRepository,
    ReviewReportRepository,
    SystemEventLogRepository,
)
from fund_manager.storage.repo.protocols import (
    AgentDebateLogRepositoryProtocol,
    PortfolioRepositoryProtocol,
    ReviewReportRepositoryProtocol,
    SystemEventLogRepositoryProtocol,
)

WORKFLOW_NAME = "weekly_review"
MAX_HIGHLIGHT_POSITIONS = 3


@dataclass(frozen=True)
class WeeklyReviewWorkflowResult:
    """Structured result returned after a weekly review run completes."""

    run_id: str
    workflow_name: str
    portfolio_id: int
    period_start: date
    period_end: date
    report_record_id: int
    report_markdown: str
    review_output: ReviewAgentOutput
    facts: WeeklyReviewFacts


class WeeklyReviewWorkflow:
    """Coordinate the first manual weekly review workflow."""

    def __init__(
        self,
        session: Session,
        *,
        portfolio_service: PortfolioService | None = None,
        analytics_service: AnalyticsService | None = None,
        review_agent: ReviewAgent | None = None,
        markdown_exporter: WeeklyReviewMarkdownExporter | None = None,
        portfolio_repo: PortfolioRepositoryProtocol | None = None,
        review_report_repo: ReviewReportRepositoryProtocol | None = None,
        agent_log_repo: AgentDebateLogRepositoryProtocol | None = None,
        system_event_log_repo: SystemEventLogRepositoryProtocol | None = None,
    ) -> None:
        self._session = session
        self._portfolio_service = portfolio_service or PortfolioService(session)
        self._analytics_service = analytics_service or AnalyticsService()
        self._review_agent = review_agent or ManualReviewAgent()
        self._markdown_exporter = markdown_exporter or WeeklyReviewMarkdownExporter()
        self._portfolio_repo = portfolio_repo or PortfolioRepository(session)
        self._review_report_repo = review_report_repo or ReviewReportRepository(session)
        self._agent_log_repo = agent_log_repo or AgentDebateLogRepository(session)
        self._system_event_log_repo = system_event_log_repo or SystemEventLogRepository(session)

    def run(
        self,
        *,
        portfolio_id: int,
        period_start: date,
        period_end: date,
        trigger_source: str = "manual",
    ) -> WeeklyReviewWorkflowResult:
        """Run the manual weekly review workflow for one portfolio."""
        if period_start > period_end:
            msg = "period_start cannot be later than period_end."
            raise ValueError(msg)

        run_id = build_weekly_review_run_id(period_end)
        self._record_event(
            event_type="workflow_started",
            status="started",
            portfolio_id=portfolio_id,
            run_id=run_id,
            event_message="Weekly review workflow started.",
            payload_json={
                "trigger_source": trigger_source,
                "period_start": period_start,
                "period_end": period_end,
            },
            commit=True,
        )

        try:
            facts = self._build_weekly_review_facts(
                portfolio_id=portfolio_id,
                period_start=period_start,
                period_end=period_end,
            )
            tool_call_summaries = self._build_tool_call_summaries(
                period_end=period_end,
                trigger_source=trigger_source,
            )

            self._record_event(
                event_type="context_prepared",
                status="completed",
                portfolio_id=portfolio_id,
                run_id=run_id,
                event_message="Coordinator prepared structured weekly review facts.",
                payload_json={
                    "position_count": facts.position_count,
                    "valuation_point_count": facts.valuation_point_count,
                    "missing_nav_fund_codes": facts.missing_nav_fund_codes,
                },
                commit=False,
            )

            review_output = self._review_agent.review(facts)
            self._agent_log_repo.append(
                portfolio_id=portfolio_id,
                run_id=run_id,
                workflow_name=WORKFLOW_NAME,
                agent_name=self._review_agent.agent_name,
                model_name=self._review_agent.model_name,
                input_summary=self._build_agent_input_summary(facts),
                output_summary=review_output.summary,
                tool_calls_json=serialize_for_json(tool_call_summaries),
                trace_reference=self._review_agent.prompt.path.as_posix(),
            )

            report_markdown = self._markdown_exporter.render(
                facts=facts,
                review=review_output,
                run_id=run_id,
                workflow_name=WORKFLOW_NAME,
                trigger_source=trigger_source,
                prompt_reference=self._review_agent.prompt.path.as_posix(),
            )
            summary_json = self._build_report_summary_json(
                facts=facts,
                review_output=review_output,
                run_id=run_id,
                trigger_source=trigger_source,
                tool_call_summaries=tool_call_summaries,
            )
            review_report = self._review_report_repo.append(
                portfolio_id=portfolio_id,
                period_type=ReportPeriodType.WEEKLY,
                period_start=period_start,
                period_end=period_end,
                report_markdown=report_markdown,
                summary_json=summary_json,
                created_by_agent=self._review_agent.agent_name,
                run_id=run_id,
                workflow_name=WORKFLOW_NAME,
            )

            self._record_event(
                event_type="report_persisted",
                status="completed",
                portfolio_id=portfolio_id,
                run_id=run_id,
                event_message="Weekly review report persisted.",
                payload_json={"review_report_id": review_report.id},
                commit=False,
            )
            self._record_event(
                event_type="workflow_completed",
                status="completed",
                portfolio_id=portfolio_id,
                run_id=run_id,
                event_message="Weekly review workflow completed successfully.",
                payload_json={
                    "review_report_id": review_report.id,
                    "created_by_agent": self._review_agent.agent_name,
                },
                commit=False,
            )
            self._session.commit()
        except Exception as exc:
            self._session.rollback()
            self._record_failure_event(
                portfolio_id=portfolio_id,
                run_id=run_id,
                period_start=period_start,
                period_end=period_end,
                trigger_source=trigger_source,
                error=exc,
            )
            raise

        return WeeklyReviewWorkflowResult(
            run_id=run_id,
            workflow_name=WORKFLOW_NAME,
            portfolio_id=portfolio_id,
            period_start=period_start,
            period_end=period_end,
            report_record_id=review_report.id,
            report_markdown=report_markdown,
            review_output=review_output,
            facts=facts,
        )

    def _build_weekly_review_facts(
        self,
        *,
        portfolio_id: int,
        period_start: date,
        period_end: date,
    ) -> WeeklyReviewFacts:
        snapshot = self._portfolio_service.get_portfolio_snapshot(
            portfolio_id,
            as_of_date=period_end,
            workflow_name=WORKFLOW_NAME,
        )
        portfolio = self._portfolio_repo.get_by_id(portfolio_id)
        if portfolio is None:
            msg = f"Portfolio {portfolio_id} was not found while building weekly review facts."
            raise ValueError(msg)

        bounded_history = tuple(
            PortfolioValuePoint(point.as_of_date, point.market_value_amount)
            for point in snapshot.valuation_history
            if period_start <= point.as_of_date <= period_end
        )
        bounded_metrics = self._analytics_service.compute_performance_metrics(
            bounded_history,
            as_of_date=period_end,
        )

        top_weight_positions = self._build_position_highlights(
            snapshot.positions,
            sort_key=lambda position: position.weight_ratio,
            reverse=True,
        )
        top_gainers = self._build_position_highlights(
            snapshot.positions,
            sort_key=lambda position: position.unrealized_pnl_amount,
            reverse=True,
            exclude_none=True,
        )
        top_laggards = self._build_position_highlights(
            snapshot.positions,
            sort_key=lambda position: position.unrealized_pnl_amount,
            reverse=False,
            exclude_none=True,
        )

        return WeeklyReviewFacts(
            portfolio_id=portfolio.id,
            portfolio_code=portfolio.portfolio_code,
            portfolio_name=portfolio.portfolio_name,
            base_currency_code=portfolio.base_currency_code,
            period_start=period_start,
            period_end=period_end,
            latest_valuation_date=bounded_metrics.valuation_history_end_date,
            valuation_point_count=bounded_metrics.valuation_point_count,
            position_count=snapshot.position_count,
            total_cost_amount=snapshot.total_cost_amount,
            total_market_value_amount=snapshot.total_market_value_amount,
            unrealized_pnl_amount=snapshot.unrealized_pnl_amount,
            daily_return_ratio=snapshot.daily_return_ratio,
            period_return_ratio=bounded_metrics.period_return_ratio,
            monthly_return_ratio=snapshot.monthly_return_ratio,
            max_drawdown_ratio=bounded_metrics.max_drawdown_ratio,
            missing_nav_fund_codes=snapshot.missing_nav_fund_codes,
            top_weight_positions=top_weight_positions,
            top_gainers=top_gainers,
            top_laggards=top_laggards,
            accounting_assumptions_note=snapshot.accounting_assumptions_note,
        )

    def _build_position_highlights(
        self,
        positions: Sequence[Any],
        *,
        sort_key: Any,
        reverse: bool,
        exclude_none: bool = False,
    ) -> tuple[ReviewPositionFact, ...]:
        normalized_positions = [
            position
            for position in positions
            if not exclude_none or sort_key(position) is not None
        ]
        positions_with_values = [
            position for position in normalized_positions if sort_key(position) is not None
        ]
        positions_without_values = [
            position for position in normalized_positions if sort_key(position) is None
        ]
        sorted_positions = sorted(
            positions_with_values,
            key=lambda position: (sort_key(position), position.fund_code),
            reverse=reverse,
        ) + sorted(positions_without_values, key=lambda position: position.fund_code)
        highlights = [
            ReviewPositionFact(
                fund_code=position.fund_code,
                fund_name=position.fund_name,
                units=position.units,
                current_value_amount=position.current_value_amount,
                weight_ratio=position.weight_ratio,
                unrealized_pnl_amount=position.unrealized_pnl_amount,
                missing_nav=position.missing_nav,
            )
            for position in sorted_positions[:MAX_HIGHLIGHT_POSITIONS]
        ]
        return tuple(highlights)

    def _build_report_summary_json(
        self,
        *,
        facts: WeeklyReviewFacts,
        review_output: ReviewAgentOutput,
        run_id: str,
        trigger_source: str,
        tool_call_summaries: list[dict[str, str]],
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            serialize_for_json(
            {
                "summary": review_output.summary,
                "facts": facts,
                "review_output": review_output,
                "execution_metadata": {
                    "run_id": run_id,
                    "workflow_name": WORKFLOW_NAME,
                    "trigger_source": trigger_source,
                    "created_by_agent": self._review_agent.agent_name,
                    "model_name": self._review_agent.model_name,
                    "prompt_path": self._review_agent.prompt.path.as_posix(),
                    "tool_call_summaries": tool_call_summaries,
                },
            }
            ),
        )

    def _build_tool_call_summaries(
        self,
        *,
        period_end: date,
        trigger_source: str,
    ) -> list[dict[str, str]]:
        return [
            {
                "name": "PortfolioService.get_portfolio_snapshot",
                "kind": "deterministic_service",
                "as_of_date": period_end.isoformat(),
            },
            {
                "name": "AnalyticsService.compute_performance_metrics",
                "kind": "deterministic_service",
                "window": "bounded_review_period",
            },
            {
                "name": "ReviewAgent.review",
                "kind": "agent_runtime",
                "agent_name": self._review_agent.agent_name,
            },
            {
                "name": "WeeklyReviewMarkdownExporter.render",
                "kind": "report_exporter",
                "trigger_source": trigger_source,
            },
        ]

    def _build_agent_input_summary(self, facts: WeeklyReviewFacts) -> str:
        missing_nav_summary = (
            ", ".join(facts.missing_nav_fund_codes) if facts.missing_nav_fund_codes else "none"
        )
        return (
            f"portfolio={facts.portfolio_name}; "
            f"period={facts.period_start.isoformat()}..{facts.period_end.isoformat()}; "
            f"positions={facts.position_count}; "
            f"valuation_points={facts.valuation_point_count}; "
            f"missing_nav={missing_nav_summary}"
        )

    def _record_event(
        self,
        *,
        event_type: str,
        status: str,
        portfolio_id: int | None,
        run_id: str,
        event_message: str,
        payload_json: dict[str, Any],
        commit: bool,
    ) -> None:
        self._system_event_log_repo.append(
            event_type=event_type,
            status=status,
            portfolio_id=portfolio_id,
            run_id=run_id,
            workflow_name=WORKFLOW_NAME,
            event_message=event_message,
            payload_json=serialize_for_json(payload_json),
        )
        if commit:
            self._session.commit()

    def _record_failure_event(
        self,
        *,
        portfolio_id: int,
        run_id: str,
        period_start: date,
        period_end: date,
        trigger_source: str,
        error: Exception,
    ) -> None:
        try:
            self._record_event(
                event_type="workflow_failed",
                status="failed",
                portfolio_id=portfolio_id,
                run_id=run_id,
                event_message=f"{type(error).__name__}: {error}",
                payload_json={
                    "period_start": period_start,
                    "period_end": period_end,
                    "trigger_source": trigger_source,
                    "error_type": type(error).__name__,
                },
                commit=True,
            )
        except Exception:
            self._session.rollback()


def build_weekly_review_run_id(period_end: date) -> str:
    """Generate a traceable run identifier for one weekly review execution."""
    return f"weekly-review-{period_end:%Y%m%d}-{uuid4().hex[:8]}"


def run_manual_weekly_review(
    session: Session,
    *,
    portfolio_id: int,
    period_start: date,
    period_end: date,
    trigger_source: str = "manual",
) -> WeeklyReviewWorkflowResult:
    """Convenience wrapper for running the manual weekly review workflow."""
    workflow = WeeklyReviewWorkflow(session)
    return workflow.run(
        portfolio_id=portfolio_id,
        period_start=period_start,
        period_end=period_end,
        trigger_source=trigger_source,
    )


__all__ = [
    "WORKFLOW_NAME",
    "WeeklyReviewWorkflow",
    "WeeklyReviewWorkflowResult",
    "build_weekly_review_run_id",
    "run_manual_weekly_review",
    "serialize_for_json",
]
