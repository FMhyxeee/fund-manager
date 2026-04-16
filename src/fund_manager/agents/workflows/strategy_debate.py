"""Multi-agent strategy debate workflow orchestration."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from fund_manager.agents.runtime import (
    ChallengerAgent,
    JudgeAgent,
    ManualChallengerAgent,
    ManualJudgeAgent,
    ManualStrategyAgent,
    StrategyAgent,
)
from fund_manager.core.ai_artifacts import (
    ChallengerOutput,
    JudgeOutput,
    StrategyProposalOutput,
)
from fund_manager.core.domain.metrics import PortfolioValuePoint
from fund_manager.core.fact_packs import ReviewPositionFact, StrategyDebateFacts
from fund_manager.core.serialization import serialize_for_json
from fund_manager.core.services import AnalyticsService, PortfolioService
from fund_manager.storage.repo import (
    AgentDebateLogRepository,
    PortfolioRepository,
    StrategyProposalRepository,
    SystemEventLogRepository,
)
from fund_manager.storage.repo.protocols import (
    AgentDebateLogRepositoryProtocol,
    PortfolioRepositoryProtocol,
    StrategyProposalRepositoryProtocol,
    SystemEventLogRepositoryProtocol,
)

WORKFLOW_NAME = "strategy_debate"
MAX_HIGHLIGHT_POSITIONS = 3


@dataclass(frozen=True)
class StrategyDebateWorkflowResult:
    """Structured result returned after a strategy debate run completes."""

    run_id: str
    workflow_name: str
    portfolio_id: int
    period_start: date
    period_end: date
    strategy_proposal_record_id: int
    facts: StrategyDebateFacts
    strategy_output: StrategyProposalOutput
    challenger_output: ChallengerOutput
    judge_output: JudgeOutput


class StrategyDebateWorkflow:
    """Coordinate the first multi-agent strategy debate workflow."""

    def __init__(
        self,
        session: Session,
        *,
        portfolio_service: PortfolioService | None = None,
        analytics_service: AnalyticsService | None = None,
        strategy_agent: StrategyAgent | None = None,
        challenger_agent: ChallengerAgent | None = None,
        judge_agent: JudgeAgent | None = None,
        portfolio_repo: PortfolioRepositoryProtocol | None = None,
        agent_log_repo: AgentDebateLogRepositoryProtocol | None = None,
        strategy_proposal_repo: StrategyProposalRepositoryProtocol | None = None,
        system_event_log_repo: SystemEventLogRepositoryProtocol | None = None,
    ) -> None:
        self._session = session
        self._portfolio_service = portfolio_service or PortfolioService(session)
        self._analytics_service = analytics_service or AnalyticsService()
        self._strategy_agent = strategy_agent or ManualStrategyAgent()
        self._challenger_agent = challenger_agent or ManualChallengerAgent()
        self._judge_agent = judge_agent or ManualJudgeAgent()
        self._portfolio_repo = portfolio_repo or PortfolioRepository(session)
        self._agent_log_repo = agent_log_repo or AgentDebateLogRepository(session)
        self._strategy_proposal_repo = strategy_proposal_repo or StrategyProposalRepository(
            session
        )
        self._system_event_log_repo = system_event_log_repo or SystemEventLogRepository(session)

    def run(
        self,
        *,
        portfolio_id: int,
        period_start: date,
        period_end: date,
        trigger_source: str = "manual",
        created_by: str | None = None,
        idempotency_key: str | None = None,
        run_id: str | None = None,
    ) -> StrategyDebateWorkflowResult:
        """Run the strategy debate workflow for one portfolio."""
        if period_start > period_end:
            msg = "period_start cannot be later than period_end."
            raise ValueError(msg)

        resolved_run_id = run_id or build_strategy_debate_run_id(period_end)
        self._record_event(
            event_type="workflow_started",
            status="started",
            portfolio_id=portfolio_id,
            run_id=resolved_run_id,
            event_message="Strategy debate workflow started.",
            payload_json={
                "trigger_source": trigger_source,
                "created_by": created_by,
                "idempotency_key": idempotency_key,
                "period_start": period_start,
                "period_end": period_end,
            },
            commit=True,
        )

        try:
            facts = self._build_strategy_debate_facts(
                portfolio_id=portfolio_id,
                period_start=period_start,
                period_end=period_end,
            )
            self._record_event(
                event_type="context_prepared",
                status="completed",
                portfolio_id=portfolio_id,
                run_id=resolved_run_id,
                event_message="Coordinator prepared structured strategy debate facts.",
                payload_json={
                    "position_count": facts.position_count,
                    "valuation_point_count": facts.valuation_point_count,
                    "missing_nav_fund_codes": facts.missing_nav_fund_codes,
                },
                commit=False,
            )

            strategy_output = self._strategy_agent.propose(facts)
            self._append_agent_log(
                portfolio_id=portfolio_id,
                run_id=resolved_run_id,
                agent_name=self._strategy_agent.agent_name,
                model_name=self._strategy_agent.model_name,
                prompt_path=self._strategy_agent.prompt.path.as_posix(),
                input_summary=self._build_facts_input_summary(facts),
                output_summary=strategy_output.summary,
                tool_calls_json=self._build_tool_call_summaries(
                    trigger_source=trigger_source,
                    agent_name=self._strategy_agent.agent_name,
                ),
            )

            challenger_output = self._challenger_agent.challenge(facts, strategy_output)
            self._append_agent_log(
                portfolio_id=portfolio_id,
                run_id=resolved_run_id,
                agent_name=self._challenger_agent.agent_name,
                model_name=self._challenger_agent.model_name,
                prompt_path=self._challenger_agent.prompt.path.as_posix(),
                input_summary=self._build_challenger_input_summary(facts, strategy_output),
                output_summary=challenger_output.summary,
                tool_calls_json=self._build_tool_call_summaries(
                    trigger_source=trigger_source,
                    agent_name=self._challenger_agent.agent_name,
                ),
            )

            judge_output = self._judge_agent.judge(facts, strategy_output, challenger_output)
            self._append_agent_log(
                portfolio_id=portfolio_id,
                run_id=resolved_run_id,
                agent_name=self._judge_agent.agent_name,
                model_name=self._judge_agent.model_name,
                prompt_path=self._judge_agent.prompt.path.as_posix(),
                input_summary=self._build_judge_input_summary(strategy_output, challenger_output),
                output_summary=judge_output.summary,
                tool_calls_json=self._build_tool_call_summaries(
                    trigger_source=trigger_source,
                    agent_name=self._judge_agent.agent_name,
                ),
            )

            strategy_proposal = self._strategy_proposal_repo.append(
                portfolio_id=portfolio_id,
                proposal_date=period_end,
                thesis=judge_output.thesis,
                evidence_json=serialize_for_json(
                    {
                        "facts": facts,
                        "strategy_output": strategy_output,
                        "challenger_output": challenger_output,
                        "judge_output": judge_output,
                        "execution_metadata": {
                            "run_id": resolved_run_id,
                            "workflow_name": WORKFLOW_NAME,
                            "trigger_source": trigger_source,
                            "created_by": created_by,
                            "idempotency_key": idempotency_key,
                            "prompt_paths": {
                                "strategy": self._strategy_agent.prompt.path.as_posix(),
                                "challenger": self._challenger_agent.prompt.path.as_posix(),
                                "judge": self._judge_agent.prompt.path.as_posix(),
                            },
                        },
                    }
                ),
                recommended_actions_json=serialize_for_json(
                    [asdict(action) for action in judge_output.proposed_actions]
                ),
                risk_notes="\n".join(strategy_output.risks),
                counterarguments="\n".join(judge_output.counterarguments),
                final_decision=judge_output.final_judgment,
                confidence_score=judge_output.confidence_score,
                created_by_agent=self._judge_agent.agent_name,
                run_id=resolved_run_id,
                workflow_name=WORKFLOW_NAME,
            )

            self._record_event(
                event_type="proposal_persisted",
                status="completed",
                portfolio_id=portfolio_id,
                run_id=resolved_run_id,
                event_message="Final strategy proposal persisted.",
                payload_json={"strategy_proposal_id": strategy_proposal.id},
                commit=False,
            )
            self._record_event(
                event_type="workflow_completed",
                status="completed",
                portfolio_id=portfolio_id,
                run_id=resolved_run_id,
                event_message="Strategy debate workflow completed successfully.",
                payload_json={
                    "strategy_proposal_id": strategy_proposal.id,
                    "created_by_agent": self._judge_agent.agent_name,
                    "final_decision": judge_output.final_judgment,
                    "created_by": created_by,
                    "idempotency_key": idempotency_key,
                },
                commit=False,
            )
            self._session.commit()
        except Exception as exc:
            self._session.rollback()
            self._record_failure_event(
                portfolio_id=portfolio_id,
                run_id=resolved_run_id,
                period_start=period_start,
                period_end=period_end,
                trigger_source=trigger_source,
                created_by=created_by,
                idempotency_key=idempotency_key,
                error=exc,
            )
            raise

        return StrategyDebateWorkflowResult(
            run_id=resolved_run_id,
            workflow_name=WORKFLOW_NAME,
            portfolio_id=portfolio_id,
            period_start=period_start,
            period_end=period_end,
            strategy_proposal_record_id=strategy_proposal.id,
            facts=facts,
            strategy_output=strategy_output,
            challenger_output=challenger_output,
            judge_output=judge_output,
        )

    def _build_strategy_debate_facts(
        self,
        *,
        portfolio_id: int,
        period_start: date,
        period_end: date,
    ) -> StrategyDebateFacts:
        snapshot = self._portfolio_service.get_portfolio_snapshot(
            portfolio_id,
            as_of_date=period_end,
            workflow_name=WORKFLOW_NAME,
        )
        portfolio = self._portfolio_repo.get_by_id(portfolio_id)
        if portfolio is None:
            msg = (
                f"Portfolio {portfolio_id} was not found while building strategy debate facts."
            )
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

        return StrategyDebateFacts(
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
            period_return_ratio=bounded_metrics.period_return_ratio,
            weekly_return_ratio=snapshot.weekly_return_ratio,
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

    def _append_agent_log(
        self,
        *,
        portfolio_id: int,
        run_id: str,
        agent_name: str,
        model_name: str | None,
        prompt_path: str,
        input_summary: str,
        output_summary: str,
        tool_calls_json: list[dict[str, str]],
    ) -> None:
        self._agent_log_repo.append(
            portfolio_id=portfolio_id,
            run_id=run_id,
            workflow_name=WORKFLOW_NAME,
            agent_name=agent_name,
            model_name=model_name,
            input_summary=input_summary,
            output_summary=output_summary,
            tool_calls_json=serialize_for_json(tool_calls_json),
            trace_reference=prompt_path,
        )

    def _build_tool_call_summaries(
        self,
        *,
        trigger_source: str,
        agent_name: str,
    ) -> list[dict[str, str]]:
        return [
            {
                "name": "PortfolioService.get_portfolio_snapshot",
                "kind": "deterministic_service",
            },
            {
                "name": "AnalyticsService.compute_performance_metrics",
                "kind": "deterministic_service",
            },
            {
                "name": agent_name,
                "kind": "agent_runtime",
            },
            {
                "name": "StrategyProposalRepository.append",
                "kind": "persistence",
                "trigger_source": trigger_source,
            },
        ]

    def _build_facts_input_summary(self, facts: StrategyDebateFacts) -> str:
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

    def _build_challenger_input_summary(
        self,
        facts: StrategyDebateFacts,
        strategy_output: StrategyProposalOutput,
    ) -> str:
        return (
            self._build_facts_input_summary(facts)
            + f"; strategy_actions={len(strategy_output.proposed_actions)}"
        )

    def _build_judge_input_summary(
        self,
        strategy_output: StrategyProposalOutput,
        challenger_output: ChallengerOutput,
    ) -> str:
        return (
            f"strategy_actions={len(strategy_output.proposed_actions)}; "
            f"critique_points={len(challenger_output.critique_points)}; "
            f"counterarguments={len(challenger_output.counterarguments)}"
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
        created_by: str | None,
        idempotency_key: str | None,
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
                    "created_by": created_by,
                    "idempotency_key": idempotency_key,
                    "error_type": type(error).__name__,
                },
                commit=True,
            )
        except Exception:
            self._session.rollback()


def build_strategy_debate_run_id(period_end: date) -> str:
    """Generate a traceable run identifier for one strategy debate execution."""
    return f"strategy-debate-{period_end:%Y%m%d}-{uuid4().hex[:8]}"


def run_strategy_debate(
    session: Session,
    *,
    portfolio_id: int,
    period_start: date,
    period_end: date,
    trigger_source: str = "manual",
) -> StrategyDebateWorkflowResult:
    """Convenience wrapper for running the strategy debate workflow."""
    workflow = StrategyDebateWorkflow(session)
    return workflow.run(
        portfolio_id=portfolio_id,
        period_start=period_start,
        period_end=period_end,
        trigger_source=trigger_source,
    )


__all__ = [
    "MAX_HIGHLIGHT_POSITIONS",
    "WORKFLOW_NAME",
    "StrategyDebateWorkflow",
    "StrategyDebateWorkflowResult",
    "build_strategy_debate_run_id",
    "run_strategy_debate",
]
