"""Integration tests for the storage-backed portfolio service."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from fund_manager.core.services import IncompletePortfolioSnapshotError, PortfolioService
from fund_manager.data_adapters.import_holdings import import_holdings_csv
from fund_manager.storage.models import (
    Base,
    FundMaster,
    NavSnapshot,
    Portfolio,
    PortfolioSnapshot,
    PositionLot,
)


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    database_path = tmp_path / "portfolio-service.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    with session_factory() as db_session:
        yield db_session

    engine.dispose()


def test_portfolio_service_assembles_snapshot_and_persists_it(session: Session) -> None:
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

    service = PortfolioService(session)

    snapshot = service.get_portfolio_snapshot(
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
    assert alpha_position.fund_code == "000001"
    assert alpha_position.units == Decimal("12.000000")
    assert alpha_position.current_value_amount == Decimal("18.0000")
    assert alpha_position.weight_ratio == Decimal("0.537313")
    assert beta_position.fund_code == "000002"
    assert beta_position.current_value_amount == Decimal("15.5000")
    assert beta_position.weight_ratio == Decimal("0.462687")

    stored_snapshot = service.save_portfolio_snapshot(
        portfolio.id,
        as_of_date=date(2026, 3, 15),
        run_id="weekly-20260315",
        workflow_name="weekly_review",
    )

    assert stored_snapshot.snapshot_record_id is not None
    assert session.scalar(select(func.count()).select_from(PortfolioSnapshot)) == 1

    persisted_row = session.execute(select(PortfolioSnapshot)).scalar_one()
    assert persisted_row.snapshot_date == date(2026, 3, 15)
    assert persisted_row.total_market_value_amount == Decimal("33.5000")
    assert persisted_row.weekly_return_ratio == Decimal("0.139456")


def test_portfolio_service_uses_latest_bootstrap_batch_and_blocks_incomplete_persistence(
    session: Session,
) -> None:
    import_holdings_csv(
        session,
        fixture_path("bootstrap_main.csv"),
        as_of_date=date(2026, 3, 31),
    )
    import_holdings_csv(
        session,
        fixture_path("append_snapshot.csv"),
        as_of_date=date(2026, 4, 1),
    )

    alpha_fund = session.execute(
        select(FundMaster).where(FundMaster.fund_code == "000001")
    ).scalar_one()
    session.add(
        NavSnapshot(
            fund_id=alpha_fund.id,
            nav_date=date(2026, 4, 1),
            unit_nav_amount=Decimal("1.25000000"),
            source_name="test",
        )
    )
    session.commit()

    portfolio = session.execute(
        select(Portfolio).where(Portfolio.portfolio_code == "main")
    ).scalar_one()
    service = PortfolioService(session)

    snapshot = service.get_portfolio_snapshot(
        portfolio.id,
        as_of_date=date(2026, 4, 1),
    )

    assert snapshot.position_count == 2
    assert snapshot.total_cost_amount == Decimal("19.5000")
    assert snapshot.total_market_value_amount is None
    assert snapshot.unrealized_pnl_amount is None
    assert snapshot.daily_return_ratio is None
    assert snapshot.weekly_return_ratio is None
    assert snapshot.monthly_return_ratio is None
    assert snapshot.max_drawdown_ratio is None
    assert snapshot.missing_nav_fund_codes == ("000002",)
    assert [position.units for position in snapshot.positions] == [
        Decimal("10.000000"),
        Decimal("5.000000"),
    ]

    with pytest.raises(IncompletePortfolioSnapshotError):
        service.save_portfolio_snapshot(
            portfolio.id,
            as_of_date=date(2026, 4, 1),
            run_id="weekly-20260401",
            workflow_name="weekly_review",
        )

    assert session.scalar(select(func.count()).select_from(PortfolioSnapshot)) == 0


def fixture_path(filename: str) -> Path:
    return Path(__file__).resolve().parents[3] / "fixtures" / "holdings" / filename
