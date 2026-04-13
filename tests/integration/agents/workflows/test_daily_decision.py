"""Integration tests for the deterministic daily decision workflow."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from fund_manager.agents.workflows import DailyDecisionWorkflow
from fund_manager.storage.models import Base, DecisionRun, FundMaster, NavSnapshot, Portfolio, PositionLot, SystemEventLog
from fund_manager.storage.repo import PortfolioPolicyRepository, PortfolioPolicyTargetCreate


def test_daily_decision_workflow_persists_decision_run_and_events(session: Session) -> None:
    portfolio, alpha_fund, beta_fund = seed_portfolio(session)
    PortfolioPolicyRepository(session).append(
        portfolio_id=portfolio.id,
        policy_name="core-balance",
        effective_from=date(2026, 3, 1),
        rebalance_threshold_ratio=Decimal("0.050000"),
        targets=(
            PortfolioPolicyTargetCreate(
                fund_id=alpha_fund.id,
                target_weight_ratio=Decimal("0.500000"),
            ),
            PortfolioPolicyTargetCreate(
                fund_id=beta_fund.id,
                target_weight_ratio=Decimal("0.500000"),
            ),
        ),
        created_by="test",
    )
    session.commit()

    result = DailyDecisionWorkflow(session).run(
        portfolio_id=portfolio.id,
        decision_date=date(2026, 3, 15),
    )

    assert result.workflow_name == "daily_decision"
    assert result.run_id.startswith("daily-decision-20260315-")
    assert result.decision.final_decision == "rebalance_required"
    assert result.decision.action_count == 2

    persisted_run = session.execute(select(DecisionRun)).scalar_one()
    assert persisted_run.id == result.decision_run_record_id
    assert persisted_run.workflow_name == "daily_decision"
    assert persisted_run.created_by_agent == "DecisionService"
    assert persisted_run.final_decision == "rebalance_required"
    assert persisted_run.actions_json is not None
    assert {action["action_type"] for action in persisted_run.actions_json} == {"add", "trim"}
    assert persisted_run.decision_summary_json is not None
    assert persisted_run.decision_summary_json["policy_name"] == "core-balance"

    event_types = [
        row.event_type
        for row in session.execute(
            select(SystemEventLog).order_by(SystemEventLog.id.asc())
        ).scalars()
    ]
    assert event_types == [
        "workflow_started",
        "decision_computed",
        "decision_persisted",
        "workflow_completed",
    ]


def test_daily_decision_workflow_records_failure_event(session: Session) -> None:
    with pytest.raises(Exception):
        DailyDecisionWorkflow(session).run(
            portfolio_id=99999,
            decision_date=date(2026, 3, 15),
        )

    failed_events = [
        row
        for row in session.execute(select(SystemEventLog).order_by(SystemEventLog.id.asc())).scalars()
        if row.event_type == "workflow_failed"
    ]
    assert len(failed_events) == 1
    assert failed_events[0].status == "failed"
    assert session.execute(select(DecisionRun)).scalars().first() is None


def seed_portfolio(session: Session) -> tuple[Portfolio, FundMaster, FundMaster]:
    portfolio = Portfolio(
        portfolio_code="main",
        portfolio_name="Main",
        is_default=True,
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
                run_id="rebuild-20260310",
                lot_key="beta-core",
                opened_on=date(2026, 3, 1),
                as_of_date=date(2026, 3, 10),
                remaining_units=Decimal("5.000000"),
                average_cost_per_unit=Decimal("2.00000000"),
                total_cost_amount=Decimal("10.0000"),
            ),
            NavSnapshot(
                fund_id=alpha_fund.id,
                nav_date=date(2026, 3, 14),
                unit_nav_amount=Decimal("1.25000000"),
                source_name="test",
            ),
            NavSnapshot(
                fund_id=beta_fund.id,
                nav_date=date(2026, 3, 14),
                unit_nav_amount=Decimal("2.00000000"),
                source_name="test",
            ),
        ]
    )
    session.commit()
    return portfolio, alpha_fund, beta_fund


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    database_path = tmp_path / "daily-decision-workflow.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    with session_factory() as db_session:
        yield db_session

    engine.dispose()
