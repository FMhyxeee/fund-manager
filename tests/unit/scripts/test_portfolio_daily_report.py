"""Tests for the daily portfolio report script."""

from __future__ import annotations

import importlib.util
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from fund_manager.core.config import get_settings
from fund_manager.storage.db import get_engine, get_session_factory
from fund_manager.storage.models import Base, FundMaster, NavSnapshot, Portfolio, PositionLot, TransactionRecord, TransactionType


def _load_report_module():
    script_path = Path(__file__).resolve().parents[3] / "scripts" / "portfolio_daily_report.py"
    spec = importlib.util.spec_from_file_location("portfolio_daily_report", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_generate_report_uses_position_lots_and_ratio_percentages(monkeypatch, tmp_path) -> None:
    """The report should read canonical lots and render ratio fields as percentages."""
    database_path = tmp_path / "report.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    get_settings.cache_clear()
    get_session_factory.cache_clear()
    get_engine.cache_clear()

    try:
        engine = get_engine()
        Base.metadata.create_all(engine)

        with Session(engine) as session:
            portfolio = Portfolio(id=1, portfolio_code="main", portfolio_name="Main", is_default=True)
            fund = FundMaster(id=1, fund_code="000001", fund_name="Alpha", source_name="test")
            session.add_all([portfolio, fund])
            session.flush()
            session.add(
                PositionLot(
                    portfolio_id=portfolio.id,
                    fund_id=fund.id,
                    lot_key="lot-1",
                    run_id="test-run",
                    opened_on=date(2026, 3, 1),
                    as_of_date=date(2026, 3, 1),
                    remaining_units=Decimal("100.000000"),
                    average_cost_per_unit=Decimal("1.00000000"),
                    total_cost_amount=Decimal("100.0000"),
                )
            )
            session.add(
                TransactionRecord(
                    portfolio_id=portfolio.id,
                    fund_id=fund.id,
                    trade_date=date(2026, 3, 1),
                    trade_type=TransactionType.BUY,
                    units=Decimal("100.000000"),
                    gross_amount=Decimal("100.0000"),
                )
            )
            session.add_all(
                [
                    NavSnapshot(
                        fund_id=fund.id,
                        nav_date=date(2026, 3, 3),
                        unit_nav_amount=Decimal("1.01000000"),
                        daily_return_ratio=Decimal("0.010000"),
                    ),
                    NavSnapshot(
                        fund_id=fund.id,
                        nav_date=date(2026, 3, 2),
                        unit_nav_amount=Decimal("1.00000000"),
                        daily_return_ratio=Decimal("-0.005000"),
                    ),
                ]
            )
            session.commit()

        module = _load_report_module()
        report = module.generate_report(as_of_date=date(2026, 3, 3))
    finally:
        get_settings.cache_clear()
        get_session_factory.cache_clear()
        get_engine.cache_clear()

    assert "Alpha（000001）" in report
    assert "2026-03-03 1.0100 (+1.00%)" in report
    assert "2026-03-02 1.0000 (-0.50%)" in report
    assert "💰 组合总市值: ¥101.00" in report


def test_generate_report_ignores_buy_transactions_without_position_lots(monkeypatch, tmp_path) -> None:
    """Raw buy transactions alone should not be treated as authoritative holdings."""
    database_path = tmp_path / "report-empty.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    get_settings.cache_clear()
    get_session_factory.cache_clear()
    get_engine.cache_clear()

    try:
        engine = get_engine()
        Base.metadata.create_all(engine)

        with Session(engine) as session:
            portfolio = Portfolio(id=1, portfolio_code="main", portfolio_name="Main", is_default=True)
            fund = FundMaster(id=1, fund_code="000001", fund_name="Alpha", source_name="test")
            session.add_all([portfolio, fund])
            session.flush()
            session.add(
                TransactionRecord(
                    portfolio_id=portfolio.id,
                    fund_id=fund.id,
                    trade_date=date(2026, 3, 1),
                    trade_type=TransactionType.BUY,
                    units=Decimal("100.000000"),
                    gross_amount=Decimal("100.0000"),
                )
            )
            session.commit()

        module = _load_report_module()
        report = module.generate_report(as_of_date=date(2026, 3, 3))
    finally:
        get_settings.cache_clear()
        get_session_factory.cache_clear()
        get_engine.cache_clear()

    assert report == "📭 当前无持仓"
