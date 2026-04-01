"""Integration tests for the manual weekly review workflow."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from fund_manager.agents.workflows import WeeklyReviewWorkflow
from fund_manager.storage.models import (
    AgentDebateLog,
    Base,
    FundMaster,
    NavSnapshot,
    Portfolio,
    PositionLot,
    ReportPeriodType,
    ReviewReport,
    SystemEventLog,
)


def test_weekly_review_workflow_persists_report_and_trace_logs(session: Session) -> None:
    portfolio = seed_portfolio_with_valuation_history(session)

    workflow = WeeklyReviewWorkflow(session)
    result = workflow.run(
        portfolio_id=portfolio.id,
        period_start=date(2026, 3, 8),
        period_end=date(2026, 3, 15),
    )

    assert result.workflow_name == "weekly_review"
    assert result.report_record_id > 0
    assert result.review_output.summary
    assert result.facts.period_return_ratio == Decimal("0.139456")
    assert "# Weekly Review" in result.report_markdown
    assert "## Summary" in result.report_markdown
    assert "## Traceability" in result.report_markdown
    assert result.run_id.startswith("weekly-review-20260315-")

    persisted_report = session.execute(select(ReviewReport)).scalar_one()
    assert persisted_report.id == result.report_record_id
    assert persisted_report.period_type is ReportPeriodType.WEEKLY
    assert persisted_report.workflow_name == "weekly_review"
    assert persisted_report.created_by_agent == "ReviewAgent"
    assert persisted_report.report_markdown == result.report_markdown
    assert persisted_report.summary_json is not None
    assert persisted_report.summary_json["execution_metadata"]["trigger_source"] == "manual"
    assert persisted_report.summary_json["facts"]["period_start"] == "2026-03-08"
    assert (
        persisted_report.summary_json["review_output"]["summary"] == result.review_output.summary
    )

    agent_log = session.execute(select(AgentDebateLog)).scalar_one()
    assert agent_log.run_id == result.run_id
    assert agent_log.workflow_name == "weekly_review"
    assert agent_log.agent_name == "ReviewAgent"
    assert agent_log.model_name == "manual-review-agent-v1"
    assert agent_log.trace_reference.endswith("agents/prompts/review_agent.md")

    event_types = [
        row.event_type
        for row in session.execute(
            select(SystemEventLog).order_by(SystemEventLog.id.asc())
        ).scalars()
    ]
    assert event_types == [
        "workflow_started",
        "context_prepared",
        "report_persisted",
        "workflow_completed",
    ]


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
    database_path = tmp_path / "weekly-review.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    with session_factory() as db_session:
        yield db_session

    engine.dispose()
