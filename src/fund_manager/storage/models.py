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


class DecisionFeedbackStatus(StrEnum):
    """Supported manual feedback states for deterministic decision actions."""

    EXECUTED = "executed"
    SKIPPED = "skipped"
    DEFERRED = "deferred"


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
    policy_targets: Mapped[list[PortfolioPolicyTarget]] = relationship(back_populates="fund")
    decision_feedbacks: Mapped[list[DecisionFeedback]] = relationship(back_populates="fund")


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
    portfolio_policies: Mapped[list[PortfolioPolicy]] = relationship(back_populates="portfolio")
    decision_runs: Mapped[list[DecisionRun]] = relationship(back_populates="portfolio")
    decision_feedbacks: Mapped[list[DecisionFeedback]] = relationship(back_populates="portfolio")
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
    decision_links: Mapped[list[DecisionTransactionLink]] = relationship(
        back_populates="transaction"
    )


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


class PortfolioPolicy(CreatedAtMixin, Base):
    """Append-only portfolio policy snapshots that govern deterministic decisions."""

    __tablename__ = "portfolio_policy"
    __table_args__ = (
        Index("ix_portfolio_policy__portfolio_id__effective_from", "portfolio_id", "effective_from"),
        Index("ix_portfolio_policy__run_id", "run_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolio.id"), nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(64))
    policy_name: Mapped[str] = mapped_column(String(128), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    rebalance_threshold_ratio: Mapped[Decimal] = mapped_column(RATIO_NUMERIC, nullable=False)
    max_single_position_weight_ratio: Mapped[Decimal | None] = mapped_column(RATIO_NUMERIC)
    created_by: Mapped[str | None] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(Text)

    portfolio: Mapped[Portfolio] = relationship(back_populates="portfolio_policies")
    targets: Mapped[list[PortfolioPolicyTarget]] = relationship(
        back_populates="policy",
        cascade="all, delete-orphan",
    )
    decision_runs: Mapped[list[DecisionRun]] = relationship(back_populates="policy")


class PortfolioPolicyTarget(CreatedAtMixin, Base):
    """Fund-level target weights and bounds attached to one portfolio policy."""

    __tablename__ = "portfolio_policy_target"
    __table_args__ = (
        UniqueConstraint("policy_id", "fund_id", name="uq_portfolio_policy_target__policy_id__fund_id"),
        Index("ix_portfolio_policy_target__policy_id__fund_id", "policy_id", "fund_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    policy_id: Mapped[int] = mapped_column(ForeignKey("portfolio_policy.id"), nullable=False)
    fund_id: Mapped[int] = mapped_column(ForeignKey("fund_master.id"), nullable=False)
    target_weight_ratio: Mapped[Decimal] = mapped_column(RATIO_NUMERIC, nullable=False)
    min_weight_ratio: Mapped[Decimal | None] = mapped_column(RATIO_NUMERIC)
    max_weight_ratio: Mapped[Decimal | None] = mapped_column(RATIO_NUMERIC)
    add_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    trim_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    policy: Mapped[PortfolioPolicy] = relationship(back_populates="targets")
    fund: Mapped[FundMaster] = relationship(back_populates="policy_targets")


class DecisionRun(CreatedAtMixin, Base):
    """Append-only deterministic decision outputs generated from policy + facts."""

    __tablename__ = "decision_run"
    __table_args__ = (
        Index("ix_decision_run__portfolio_id__decision_date", "portfolio_id", "decision_date"),
        Index("ix_decision_run__run_id", "run_id"),
        Index("ix_decision_run__workflow_name__decision_date", "workflow_name", "decision_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolio.id"), nullable=False)
    policy_id: Mapped[int | None] = mapped_column(ForeignKey("portfolio_policy.id"))
    run_id: Mapped[str | None] = mapped_column(String(64))
    workflow_name: Mapped[str | None] = mapped_column(String(64))
    decision_date: Mapped[date] = mapped_column(Date, nullable=False)
    trigger_source: Mapped[str | None] = mapped_column(String(32))
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    final_decision: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence_score: Mapped[Decimal | None] = mapped_column(CONFIDENCE_NUMERIC)
    actions_json: Mapped[list[dict[str, Any]] | dict[str, Any] | None] = mapped_column(JSON)
    decision_summary_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSON)
    created_by_agent: Mapped[str | None] = mapped_column(String(64))

    portfolio: Mapped[Portfolio] = relationship(back_populates="decision_runs")
    policy: Mapped[PortfolioPolicy | None] = relationship(back_populates="decision_runs")
    feedback_entries: Mapped[list[DecisionFeedback]] = relationship(back_populates="decision_run")


class DecisionFeedback(CreatedAtMixin, Base):
    """Append-only manual feedback captured against one deterministic decision action."""

    __tablename__ = "decision_feedback"
    __table_args__ = (
        Index("ix_decision_feedback__decision_run_id__action_index", "decision_run_id", "action_index"),
        Index("ix_decision_feedback__portfolio_id__feedback_date", "portfolio_id", "feedback_date"),
        Index("ix_decision_feedback__fund_id__feedback_date", "fund_id", "feedback_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_run_id: Mapped[int] = mapped_column(ForeignKey("decision_run.id"), nullable=False)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolio.id"), nullable=False)
    fund_id: Mapped[int | None] = mapped_column(ForeignKey("fund_master.id"))
    action_index: Mapped[int] = mapped_column(Integer, nullable=False)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    feedback_status: Mapped[DecisionFeedbackStatus] = mapped_column(
        SqlEnum(
            DecisionFeedbackStatus,
            name="decision_feedback_status_enum",
            native_enum=False,
            length=32,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    feedback_date: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(64))

    decision_run: Mapped[DecisionRun] = relationship(back_populates="feedback_entries")
    portfolio: Mapped[Portfolio] = relationship(back_populates="decision_feedbacks")
    fund: Mapped[FundMaster | None] = relationship(back_populates="decision_feedbacks")
    transaction_links: Mapped[list[DecisionTransactionLink]] = relationship(
        back_populates="feedback",
        cascade="all, delete-orphan",
    )


class DecisionTransactionLink(CreatedAtMixin, Base):
    """Append-only links between manual feedback and authoritative transactions."""

    __tablename__ = "decision_transaction_link"
    __table_args__ = (
        UniqueConstraint(
            "transaction_id",
            name="uq_decision_transaction_link__transaction_id",
        ),
        Index("ix_decision_transaction_link__feedback_id", "feedback_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    feedback_id: Mapped[int] = mapped_column(ForeignKey("decision_feedback.id"), nullable=False)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transaction.id"), nullable=False)
    match_source: Mapped[str | None] = mapped_column(String(32))
    match_reason: Mapped[str | None] = mapped_column(Text)

    feedback: Mapped[DecisionFeedback] = relationship(back_populates="transaction_links")
    transaction: Mapped[TransactionRecord] = relationship(back_populates="decision_links")


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
    "DecisionFeedback",
    "DecisionFeedbackStatus",
    "DecisionRun",
    "DecisionTransactionLink",
    "FundMaster",
    "NavSnapshot",
    "Portfolio",
    "PortfolioPolicy",
    "PortfolioPolicyTarget",
    "PortfolioSnapshot",
    "PositionLot",
    "ReportPeriodType",
    "ReviewReport",
    "StrategyProposal",
    "SystemEventLog",
    "TransactionRecord",
    "TransactionType",
]
