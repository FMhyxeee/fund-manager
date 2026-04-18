"""Typed SQLAlchemy models for the simplified fund-manager core."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    Enum as SqlEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fund_manager.storage.db import Base

MONEY_NUMERIC = Numeric(20, 4)
NAV_NUMERIC = Numeric(20, 8)
UNITS_NUMERIC = Numeric(20, 6)
RATIO_NUMERIC = Numeric(12, 6)


def _enum_values(enum_cls: type[StrEnum]) -> list[str]:
    """Persist enum values instead of member names to match migrations."""
    return [member.value for member in enum_cls]


class TransactionType(StrEnum):
    """Supported normalized transaction types."""

    BUY = "buy"
    SELL = "sell"
    DIVIDEND = "dividend"
    CONVERT_IN = "convert_in"
    CONVERT_OUT = "convert_out"
    ADJUST = "adjust"


class CreatedAtMixin:
    """Timestamp for append-only records."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class UpdatedAtMixin(CreatedAtMixin):
    """Timestamps for mutable master records."""

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class FundMaster(UpdatedAtMixin, Base):
    """Reference data for funds tracked by the system."""

    __tablename__ = "fund_master"
    __table_args__ = (
        UniqueConstraint("fund_code", name="uq_fund_master__fund_code"),
        Index("ix_fund_master__fund_name", "fund_name"),
        Index("ix_fund_master__fund_status", "fund_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fund_code: Mapped[str] = mapped_column(String(32), nullable=False)
    fund_name: Mapped[str] = mapped_column(String(255), nullable=False)
    fund_type: Mapped[str | None] = mapped_column(String(64))
    base_currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="CNY")
    company_name: Mapped[str | None] = mapped_column(String(255))
    manager_name: Mapped[str | None] = mapped_column(String(255))
    risk_level: Mapped[str | None] = mapped_column(String(64))
    benchmark_name: Mapped[str | None] = mapped_column(String(255))
    fund_status: Mapped[str | None] = mapped_column(String(32))
    source_name: Mapped[str | None] = mapped_column(String(64))
    source_reference: Mapped[str | None] = mapped_column(String(128))

    transactions: Mapped[list[TransactionRecord]] = relationship(back_populates="fund")
    nav_snapshots: Mapped[list[NavSnapshot]] = relationship(back_populates="fund")
    position_lots: Mapped[list[PositionLot]] = relationship(back_populates="fund")
    watchlist_items: Mapped[list[WatchlistItem]] = relationship(back_populates="fund")


class Portfolio(UpdatedAtMixin, Base):
    """User portfolio definition."""

    __tablename__ = "portfolio"
    __table_args__ = (
        UniqueConstraint("portfolio_code", name="uq_portfolio__portfolio_code"),
        Index("ix_portfolio__portfolio_name", "portfolio_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_code: Mapped[str] = mapped_column(String(64), nullable=False)
    portfolio_name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="CNY")
    investment_style: Mapped[str | None] = mapped_column(String(128))
    target_description: Mapped[str | None] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    transactions: Mapped[list[TransactionRecord]] = relationship(back_populates="portfolio")
    position_lots: Mapped[list[PositionLot]] = relationship(back_populates="portfolio")


class TransactionRecord(CreatedAtMixin, Base):
    """Normalized append-only portfolio transactions."""

    __tablename__ = "transaction"
    __table_args__ = (
        Index("ix_transaction__portfolio_id__trade_date", "portfolio_id", "trade_date"),
        Index("ix_transaction__fund_id__trade_date", "fund_id", "trade_date"),
        Index("ix_transaction__source_name__source_reference", "source_name", "source_reference"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolio.id"), nullable=False)
    fund_id: Mapped[int] = mapped_column(ForeignKey("fund_master.id"), nullable=False)
    external_reference: Mapped[str | None] = mapped_column(String(128))
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    trade_type: Mapped[TransactionType] = mapped_column(
        SqlEnum(
            TransactionType,
            name="transaction_type_enum",
            native_enum=False,
            length=32,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    units: Mapped[Decimal | None] = mapped_column(UNITS_NUMERIC)
    gross_amount: Mapped[Decimal | None] = mapped_column(MONEY_NUMERIC)
    fee_amount: Mapped[Decimal | None] = mapped_column(MONEY_NUMERIC)
    nav_per_unit: Mapped[Decimal | None] = mapped_column(NAV_NUMERIC)
    source_name: Mapped[str | None] = mapped_column(String(64))
    source_reference: Mapped[str | None] = mapped_column(String(128))
    note: Mapped[str | None] = mapped_column(Text)

    portfolio: Mapped[Portfolio] = relationship(back_populates="transactions")
    fund: Mapped[FundMaster] = relationship(back_populates="transactions")
    position_lots: Mapped[list[PositionLot]] = relationship(back_populates="source_transaction")


class PositionLot(CreatedAtMixin, Base):
    """Append-only lot state snapshots rebuilt from authoritative transactions."""

    __tablename__ = "position_lot"
    __table_args__ = (
        Index("ix_position_lot__portfolio_id__as_of_date", "portfolio_id", "as_of_date"),
        Index("ix_position_lot__fund_id__as_of_date", "fund_id", "as_of_date"),
        Index("ix_position_lot__run_id", "run_id"),
        Index(
            "ix_position_lot__portfolio_id__fund_id__lot_key",
            "portfolio_id",
            "fund_id",
            "lot_key",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolio.id"), nullable=False)
    fund_id: Mapped[int] = mapped_column(ForeignKey("fund_master.id"), nullable=False)
    source_transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transaction.id"))
    run_id: Mapped[str | None] = mapped_column(String(64))
    lot_key: Mapped[str] = mapped_column(String(64), nullable=False)
    opened_on: Mapped[date | None] = mapped_column(Date)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    remaining_units: Mapped[Decimal] = mapped_column(UNITS_NUMERIC, nullable=False)
    average_cost_per_unit: Mapped[Decimal] = mapped_column(NAV_NUMERIC, nullable=False)
    total_cost_amount: Mapped[Decimal] = mapped_column(MONEY_NUMERIC, nullable=False)
    latest_nav_per_unit: Mapped[Decimal | None] = mapped_column(NAV_NUMERIC)
    latest_market_value_amount: Mapped[Decimal | None] = mapped_column(MONEY_NUMERIC)
    portfolio_weight_ratio: Mapped[Decimal | None] = mapped_column(RATIO_NUMERIC)

    portfolio: Mapped[Portfolio] = relationship(back_populates="position_lots")
    fund: Mapped[FundMaster] = relationship(back_populates="position_lots")
    source_transaction: Mapped[TransactionRecord | None] = relationship(
        back_populates="position_lots"
    )


class NavSnapshot(CreatedAtMixin, Base):
    """Append-only fund NAV observations normalized from external sources."""

    __tablename__ = "nav_snapshot"
    __table_args__ = (
        Index("ix_nav_snapshot__fund_id__nav_date", "fund_id", "nav_date"),
        Index("ix_nav_snapshot__source_name__nav_date", "source_name", "nav_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fund_id: Mapped[int] = mapped_column(ForeignKey("fund_master.id"), nullable=False)
    nav_date: Mapped[date] = mapped_column(Date, nullable=False)
    unit_nav_amount: Mapped[Decimal] = mapped_column(NAV_NUMERIC, nullable=False)
    accumulated_nav_amount: Mapped[Decimal | None] = mapped_column(NAV_NUMERIC)
    daily_return_ratio: Mapped[Decimal | None] = mapped_column(RATIO_NUMERIC)
    source_name: Mapped[str | None] = mapped_column(String(64))
    source_reference: Mapped[str | None] = mapped_column(String(128))

    fund: Mapped[FundMaster] = relationship(back_populates="nav_snapshots")


class WatchlistItem(UpdatedAtMixin, Base):
    """Mutable fund watchlist entry separated from canonical accounting truth."""

    __tablename__ = "watchlist_item"
    __table_args__ = (
        UniqueConstraint("fund_id", name="uq_watchlist_item__fund_id"),
        Index("ix_watchlist_item__removed_at", "removed_at"),
        Index("ix_watchlist_item__category", "category"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fund_id: Mapped[int] = mapped_column(ForeignKey("fund_master.id"), nullable=False)
    category: Mapped[str | None] = mapped_column(String(64))
    style_tags_json: Mapped[list[str] | dict[str, Any] | None] = mapped_column(JSON)
    risk_level: Mapped[str | None] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(Text)
    source_name: Mapped[str | None] = mapped_column(String(64))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    fund: Mapped[FundMaster] = relationship(back_populates="watchlist_items")


__all__ = [
    "Base",
    "FundMaster",
    "NavSnapshot",
    "Portfolio",
    "PositionLot",
    "TransactionRecord",
    "TransactionType",
    "WatchlistItem",
]
