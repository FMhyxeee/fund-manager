"""Integration tests for the holdings import pipeline."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from fund_manager.data_adapters.import_holdings import import_holdings_csv
from fund_manager.storage.models import Base, FundMaster, Portfolio, PositionLot


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    with session_factory() as db_session:
        yield db_session


def test_import_holdings_creates_master_data_and_lots(session: Session) -> None:
    summary = import_holdings_csv(
        session,
        fixture_path("bootstrap_main.csv"),
        as_of_date=date(2026, 3, 31),
    )

    assert summary.dry_run is False
    assert summary.position_lot_count == 2
    assert summary.created_portfolio_names == ("main",)
    assert set(summary.created_fund_codes) == {"000001", "000002"}
    assert session.scalar(select(func.count()).select_from(Portfolio)) == 1
    assert session.scalar(select(func.count()).select_from(FundMaster)) == 2
    assert session.scalar(select(func.count()).select_from(PositionLot)) == 2

    beta_lot = session.execute(
        select(PositionLot)
        .join(FundMaster, PositionLot.fund_id == FundMaster.id)
        .where(FundMaster.fund_code == "000002")
    ).scalar_one()
    assert beta_lot.average_cost_per_unit == Decimal("1.50000000")
    assert beta_lot.total_cost_amount == Decimal("7.5000")


def test_import_holdings_dry_run_does_not_write(session: Session) -> None:
    summary = import_holdings_csv(
        session,
        fixture_path("bootstrap_main.csv"),
        as_of_date=date(2026, 3, 31),
        dry_run=True,
    )

    assert summary.dry_run is True
    assert summary.position_lot_count == 2
    assert session.scalar(select(func.count()).select_from(Portfolio)) == 0
    assert session.scalar(select(func.count()).select_from(FundMaster)) == 0
    assert session.scalar(select(func.count()).select_from(PositionLot)) == 0


def test_import_holdings_reuses_master_data_and_appends_new_snapshots(session: Session) -> None:
    import_holdings_csv(
        session,
        fixture_path("bootstrap_main.csv"),
        as_of_date=date(2026, 3, 31),
    )

    summary = import_holdings_csv(
        session,
        fixture_path("append_snapshot.csv"),
        as_of_date=date(2026, 4, 1),
    )

    alpha_fund = session.execute(
        select(FundMaster).where(FundMaster.fund_code == "000001")
    ).scalar_one()

    assert summary.created_portfolio_names == ()
    assert summary.reused_portfolio_names == ("main",)
    assert summary.updated_fund_codes == ("000001",)
    assert session.scalar(select(func.count()).select_from(Portfolio)) == 1
    assert session.scalar(select(func.count()).select_from(FundMaster)) == 2
    assert session.scalar(select(func.count()).select_from(PositionLot)) == 4
    assert alpha_fund.fund_name == "Alpha Fund Updated"


def fixture_path(filename: str) -> Path:
    return Path(__file__).resolve().parents[2] / "fixtures" / "holdings" / filename
