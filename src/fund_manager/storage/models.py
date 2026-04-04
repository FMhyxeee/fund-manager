"""Typed SQLAlchemy models for the v1 persistence layer."""

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
CONFIDENCE_NUMERIC = Numeric(5, 4)


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


class ReportPeriodType(StrEnum):
    """Supported review report periods."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


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
    portfolio_snapshots: Mapped[list[PortfolioSnapshot]] = relationship(back_populates="portfolio")
    review_reports: Mapped[list[ReviewReport]] = relationship(back_populates="portfolio")
    strategy_proposals: Mapped[list[StrategyProposal]] = relationship(back_populates="portfolio")
    debate_logs: Mapped[list[AgentDebateLog]] = relationship(back_populates="portfolio")
    system_event_logs: Mapped[list[SystemEventLog]] = relationship(back_populates="portfolio")


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
            "ix_position_lot__portfolio_id__fund_id__lot_key", "portfolio_id", "fund_id", "lot_key"
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


class PortfolioSnapshot(CreatedAtMixin, Base):
    """Append-only portfolio metrics captured for a specific as-of date."""

    __tablename__ = "portfolio_snapshot"
    __table_args__ = (
        Index(
            "ix_portfolio_snapshot__portfolio_id__snapshot_date", "portfolio_id", "snapshot_date"
        ),
        Index("ix_portfolio_snapshot__run_id", "run_id"),
        Index(
            "ix_portfolio_snapshot__workflow_name__snapshot_date", "workflow_name", "snapshot_date"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolio.id"), nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(64))
    workflow_name: Mapped[str | None] = mapped_column(String(64))
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    total_cost_amount: Mapped[Decimal] = mapped_column(MONEY_NUMERIC, nullable=False)
    total_market_value_amount: Mapped[Decimal] = mapped_column(MONEY_NUMERIC, nullable=False)
    total_cash_amount: Mapped[Decimal | None] = mapped_column(MONEY_NUMERIC)
    unrealized_pnl_amount: Mapped[Decimal] = mapped_column(MONEY_NUMERIC, nullable=False)
    realized_pnl_amount: Mapped[Decimal | None] = mapped_column(MONEY_NUMERIC)
    cash_ratio: Mapped[Decimal | None] = mapped_column(RATIO_NUMERIC)
    daily_return_ratio: Mapped[Decimal | None] = mapped_column(RATIO_NUMERIC)
    weekly_return_ratio: Mapped[Decimal | None] = mapped_column(RATIO_NUMERIC)
    monthly_return_ratio: Mapped[Decimal | None] = mapped_column(RATIO_NUMERIC)
    max_drawdown_ratio: Mapped[Decimal | None] = mapped_column(RATIO_NUMERIC)

    portfolio: Mapped[Portfolio] = relationship(back_populates="portfolio_snapshots")


class ReviewReport(CreatedAtMixin, Base):
    """Append-only review report artifacts produced by workflows."""

    __tablename__ = "review_report"
    __table_args__ = (
        Index("ix_review_report__portfolio_id__period_end", "portfolio_id", "period_end"),
        Index("ix_review_report__run_id", "run_id"),
        Index("ix_review_report__workflow_name__period_type", "workflow_name", "period_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolio.id"), nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(64))
    workflow_name: Mapped[str | None] = mapped_column(String(64))
    period_type: Mapped[ReportPeriodType] = mapped_column(
        SqlEnum(
            ReportPeriodType,
            name="report_period_type_enum",
            native_enum=False,
            length=16,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    report_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    summary_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_by_agent: Mapped[str | None] = mapped_column(String(64))

    portfolio: Mapped[Portfolio] = relationship(back_populates="review_reports")


class StrategyProposal(CreatedAtMixin, Base):
    """Append-only strategy proposals and final judgments."""

    __tablename__ = "strategy_proposal"
    __table_args__ = (
        Index("ix_strategy_proposal__portfolio_id__proposal_date", "portfolio_id", "proposal_date"),
        Index("ix_strategy_proposal__run_id", "run_id"),
        Index(
            "ix_strategy_proposal__workflow_name__proposal_date", "workflow_name", "proposal_date"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolio.id"), nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(64))
    workflow_name: Mapped[str | None] = mapped_column(String(64))
    proposal_date: Mapped[date] = mapped_column(Date, nullable=False)
    thesis: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSON)
    recommended_actions_json: Mapped[list[dict[str, Any]] | dict[str, Any] | None] = mapped_column(
        JSON
    )
    risk_notes: Mapped[str | None] = mapped_column(Text)
    counterarguments: Mapped[str | None] = mapped_column(Text)
    final_decision: Mapped[str | None] = mapped_column(String(64))
    confidence_score: Mapped[Decimal | None] = mapped_column(CONFIDENCE_NUMERIC)
    created_by_agent: Mapped[str | None] = mapped_column(String(64))

    portfolio: Mapped[Portfolio] = relationship(back_populates="strategy_proposals")


class AgentDebateLog(CreatedAtMixin, Base):
    """Append-only agent discussion log for workflow traceability."""

    __tablename__ = "agent_debate_log"
    __table_args__ = (
        Index("ix_agent_debate_log__run_id__created_at", "run_id", "created_at"),
        Index("ix_agent_debate_log__portfolio_id__workflow_name", "portfolio_id", "workflow_name"),
        Index("ix_agent_debate_log__agent_name__created_at", "agent_name", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[int | None] = mapped_column(ForeignKey("portfolio.id"))
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    workflow_name: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(128))
    input_summary: Mapped[str | None] = mapped_column(Text)
    output_summary: Mapped[str | None] = mapped_column(Text)
    tool_calls_json: Mapped[list[dict[str, Any]] | dict[str, Any] | None] = mapped_column(JSON)
    trace_reference: Mapped[str | None] = mapped_column(String(255))

    portfolio: Mapped[Portfolio | None] = relationship(back_populates="debate_logs")


class SystemEventLog(CreatedAtMixin, Base):
    """Append-only workflow and system events."""

    __tablename__ = "system_event_log"
    __table_args__ = (
        Index("ix_system_event_log__run_id__created_at", "run_id", "created_at"),
        Index("ix_system_event_log__event_type__created_at", "event_type", "created_at"),
        Index("ix_system_event_log__portfolio_id__workflow_name", "portfolio_id", "workflow_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[int | None] = mapped_column(ForeignKey("portfolio.id"))
    run_id: Mapped[str | None] = mapped_column(String(64))
    workflow_name: Mapped[str | None] = mapped_column(String(64))
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    event_message: Mapped[str | None] = mapped_column(Text)
    payload_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSON)

    portfolio: Mapped[Portfolio | None] = relationship(back_populates="system_event_logs")


__all__ = [
    "AgentDebateLog",
    "Base",
    "FundMaster",
    "NavSnapshot",
    "Portfolio",
    "PortfolioSnapshot",
    "PositionLot",
    "ReportPeriodType",
    "ReviewReport",
    "StrategyProposal",
    "SystemEventLog",
    "TransactionRecord",
    "TransactionType",
]
