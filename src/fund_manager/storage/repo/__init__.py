"""Repository interfaces and implementations for the core ledger kernel."""

from fund_manager.storage.repo.fund_master_repo import FundMasterRepository, FundUpsertResult
from fund_manager.storage.repo.nav_snapshot_repo import NavSnapshotCreate, NavSnapshotRepository
from fund_manager.storage.repo.portfolio_repo import (
    PortfolioRepository,
    build_portfolio_code_seed,
    normalize_portfolio_name,
)
from fund_manager.storage.repo.position_lot_repo import (
    ActivePortfolioFund,
    PositionLotRepository,
    resolve_authoritative_position_lots,
)
from fund_manager.storage.repo.protocols import (
    FundMasterRepositoryProtocol,
    NavSnapshotRepositoryProtocol,
    PortfolioRepositoryProtocol,
    PositionLotRepositoryProtocol,
    TransactionRepositoryProtocol,
    WatchlistRepositoryProtocol,
)
from fund_manager.storage.repo.transaction_repo import TransactionRepository
from fund_manager.storage.repo.watchlist_repo import WatchlistRepository

__all__ = [
    "ActivePortfolioFund",
    "FundMasterRepository",
    "FundMasterRepositoryProtocol",
    "FundUpsertResult",
    "NavSnapshotCreate",
    "NavSnapshotRepository",
    "NavSnapshotRepositoryProtocol",
    "PortfolioRepository",
    "PortfolioRepositoryProtocol",
    "PositionLotRepository",
    "PositionLotRepositoryProtocol",
    "TransactionRepository",
    "TransactionRepositoryProtocol",
    "WatchlistRepository",
    "WatchlistRepositoryProtocol",
    "build_portfolio_code_seed",
    "normalize_portfolio_name",
    "resolve_authoritative_position_lots",
]
