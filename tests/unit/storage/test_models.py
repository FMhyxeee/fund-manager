"""Smoke tests for the SQLAlchemy model metadata."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from fund_manager.storage.models import (
    Base,
    FundMaster,
    Portfolio,
    TransactionRecord,
    TransactionType,
    WatchlistItem,
)


def test_metadata_create_all_builds_core_schema() -> None:
    """The ORM metadata should build only the core ledger/watchlist schema."""
    engine = create_engine("sqlite+pysqlite:///:memory:")

    Base.metadata.create_all(engine)

    inspector = inspect(engine)
    assert set(inspector.get_table_names()) == {
        "fund_master",
        "nav_snapshot",
        "portfolio",
        "position_lot",
        "transaction",
        "watchlist_item",
    }


def test_metadata_declares_stable_unique_constraints_and_indexes() -> None:
    """Key lookup paths should keep explicit stable names."""
    engine = create_engine("sqlite+pysqlite:///:memory:")

    Base.metadata.create_all(engine)

    inspector = inspect(engine)
    fund_unique_constraints = {
        constraint["name"] for constraint in inspector.get_unique_constraints("fund_master")
    }
    watchlist_unique_constraints = {
        constraint["name"] for constraint in inspector.get_unique_constraints("watchlist_item")
    }
    transaction_indexes = {index["name"] for index in inspector.get_indexes("transaction")}
    position_lot_indexes = {index["name"] for index in inspector.get_indexes("position_lot")}
    watchlist_indexes = {index["name"] for index in inspector.get_indexes("watchlist_item")}

    assert "uq_fund_master__fund_code" in fund_unique_constraints
    assert "uq_watchlist_item__fund_id" in watchlist_unique_constraints
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
    assert {
        "ix_watchlist_item__category",
        "ix_watchlist_item__removed_at",
    } <= watchlist_indexes


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


def test_watchlist_item_round_trips_json_tags() -> None:
    """Watchlist style tags should stay structured."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        fund = FundMaster(fund_code="000001", fund_name="Alpha", source_name="test")
        session.add(fund)
        session.flush()
        session.add(
            WatchlistItem(
                fund_id=fund.id,
                category="broad_index",
                style_tags_json=["index", "broad"],
                risk_level="medium",
            )
        )
        session.commit()

        stored_value = session.execute(select(WatchlistItem.style_tags_json)).scalar_one()

    assert stored_value == ["index", "broad"]
