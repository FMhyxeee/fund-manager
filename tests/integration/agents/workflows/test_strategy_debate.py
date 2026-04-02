"""Integration tests for the multi-agent strategy debate workflow."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from fund_manager.agents.runtime.challenger_agent import (
    ChallengerOutput,
    ManualChallengerAgent,
)
from fund_manager.agents.runtime.judge_agent import (
    JudgeOutput,
    ManualJudgeAgent,
)
from fund_manager.agents.runtime.review_agent import PromptDefinition
from fund_manager.agents.runtime.strategy_agent import (
    ManualStrategyAgent,
    StrategyDebateFacts,
    StrategyProposalOutput,
)
from fund_manager.agents.workflows import StrategyDebateWorkflow
from fund_manager.storage.models import (
    AgentDebateLog,
    Base,
    FundMaster,
    NavSnapshot,
    Portfolio,
    PositionLot,
    StrategyProposal,
    SystemEventLog,
)


def test_strategy_debate_workflow_persists_logs_and_strategy_proposal(session: Session) -> None:
    portfolio = seed_portfolio_with_valuation_history(session)

    workflow = StrategyDebateWorkflow(session)
    result = workflow.run(
        portfolio_id=portfolio.id,
        period_start=date(2026, 3, 8),
        period_end=date(2026, 3, 15),
    )

    assert result.workflow_name == "strategy_debate"
    assert result.strategy_proposal_record_id > 0
    assert result.run_id.startswith("strategy-debate-20260315-")
    assert result.strategy_output.proposed_actions
    assert result.challenger_output.critique_points
    assert result.judge_output.final_judgment == "monitor_with_concentration_review"

    persisted_proposal = session.execute(select(StrategyProposal)).scalar_one()
    assert persisted_proposal.id == result.strategy_proposal_record_id
    assert persisted_proposal.workflow_name == "strategy_debate"
    assert persisted_proposal.created_by_agent == "JudgeAgent"
    assert persisted_proposal.final_decision == "monitor_with_concentration_review"
    assert persisted_proposal.confidence_score == Decimal("0.6500")
    assert persisted_proposal.thesis == result.judge_output.thesis
    assert persisted_proposal.evidence_json is not None
    assert persisted_proposal.evidence_json["execution_metadata"]["run_id"] == result.run_id
    assert (
        persisted_proposal.evidence_json["strategy_output"]["summary"]
        == result.strategy_output.summary
    )
    assert persisted_proposal.recommended_actions_json is not None
    assert persisted_proposal.recommended_actions_json[0]["priority"] == "high"

    agent_logs = (
        session.execute(select(AgentDebateLog).order_by(AgentDebateLog.id.asc())).scalars().all()
    )
    assert [log.agent_name for log in agent_logs] == [
        "StrategyAgent",
        "ChallengerAgent",
        "JudgeAgent",
    ]
    assert agent_logs[0].trace_reference.endswith("agents/prompts/strategy_agent.md")
    assert agent_logs[1].trace_reference.endswith("agents/prompts/challenger_agent.md")
    assert agent_logs[2].trace_reference.endswith("agents/prompts/judge_agent.md")
    assert all(log.run_id == result.run_id for log in agent_logs)

    event_types = [
        row.event_type
        for row in session.execute(
            select(SystemEventLog).order_by(SystemEventLog.id.asc())
        ).scalars()
    ]
    assert event_types == [
        "workflow_started",
        "context_prepared",
        "proposal_persisted",
        "workflow_completed",
    ]


def test_strategy_debate_challenger_output_does_not_restate_proposal(session: Session) -> None:
    portfolio = seed_portfolio_with_valuation_history(session)

    workflow = StrategyDebateWorkflow(session)
    result = workflow.run(
        portfolio_id=portfolio.id,
        period_start=date(2026, 3, 8),
        period_end=date(2026, 3, 15),
    )

    proposal_action_texts = {
        action.action.lower() for action in result.strategy_output.proposed_actions
    }
    assert all(
        critique.lower() not in proposal_action_texts
        for critique in result.challenger_output.critique_points
    )
    assert result.strategy_output.thesis.lower() not in {
        critique.lower() for critique in result.challenger_output.critique_points
    }


def test_strategy_debate_rejects_invalid_period_range(session: Session) -> None:
    portfolio = seed_portfolio_with_valuation_history(session)
    workflow = StrategyDebateWorkflow(session)

    with pytest.raises(ValueError, match="period_start cannot be later than period_end"):
        workflow.run(
            portfolio_id=portfolio.id,
            period_start=date(2026, 3, 15),
            period_end=date(2026, 3, 8),
        )


def test_strategy_debate_records_failure_event_for_missing_portfolio(session: Session) -> None:
    workflow = StrategyDebateWorkflow(session)

    with pytest.raises(Exception):
        workflow.run(
            portfolio_id=99999,
            period_start=date(2026, 3, 8),
            period_end=date(2026, 3, 15),
        )

    events = (
        session.execute(select(SystemEventLog).order_by(SystemEventLog.id.asc())).scalars().all()
    )
    started_events = [e for e in events if e.event_type == "workflow_started"]
    failed_events = [e for e in events if e.event_type == "workflow_failed"]
    assert len(started_events) == 1
    assert len(failed_events) == 1
    assert failed_events[0].status == "failed"
    assert failed_events[0].portfolio_id == 99999

    assert session.execute(select(StrategyProposal)).scalars().first() is None
    assert session.execute(select(AgentDebateLog)).scalars().first() is None


def test_strategy_debate_rolls_back_on_agent_failure(session: Session) -> None:
    portfolio = seed_portfolio_with_valuation_history(session)

    class FailingStrategyAgent:
        @property
        def agent_name(self) -> str:
            return "FailingStrategyAgent"

        @property
        def model_name(self) -> str:
            return "failing-v1"

        @property
        def prompt(self) -> PromptDefinition:
            return ManualStrategyAgent().prompt

        def propose(self, facts: StrategyDebateFacts) -> StrategyProposalOutput:
            raise RuntimeError("Intentional agent failure for testing")

    workflow = StrategyDebateWorkflow(
        session,
        strategy_agent=FailingStrategyAgent(),
        challenger_agent=ManualChallengerAgent(),
        judge_agent=ManualJudgeAgent(),
    )

    with pytest.raises(RuntimeError, match="Intentional agent failure"):
        workflow.run(
            portfolio_id=portfolio.id,
            period_start=date(2026, 3, 8),
            period_end=date(2026, 3, 15),
        )

    assert session.execute(select(StrategyProposal)).scalars().first() is None

    failed_events = [
        e
        for e in session.execute(select(SystemEventLog)).scalars()
        if e.event_type == "workflow_failed"
    ]
    assert len(failed_events) == 1
    assert "RuntimeError" in (failed_events[0].event_message or "")


def test_strategy_debate_passes_same_evidence_base_to_all_agents(session: Session) -> None:
    captured_facts: list[StrategyDebateFacts] = []

    class CapturingStrategyAgent:
        @property
        def agent_name(self) -> str:
            return "CapturingStrategyAgent"

        @property
        def model_name(self) -> str:
            return "capturing-v1"

        @property
        def prompt(self) -> PromptDefinition:
            return ManualStrategyAgent().prompt

        def propose(self, facts: StrategyDebateFacts) -> StrategyProposalOutput:
            captured_facts.append(facts)
            return ManualStrategyAgent().propose(facts)

    class CapturingChallengerAgent:
        @property
        def agent_name(self) -> str:
            return "CapturingChallengerAgent"

        @property
        def model_name(self) -> str:
            return "capturing-v1"

        @property
        def prompt(self) -> PromptDefinition:
            return ManualChallengerAgent().prompt

        def challenge(
            self, facts: StrategyDebateFacts, proposal: StrategyProposalOutput
        ) -> ChallengerOutput:
            captured_facts.append(facts)
            return ManualChallengerAgent().challenge(facts, proposal)

    class CapturingJudgeAgent:
        @property
        def agent_name(self) -> str:
            return "CapturingJudgeAgent"

        @property
        def model_name(self) -> str:
            return "capturing-v1"

        @property
        def prompt(self) -> PromptDefinition:
            return ManualJudgeAgent().prompt

        def judge(
            self,
            facts: StrategyDebateFacts,
            proposal: StrategyProposalOutput,
            challenge: ChallengerOutput,
        ) -> JudgeOutput:
            captured_facts.append(facts)
            return ManualJudgeAgent().judge(facts, proposal, challenge)

    portfolio = seed_portfolio_with_valuation_history(session)
    workflow = StrategyDebateWorkflow(
        session,
        strategy_agent=CapturingStrategyAgent(),
        challenger_agent=CapturingChallengerAgent(),
        judge_agent=CapturingJudgeAgent(),
    )
    workflow.run(
        portfolio_id=portfolio.id,
        period_start=date(2026, 3, 8),
        period_end=date(2026, 3, 15),
    )

    assert len(captured_facts) == 3
    assert captured_facts[0] == captured_facts[1] == captured_facts[2]
    assert captured_facts[0].portfolio_id == portfolio.id
    assert captured_facts[0].period_start == date(2026, 3, 8)
    assert captured_facts[0].period_end == date(2026, 3, 15)


def test_strategy_debate_creates_distinct_append_only_proposals_on_repeated_runs(
    session: Session,
) -> None:
    portfolio = seed_portfolio_with_valuation_history(session)
    workflow = StrategyDebateWorkflow(session)

    result_a = workflow.run(
        portfolio_id=portfolio.id,
        period_start=date(2026, 3, 8),
        period_end=date(2026, 3, 15),
    )
    result_b = workflow.run(
        portfolio_id=portfolio.id,
        period_start=date(2026, 3, 8),
        period_end=date(2026, 3, 15),
    )

    assert result_a.run_id != result_b.run_id
    assert result_a.strategy_proposal_record_id != result_b.strategy_proposal_record_id

    all_proposals = (
        session.execute(select(StrategyProposal).order_by(StrategyProposal.id.asc()))
        .scalars()
        .all()
    )
    assert len(all_proposals) == 2
    assert all_proposals[0].id == result_a.strategy_proposal_record_id
    assert all_proposals[1].id == result_b.strategy_proposal_record_id

    all_logs = (
        session.execute(select(AgentDebateLog).order_by(AgentDebateLog.id.asc())).scalars().all()
    )
    assert len(all_logs) == 6
    run_a_logs = [log for log in all_logs if log.run_id == result_a.run_id]
    run_b_logs = [log for log in all_logs if log.run_id == result_b.run_id]
    assert len(run_a_logs) == 3
    assert len(run_b_logs) == 3


def test_strategy_debate_handles_missing_nav_gracefully(session: Session) -> None:
    portfolio = seed_portfolio_without_nav(session)
    workflow = StrategyDebateWorkflow(session)

    result = workflow.run(
        portfolio_id=portfolio.id,
        period_start=date(2026, 3, 8),
        period_end=date(2026, 3, 15),
    )

    assert result.facts.missing_nav_fund_codes
    assert result.strategy_output.confidence_level == "low"
    assert result.challenger_output.confidence_level == "low"
    assert result.judge_output.confidence_level == "low"
    assert result.judge_output.final_judgment == "defer_until_complete_data"
    assert result.judge_output.confidence_score == Decimal("0.3500")

    persisted_proposal = session.execute(select(StrategyProposal)).scalar_one()
    assert persisted_proposal.final_decision == "defer_until_complete_data"
    assert persisted_proposal.confidence_score == Decimal("0.3500")


def test_strategy_debate_records_full_event_lifecycle(session: Session) -> None:
    portfolio = seed_portfolio_with_valuation_history(session)
    workflow = StrategyDebateWorkflow(session)

    workflow.run(
        portfolio_id=portfolio.id,
        period_start=date(2026, 3, 8),
        period_end=date(2026, 3, 15),
    )

    events = (
        session.execute(select(SystemEventLog).order_by(SystemEventLog.id.asc())).scalars().all()
    )
    event_types = [e.event_type for e in events]
    assert event_types == [
        "workflow_started",
        "context_prepared",
        "proposal_persisted",
        "workflow_completed",
    ]

    assert all(e.status == "completed" for e in events if e.event_type != "workflow_started")
    assert events[0].status == "started"
    assert events[0].portfolio_id == portfolio.id
    assert events[0].workflow_name == "strategy_debate"


def test_strategy_debate_run_id_contains_period_end_date(session: Session) -> None:
    portfolio = seed_portfolio_with_valuation_history(session)
    workflow = StrategyDebateWorkflow(session)

    result = workflow.run(
        portfolio_id=portfolio.id,
        period_start=date(2026, 3, 8),
        period_end=date(2026, 4, 1),
    )

    assert "20260401" in result.run_id
    assert result.run_id.startswith("strategy-debate-20260401-")


def test_strategy_debate_proposal_contains_debate_evidence_json(session: Session) -> None:
    portfolio = seed_portfolio_with_valuation_history(session)
    workflow = StrategyDebateWorkflow(session)

    result = workflow.run(
        portfolio_id=portfolio.id,
        period_start=date(2026, 3, 8),
        period_end=date(2026, 3, 15),
    )

    proposal = session.execute(select(StrategyProposal)).scalar_one()
    evidence = proposal.evidence_json
    assert evidence is not None
    assert "strategy_output" in evidence
    assert "challenger_output" in evidence
    assert "judge_output" in evidence
    assert "execution_metadata" in evidence
    assert evidence["execution_metadata"]["workflow_name"] == "strategy_debate"
    assert evidence["execution_metadata"]["prompt_paths"]["strategy"].endswith("strategy_agent.md")
    assert evidence["execution_metadata"]["prompt_paths"]["challenger"].endswith(
        "challenger_agent.md"
    )
    assert evidence["execution_metadata"]["prompt_paths"]["judge"].endswith("judge_agent.md")


def seed_portfolio_without_nav(session: Session) -> Portfolio:
    portfolio = Portfolio(
        portfolio_code="no-nav",
        portfolio_name="No NAV Portfolio",
    )
    fund = FundMaster(
        fund_code="000099",
        fund_name="Missing NAV Fund",
        source_name="test",
    )
    session.add_all([portfolio, fund])
    session.flush()

    session.add(
        PositionLot(
            portfolio_id=portfolio.id,
            fund_id=fund.id,
            run_id="rebuild-no-nav",
            lot_key="no-nav-lot",
            opened_on=date(2026, 3, 1),
            as_of_date=date(2026, 3, 10),
            remaining_units=Decimal("100.000000"),
            average_cost_per_unit=Decimal("1.00000000"),
            total_cost_amount=Decimal("100.0000"),
        )
    )
    session.commit()
    return portfolio


def seed_portfolio_with_valuation_history(session: Session) -> Portfolio:
    portfolio = Portfolio(
        portfolio_code="main",
        portfolio_name="Main",
    )
    alpha_fund = FundMaster(
        fund_code="000001",
        fund_name="Alpha Fund",
        source_name="test",
    )
    beta_fund = FundMaster(
        fund_code="000002",
        fund_name="Beta Fund",
        source_name="test",
    )
    session.add_all([portfolio, alpha_fund, beta_fund])
    session.flush()

    session.add_all(
        [
            PositionLot(
                portfolio_id=portfolio.id,
                fund_id=alpha_fund.id,
                run_id="rebuild-20260301",
                lot_key="alpha-core",
                opened_on=date(2026, 3, 1),
                as_of_date=date(2026, 3, 1),
                remaining_units=Decimal("10.000000"),
                average_cost_per_unit=Decimal("1.00000000"),
                total_cost_amount=Decimal("10.0000"),
            ),
            PositionLot(
                portfolio_id=portfolio.id,
                fund_id=alpha_fund.id,
                run_id="rebuild-20260310",
                lot_key="alpha-core",
                opened_on=date(2026, 3, 1),
                as_of_date=date(2026, 3, 10),
                remaining_units=Decimal("12.000000"),
                average_cost_per_unit=Decimal("1.00000000"),
                total_cost_amount=Decimal("12.0000"),
            ),
            PositionLot(
                portfolio_id=portfolio.id,
                fund_id=beta_fund.id,
                run_id="rebuild-20260301",
                lot_key="beta-core",
                opened_on=date(2026, 3, 1),
                as_of_date=date(2026, 3, 1),
                remaining_units=Decimal("5.000000"),
                average_cost_per_unit=Decimal("3.00000000"),
                total_cost_amount=Decimal("15.0000"),
            ),
            NavSnapshot(
                fund_id=alpha_fund.id,
                nav_date=date(2026, 3, 1),
                unit_nav_amount=Decimal("1.00000000"),
                source_name="test",
            ),
            NavSnapshot(
                fund_id=alpha_fund.id,
                nav_date=date(2026, 3, 10),
                unit_nav_amount=Decimal("1.20000000"),
                source_name="test",
            ),
            NavSnapshot(
                fund_id=alpha_fund.id,
                nav_date=date(2026, 3, 14),
                unit_nav_amount=Decimal("1.50000000"),
                source_name="test",
            ),
            NavSnapshot(
                fund_id=beta_fund.id,
                nav_date=date(2026, 3, 1),
                unit_nav_amount=Decimal("3.00000000"),
                source_name="test",
            ),
            NavSnapshot(
                fund_id=beta_fund.id,
                nav_date=date(2026, 3, 12),
                unit_nav_amount=Decimal("3.20000000"),
                source_name="test",
            ),
            NavSnapshot(
                fund_id=beta_fund.id,
                nav_date=date(2026, 3, 14),
                unit_nav_amount=Decimal("3.10000000"),
                source_name="test",
            ),
        ]
    )
    session.commit()
    return portfolio


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    database_path = tmp_path / "strategy-debate.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    with session_factory() as db_session:
        yield db_session

    engine.dispose()
