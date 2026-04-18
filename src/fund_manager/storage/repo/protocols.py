"""Protocol abstractions for core repository dependencies."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Protocol

from fund_manager.storage.models import (
    FundMaster,
    NavSnapshot,
    Portfolio,
    PositionLot,
    TransactionRecord,
    TransactionType,
    WatchlistItem,
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

    def get_by_id(self, transaction_id: int) -> TransactionRecord | None: ...

    def list_recent(
        self,
        *,
        portfolio_id: int | None = None,
        fund_id: int | None = None,
        trade_type: TransactionType | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 50,
    ) -> tuple[TransactionRecord, ...]: ...

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


class WatchlistRepositoryProtocol(Protocol):
    """Abstract watchlist repository contract."""

    def list_items(self, *, include_removed: bool = False) -> tuple[WatchlistItem, ...]: ...

    def get_by_fund_id(self, fund_id: int) -> WatchlistItem | None: ...

    def upsert_active(
        self,
        *,
        fund_id: int,
        category: str | None,
        style_tags: tuple[str, ...],
        risk_level: str | None,
        note: str | None,
        source_name: str | None,
    ) -> tuple[WatchlistItem, bool, bool]: ...

    def soft_remove(self, item: WatchlistItem) -> WatchlistItem: ...


__all__ = [
    "FundMasterRepositoryProtocol",
    "NavSnapshotRepositoryProtocol",
    "PortfolioRepositoryProtocol",
    "PositionLotRepositoryProtocol",
    "TransactionRepositoryProtocol",
    "WatchlistRepositoryProtocol",
]
