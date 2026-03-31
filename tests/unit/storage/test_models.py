"""Smoke tests for the SQLAlchemy model metadata."""

from __future__ import annotations

from sqlalchemy import create_engine, inspect

from fund_manager.storage.models import Base


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
