"""Tests for the MCP-oriented fund-manager service layer."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from fund_manager.mcp.service import FundManagerMCPService, ModelAllocation
from fund_manager.storage.models import Base, FundMaster, NavSnapshot, Portfolio, PositionLot


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    database_path = tmp_path / "mcp-service.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    with session_factory() as db_session:
        yield db_session

    engine.dispose()


def test_mcp_service_lists_snapshot_and_nav_history(session: Session) -> None:
    seed_portfolio_with_history(session)
    service = FundManagerMCPService(session)

    portfolios = service.list_portfolios()
    snapshot = service.get_portfolio_snapshot(portfolio_name="Main", as_of_date=date(2026, 3, 15))
    nav_history = service.get_fund_nav_history(
        fund_code="000001",
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 14),
    )
    valuation_history = service.get_portfolio_valuation_history(
        portfolio_name="Main",
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 15),
    )

    assert portfolios["portfolios"][0]["portfolio_name"] == "Main"
    assert snapshot["snapshot"]["total_market_value_amount"] == "33.5000"
    assert nav_history["fund"]["fund_name"] == "Alpha Fund"
    assert len(nav_history["points"]) == 3
    assert valuation_history["valuation_history"][0]["as_of_date"] == "2026-03-01"


def test_mcp_service_compact_metrics_and_simulation(session: Session) -> None:
    seed_portfolio_with_history(session)
    service = FundManagerMCPService(session)

    metrics = service.get_portfolio_metrics(
        portfolio_name="Main",
        as_of_date=date(2026, 3, 15),
    )
    simulation = service.simulate_model_portfolio(
        allocations=(
            ModelAllocation(fund_code="000001", weight=Decimal("0.6")),
            ModelAllocation(fund_code="000002", weight=Decimal("0.4")),
        ),
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 14),
        rebalance="monthly",
    )

    assert metrics["metrics"]["position_count"] == 2
    assert metrics["metrics"]["top_positions"][0]["fund_code"] == "000001"
    assert simulation["allocations"][0]["weight"] == "0.600000"
    assert simulation["valuation_history"][0]["market_value_amount"] == "1.0000"
    assert simulation["metrics"]["period_return_ratio"] is not None


def seed_portfolio_with_history(session: Session) -> None:
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
                daily_return_ratio=Decimal("0"),
                source_name="test",
            ),
            NavSnapshot(
                fund_id=alpha_fund.id,
                nav_date=date(2026, 3, 10),
                unit_nav_amount=Decimal("1.20000000"),
                daily_return_ratio=Decimal("0.200000"),
                source_name="test",
            ),
            NavSnapshot(
                fund_id=alpha_fund.id,
                nav_date=date(2026, 3, 14),
                unit_nav_amount=Decimal("1.50000000"),
                daily_return_ratio=Decimal("0.250000"),
                source_name="test",
            ),
            NavSnapshot(
                fund_id=beta_fund.id,
                nav_date=date(2026, 3, 1),
                unit_nav_amount=Decimal("3.00000000"),
                daily_return_ratio=Decimal("0"),
                source_name="test",
            ),
            NavSnapshot(
                fund_id=beta_fund.id,
                nav_date=date(2026, 3, 12),
                unit_nav_amount=Decimal("3.20000000"),
                daily_return_ratio=Decimal("0.066667"),
                source_name="test",
            ),
            NavSnapshot(
                fund_id=beta_fund.id,
                nav_date=date(2026, 3, 14),
                unit_nav_amount=Decimal("3.10000000"),
                daily_return_ratio=Decimal("-0.031250"),
                source_name="test",
            ),
        ]
    )
    session.commit()
