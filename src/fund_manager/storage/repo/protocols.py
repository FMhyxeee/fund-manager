"""Protocol abstractions for repository dependencies."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any, Protocol

from fund_manager.storage.models import (
    AgentDebateLog,
    DecisionFeedback,
    DecisionFeedbackStatus,
    DecisionRun,
    DecisionTransactionLink,
    FundMaster,
    NavSnapshot,
    Portfolio,
    PortfolioPolicy,
    PortfolioSnapshot,
    PortfolioPolicyTarget,
    PositionLot,
    ReportPeriodType,
    ReviewReport,
    StrategyProposal,
    SystemEventLog,
    TransactionRecord,
    TransactionType,
)
from fund_manager.storage.repo.fund_master_repo import FundUpsertResult
from fund_manager.storage.repo.nav_snapshot_repo import NavSnapshotCreate
from fund_manager.storage.repo.position_lot_repo import ActivePortfolioFund


class PortfolioRepositoryProtocol(Protocol):
    """Abstract portfolio repository contract."""

    def get_by_id(self, portfolio_id: int) -> Portfolio | None: ...

    def get_by_name(self, portfolio_name: str) -> Portfolio | None: ...

    def list_all(self) -> tuple[Portfolio, ...]: ...

    def get_or_create(
        self,
        portfolio_name: str,
        *,
        default_portfolio_name: str,
    ) -> tuple[Portfolio, bool]: ...


class PortfolioPolicyRepositoryProtocol(Protocol):
    """Abstract portfolio policy repository contract."""

    def get_active_for_date(
        self,
        *,
        portfolio_id: int,
        as_of_date: date,
    ) -> PortfolioPolicy | None: ...

    def append(
        self,
        *,
        portfolio_id: int,
        policy_name: str,
        effective_from: date,
        rebalance_threshold_ratio: Decimal,
        targets: Sequence[PortfolioPolicyTargetCreateProtocol],
        effective_to: date | None = None,
        max_single_position_weight_ratio: Decimal | None = None,
        created_by: str | None = None,
        notes: str | None = None,
        run_id: str | None = None,
    ) -> PortfolioPolicy: ...


class PortfolioPolicyTargetCreateProtocol(Protocol):
    """Protocol shape for policy target creation DTOs."""

    fund_id: int
    target_weight_ratio: Decimal
    min_weight_ratio: Decimal | None
    max_weight_ratio: Decimal | None
    add_allowed: bool
    trim_allowed: bool


class PositionLotRepositoryProtocol(Protocol):
    """Abstract append-only position lot repository contract."""

    def list_for_portfolio_up_to(
        self,
        *,
        portfolio_id: int,
        as_of_date: date,
    ) -> list[PositionLot]: ...

    def append_import_snapshot(
        self,
        *,
        portfolio_id: int,
        fund_id: int,
        fund_code: str,
        as_of_date: date,
        run_id: str,
        remaining_units: Decimal,
        average_cost_per_unit: Decimal,
        total_cost_amount: Decimal,
    ) -> PositionLot: ...

    def list_active_funds_for_portfolio_up_to(
        self,
        *,
        portfolio_id: int,
        as_of_date: date,
    ) -> tuple[ActivePortfolioFund, ...]: ...


class NavSnapshotRepositoryProtocol(Protocol):
    """Abstract NAV snapshot repository contract."""

    def list_for_funds_up_to(
        self,
        *,
        fund_ids: Sequence[int],
        as_of_date: date,
    ) -> list[NavSnapshot]: ...

    def get_latest_nav_date(self, *, fund_id: int) -> date | None: ...

    def append_many(
        self,
        *,
        fund_id: int,
        snapshots: Sequence[NavSnapshotCreate],
    ) -> int: ...


class PortfolioSnapshotRepositoryProtocol(Protocol):
    """Abstract portfolio snapshot persistence contract."""

    def append(
        self,
        *,
        portfolio_id: int,
        snapshot_date: date,
        total_cost_amount: Decimal,
        total_market_value_amount: Decimal,
        unrealized_pnl_amount: Decimal,
        daily_return_ratio: Decimal | None,
        weekly_return_ratio: Decimal | None,
        monthly_return_ratio: Decimal | None,
        max_drawdown_ratio: Decimal | None,
        run_id: str | None = None,
        workflow_name: str | None = None,
        total_cash_amount: Decimal | None = None,
        realized_pnl_amount: Decimal | None = None,
        cash_ratio: Decimal | None = None,
    ) -> PortfolioSnapshot: ...


class FundMasterRepositoryProtocol(Protocol):
    """Abstract fund master repository contract."""

    def get_by_code(self, fund_code: str) -> FundMaster | None: ...

    def upsert(
        self,
        *,
        fund_code: str,
        fund_name: str,
        source_name: str = "holdings_import",
    ) -> FundUpsertResult: ...

    def update_public_profile(
        self,
        *,
        fund_code: str,
        fund_name: str | None = None,
        fund_type: str | None = None,
        company_name: str | None = None,
        manager_name: str | None = None,
        benchmark_name: str | None = None,
        source_name: str | None = None,
        source_reference: str | None = None,
    ) -> bool: ...


class TransactionRepositoryProtocol(Protocol):
    """Abstract transaction repository contract."""

    def append_import_record(
        self,
        *,
        portfolio_id: int,
        fund_id: int,
        external_reference: str | None,
        trade_date: date,
        trade_type: TransactionType,
        units: Decimal | None,
        gross_amount: Decimal | None,
        fee_amount: Decimal | None,
        nav_per_unit: Decimal | None,
        source_name: str | None,
        source_reference: str | None,
        note: str | None,
    ) -> TransactionRecord: ...


class DecisionFeedbackRepositoryProtocol(Protocol):
    """Abstract manual decision feedback persistence contract."""

    def get_by_id(self, feedback_id: int) -> DecisionFeedback | None: ...

    def append(
        self,
        *,
        decision_run_id: int,
        portfolio_id: int,
        fund_id: int | None,
        action_index: int,
        action_type: str,
        feedback_status: DecisionFeedbackStatus,
        feedback_date: date,
        note: str | None = None,
        created_by: str | None = None,
    ) -> DecisionFeedback: ...


class DecisionTransactionLinkRepositoryProtocol(Protocol):
    """Abstract feedback-to-transaction link persistence contract."""

    def append(
        self,
        *,
        feedback_id: int,
        transaction_id: int,
        match_source: str | None = None,
        match_reason: str | None = None,
    ) -> DecisionTransactionLink: ...


class ReviewReportRepositoryProtocol(Protocol):
    """Abstract review report persistence contract."""

    def append(
        self,
        *,
        portfolio_id: int,
        period_type: ReportPeriodType,
        period_start: date,
        period_end: date,
        report_markdown: str,
        summary_json: dict[str, Any] | None,
        created_by_agent: str | None,
        run_id: str | None = None,
        workflow_name: str | None = None,
    ) -> ReviewReport: ...


class AgentDebateLogRepositoryProtocol(Protocol):
    """Abstract workflow trace log persistence contract."""

    def append(
        self,
        *,
        run_id: str,
        workflow_name: str,
        agent_name: str,
        portfolio_id: int | None = None,
        model_name: str | None = None,
        input_summary: str | None = None,
        output_summary: str | None = None,
        tool_calls_json: list[dict[str, Any]] | dict[str, Any] | None = None,
        trace_reference: str | None = None,
    ) -> AgentDebateLog: ...


class SystemEventLogRepositoryProtocol(Protocol):
    """Abstract system event persistence contract."""

    def append(
        self,
        *,
        event_type: str,
        status: str,
        portfolio_id: int | None = None,
        run_id: str | None = None,
        workflow_name: str | None = None,
        event_message: str | None = None,
        payload_json: dict[str, Any] | list[Any] | None = None,
    ) -> SystemEventLog: ...


class StrategyProposalRepositoryProtocol(Protocol):
    """Abstract strategy proposal persistence contract."""

    def append(
        self,
        *,
        portfolio_id: int,
        proposal_date: date,
        thesis: str,
        evidence_json: dict[str, Any] | list[Any] | None,
        recommended_actions_json: list[dict[str, Any]] | dict[str, Any] | None,
        risk_notes: str | None,
        counterarguments: str | None,
        final_decision: str | None,
        confidence_score: Decimal | None,
        created_by_agent: str | None,
        run_id: str | None = None,
        workflow_name: str | None = None,
    ) -> StrategyProposal: ...


class DecisionRunRepositoryProtocol(Protocol):
    """Abstract deterministic decision run persistence contract."""

    def get_by_id(self, decision_run_id: int) -> DecisionRun | None: ...

    def append(
        self,
        *,
        portfolio_id: int,
        decision_date: date,
        summary: str,
        final_decision: str,
        trigger_source: str | None,
        actions_json: list[dict[str, Any]] | dict[str, Any] | None,
        decision_summary_json: dict[str, Any] | list[Any] | None,
        created_by_agent: str | None,
        policy_id: int | None = None,
        confidence_score: Decimal | None = None,
        run_id: str | None = None,
        workflow_name: str | None = None,
    ) -> DecisionRun: ...


__all__ = [
    "AgentDebateLogRepositoryProtocol",
    "DecisionFeedbackRepositoryProtocol",
    "DecisionRunRepositoryProtocol",
    "DecisionTransactionLinkRepositoryProtocol",
    "FundMasterRepositoryProtocol",
    "NavSnapshotRepositoryProtocol",
    "PortfolioRepositoryProtocol",
    "PortfolioPolicyRepositoryProtocol",
    "PortfolioPolicyTargetCreateProtocol",
    "PortfolioSnapshotRepositoryProtocol",
    "PositionLotRepositoryProtocol",
    "ReviewReportRepositoryProtocol",
    "StrategyProposalRepositoryProtocol",
    "SystemEventLogRepositoryProtocol",
    "TransactionRepositoryProtocol",
]
