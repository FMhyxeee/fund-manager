"""Smoke tests for the SQLAlchemy model metadata."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from fund_manager.storage.models import Base, FundMaster, Portfolio, ReportPeriodType, ReviewReport, TransactionRecord, TransactionType


def test_metadata_create_all_builds_expected_tables() -> None:
    """The ORM metadata should build the full v1 schema on SQLite."""
    engine = create_engine("sqlite+pysqlite:///:memory:")

    Base.metadata.create_all(engine)

    inspector = inspect(engine)
    assert set(inspector.get_table_names()) == {
        "agent_debate_log",
        "fund_master",
        "nav_snapshot",
        "portfolio",
        "portfolio_snapshot",
        "position_lot",
        "review_report",
        "strategy_proposal",
        "system_event_log",
        "transaction",
    }


def test_metadata_declares_stable_unique_constraints_and_indexes() -> None:
    """Key lookup paths should keep explicit stable names."""
    engine = create_engine("sqlite+pysqlite:///:memory:")

    Base.metadata.create_all(engine)

    inspector = inspect(engine)
    fund_unique_constraints = {
        constraint["name"] for constraint in inspector.get_unique_constraints("fund_master")
    }
    transaction_indexes = {index["name"] for index in inspector.get_indexes("transaction")}
    position_lot_indexes = {index["name"] for index in inspector.get_indexes("position_lot")}

    assert "uq_fund_master__fund_code" in fund_unique_constraints
    assert {
        "ix_transaction__fund_id__trade_date",
        "ix_transaction__portfolio_id__trade_date",
        "ix_transaction__source_name__source_reference",
    } <= transaction_indexes
    assert {
        "ix_position_lot__portfolio_id__as_of_date",
        "ix_position_lot__portfolio_id__fund_id__lot_key",
        "ix_position_lot__run_id",
    } <= position_lot_indexes


def test_transaction_enum_round_trips_lowercase_storage() -> None:
    """ORM enum mapping should stay compatible with migrated lowercase values."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        portfolio = Portfolio(portfolio_code="main", portfolio_name="Main", is_default=True)
        fund = FundMaster(fund_code="000001", fund_name="Alpha", source_name="test")
        session.add_all([portfolio, fund])
        session.flush()
        session.add(
            TransactionRecord(
                portfolio_id=portfolio.id,
                fund_id=fund.id,
                trade_date=date(2026, 3, 1),
                trade_type=TransactionType.BUY,
                units=Decimal("10"),
                gross_amount=Decimal("12"),
            )
        )
        session.commit()

        stored_value = session.execute(text('SELECT trade_type FROM "transaction"')).scalar_one()
        loaded_value = session.execute(select(TransactionRecord.trade_type)).scalar_one()

    assert stored_value == "buy"
    assert loaded_value is TransactionType.BUY


def test_review_report_enum_round_trips_lowercase_storage() -> None:
    """Report period enums should persist values that match the migration."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        portfolio = Portfolio(portfolio_code="main", portfolio_name="Main", is_default=True)
        session.add(portfolio)
        session.flush()
        session.add(
            ReviewReport(
                portfolio_id=portfolio.id,
                period_type=ReportPeriodType.WEEKLY,
                period_start=date(2026, 3, 1),
                period_end=date(2026, 3, 7),
                report_markdown="# report",
            )
        )
        session.commit()

        stored_value = session.execute(text("SELECT period_type FROM review_report")).scalar_one()
        loaded_value = session.execute(select(ReviewReport.period_type)).scalar_one()

    assert stored_value == "weekly"
    assert loaded_value is ReportPeriodType.WEEKLY
