"""Integration tests for the storage-backed portfolio service."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from fund_manager.core.services import PortfolioService
from fund_manager.storage.models import Base, FundMaster, NavSnapshot, Portfolio, PositionLot


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    database_path = tmp_path / "portfolio-service.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    with session_factory() as db_session:
        yield db_session

    engine.dispose()


def test_portfolio_service_assembles_snapshot(session: Session) -> None:
    portfolio, alpha_fund, beta_fund = seed_two_fund_portfolio(session)

    snapshot = PortfolioService(session).get_portfolio_snapshot(
        portfolio.id,
        as_of_date=date(2026, 3, 15),
    )

    assert snapshot.portfolio_name == "Main"
    assert snapshot.position_count == 2
    assert snapshot.total_cost_amount == Decimal("27.0000")
    assert snapshot.total_market_value_amount == Decimal("33.5000")
    assert snapshot.unrealized_pnl_amount == Decimal("6.5000")
    assert snapshot.daily_return_ratio == Decimal("0.101974")
    assert snapshot.weekly_return_ratio == Decimal("0.139456")
    assert snapshot.monthly_return_ratio == Decimal("0.340000")
    assert snapshot.max_drawdown_ratio == Decimal("0.000000")
    assert snapshot.valuation_history_end_date == date(2026, 3, 14)
    assert [point.as_of_date for point in snapshot.valuation_history] == [
        date(2026, 3, 1),
        date(2026, 3, 10),
        date(2026, 3, 12),
        date(2026, 3, 14),
    ]

    alpha_position, beta_position = snapshot.positions
    assert alpha_position.fund_id == alpha_fund.id
    assert alpha_position.units == Decimal("12.000000")
    assert alpha_position.current_value_amount == Decimal("18.0000")
    assert alpha_position.weight_ratio == Decimal("0.537313")
    assert beta_position.fund_id == beta_fund.id
    assert beta_position.current_value_amount == Decimal("15.5000")
    assert beta_position.weight_ratio == Decimal("0.462687")


def test_portfolio_service_surfaces_missing_nav_explicitly(session: Session) -> None:
    portfolio = Portfolio(portfolio_code="main", portfolio_name="Main")
    alpha_fund = FundMaster(fund_code="000001", fund_name="Alpha Fund", source_name="test")
    beta_fund = FundMaster(fund_code="000002", fund_name="Beta Fund", source_name="test")
    session.add_all([portfolio, alpha_fund, beta_fund])
    session.flush()
    session.add_all(
        [
            PositionLot(
                portfolio_id=portfolio.id,
                fund_id=alpha_fund.id,
                run_id="bootstrap-1",
                lot_key="initial:000001:20260401:seed0001",
                opened_on=date(2026, 4, 1),
                as_of_date=date(2026, 4, 1),
                remaining_units=Decimal("10.000000"),
                average_cost_per_unit=Decimal("1.00000000"),
                total_cost_amount=Decimal("10.0000"),
            ),
            PositionLot(
                portfolio_id=portfolio.id,
                fund_id=beta_fund.id,
                run_id="bootstrap-1",
                lot_key="initial:000002:20260401:seed0001",
                opened_on=date(2026, 4, 1),
                as_of_date=date(2026, 4, 1),
                remaining_units=Decimal("5.000000"),
                average_cost_per_unit=Decimal("1.90000000"),
                total_cost_amount=Decimal("9.5000"),
            ),
            NavSnapshot(
                fund_id=alpha_fund.id,
                nav_date=date(2026, 4, 1),
                unit_nav_amount=Decimal("1.25000000"),
                source_name="test",
            ),
        ]
    )
    session.commit()

    snapshot = PortfolioService(session).get_portfolio_snapshot(
        portfolio.id,
        as_of_date=date(2026, 4, 1),
    )

    assert snapshot.position_count == 2
    assert snapshot.total_cost_amount == Decimal("19.5000")
    assert snapshot.total_market_value_amount is None
    assert snapshot.unrealized_pnl_amount is None
    assert snapshot.missing_nav_fund_codes == ("000002",)


def test_portfolio_service_prefers_transaction_aggregate_lots_over_bootstrap_for_same_fund(
    session: Session,
) -> None:
    portfolio = Portfolio(portfolio_code="main", portfolio_name="Main", is_default=True)
    fund = FundMaster(fund_code="000001", fund_name="Alpha Fund", source_name="test")
    session.add_all([portfolio, fund])
    session.flush()

    session.add_all(
        [
            PositionLot(
                portfolio_id=portfolio.id,
                fund_id=fund.id,
                run_id="holdings-import-20260301",
                lot_key="initial:000001:20260301:seed0001",
                opened_on=date(2026, 3, 1),
                as_of_date=date(2026, 3, 1),
                remaining_units=Decimal("10.000000"),
                average_cost_per_unit=Decimal("1.00000000"),
                total_cost_amount=Decimal("10.0000"),
            ),
            PositionLot(
                portfolio_id=portfolio.id,
                fund_id=fund.id,
                run_id="txnagg-sync-20260305",
                lot_key="txnagg:000001",
                opened_on=date(2026, 3, 1),
                as_of_date=date(2026, 3, 5),
                remaining_units=Decimal("6.000000"),
                average_cost_per_unit=Decimal("1.00000000"),
                total_cost_amount=Decimal("6.0000"),
            ),
            NavSnapshot(
                fund_id=fund.id,
                nav_date=date(2026, 3, 5),
                unit_nav_amount=Decimal("1.20000000"),
                source_name="test",
            ),
        ]
    )
    session.commit()

    snapshot = PortfolioService(session).get_portfolio_snapshot(
        portfolio.id,
        as_of_date=date(2026, 3, 5),
    )

    assert snapshot.position_count == 1
    assert snapshot.positions[0].fund_code == "000001"
    assert snapshot.positions[0].units == Decimal("6.000000")
    assert snapshot.positions[0].total_cost_amount == Decimal("6.0000")


def seed_two_fund_portfolio(session: Session) -> tuple[Portfolio, FundMaster, FundMaster]:
    portfolio = Portfolio(portfolio_code="main", portfolio_name="Main")
    alpha_fund = FundMaster(fund_code="000001", fund_name="Alpha Fund", source_name="test")
    beta_fund = FundMaster(fund_code="000002", fund_name="Beta Fund", source_name="test")
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
    return portfolio, alpha_fund, beta_fund
