"""Integration tests for agent-facing portfolio tools."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from fund_manager.agents.tools import PortfolioSummaryDTO, PortfolioTools
from fund_manager.storage.models import (
    Base,
    FundMaster,
    NavSnapshot,
    Portfolio,
    PositionLot,
    ReviewReport,
)


def test_portfolio_tools_list_and_read_snapshot_by_name(session: Session) -> None:
    portfolio = seed_portfolio_with_valuation_history(session)
    tools = PortfolioTools(session)

    portfolios = tools.list_portfolios()
    assert portfolios == (
        PortfolioSummaryDTO(
            portfolio_id=portfolio.id,
            portfolio_code="main",
            portfolio_name="Main",
            base_currency_code="CNY",
            is_default=False,
        ),
    )

    snapshot_payload = tools.get_portfolio_snapshot(
        portfolio_name="Main",
        as_of_date=date(2026, 3, 15),
    )
    assert snapshot_payload["portfolio"]["portfolio_id"] == portfolio.id
    assert snapshot_payload["snapshot"]["portfolio_name"] == "Main"
    assert snapshot_payload["snapshot"]["total_market_value_amount"] == "33.5000"
    assert snapshot_payload["snapshot"]["missing_nav_fund_codes"] == []

    position_payload = tools.get_position_breakdown(
        portfolio_name="Main",
        as_of_date=date(2026, 3, 15),
    )
    assert position_payload["as_of_date"] == "2026-03-15"
    assert len(position_payload["positions"]) == 2
    assert position_payload["positions"][0]["fund_code"] == "000001"
    assert position_payload["positions"][1]["weight_ratio"] == "0.462687"


def test_portfolio_tools_run_weekly_review_returns_json_safe_result(session: Session) -> None:
    portfolio = seed_portfolio_with_valuation_history(session)
    tools = PortfolioTools(session)

    result = tools.run_weekly_review(
        portfolio_id=portfolio.id,
        period_start=date(2026, 3, 8),
        period_end=date(2026, 3, 15),
    )

    assert result["workflow_name"] == "weekly_review"
    assert result["portfolio_id"] == portfolio.id
    assert result["period_start"] == "2026-03-08"
    assert result["facts"]["period_return_ratio"] == "0.139456"
    assert result["review_output"]["summary"]
    assert result["report_markdown"].startswith("# Weekly Review")

    persisted_report = session.execute(select(ReviewReport)).scalar_one()
    assert persisted_report.id == result["report_record_id"]
    assert persisted_report.run_id == result["run_id"]


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
    database_path = tmp_path / "portfolio-tools.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    with session_factory() as db_session:
        yield db_session

    engine.dispose()
