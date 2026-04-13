"""Repository interfaces and implementations."""

from fund_manager.storage.repo.agent_debate_log_repo import AgentDebateLogRepository
from fund_manager.storage.repo.decision_feedback_repo import DecisionFeedbackRepository
from fund_manager.storage.repo.decision_run_repo import DecisionRunRepository
from fund_manager.storage.repo.decision_transaction_link_repo import (
    DecisionTransactionLinkRepository,
)
from fund_manager.storage.repo.fund_master_repo import FundMasterRepository, FundUpsertResult
from fund_manager.storage.repo.nav_snapshot_repo import NavSnapshotCreate, NavSnapshotRepository
from fund_manager.storage.repo.portfolio_policy_repo import (
    PortfolioPolicyRepository,
    PortfolioPolicyTargetCreate,
)
from fund_manager.storage.repo.portfolio_repo import (
    PortfolioRepository,
    build_portfolio_code_seed,
    normalize_portfolio_name,
)
from fund_manager.storage.repo.portfolio_snapshot_repo import PortfolioSnapshotRepository
from fund_manager.storage.repo.position_lot_repo import (
    ActivePortfolioFund,
    PositionLotRepository,
    resolve_authoritative_position_lots,
)
from fund_manager.storage.repo.protocols import (
    AgentDebateLogRepositoryProtocol,
    DecisionFeedbackRepositoryProtocol,
    DecisionRunRepositoryProtocol,
    DecisionTransactionLinkRepositoryProtocol,
    FundMasterRepositoryProtocol,
    NavSnapshotRepositoryProtocol,
    PortfolioRepositoryProtocol,
    PortfolioPolicyRepositoryProtocol,
    PortfolioPolicyTargetCreateProtocol,
    PortfolioSnapshotRepositoryProtocol,
    PositionLotRepositoryProtocol,
    ReviewReportRepositoryProtocol,
    StrategyProposalRepositoryProtocol,
    SystemEventLogRepositoryProtocol,
    TransactionRepositoryProtocol,
)
from fund_manager.storage.repo.review_report_repo import ReviewReportRepository
from fund_manager.storage.repo.strategy_proposal_repo import StrategyProposalRepository
from fund_manager.storage.repo.system_event_log_repo import SystemEventLogRepository
from fund_manager.storage.repo.transaction_repo import TransactionRepository

__all__ = [
    "AgentDebateLogRepository",
    "AgentDebateLogRepositoryProtocol",
    "DecisionFeedbackRepository",
    "DecisionFeedbackRepositoryProtocol",
    "DecisionRunRepository",
    "DecisionRunRepositoryProtocol",
    "DecisionTransactionLinkRepository",
    "DecisionTransactionLinkRepositoryProtocol",
    "ActivePortfolioFund",
    "FundMasterRepository",
    "FundMasterRepositoryProtocol",
    "FundUpsertResult",
    "NavSnapshotCreate",
    "NavSnapshotRepository",
    "NavSnapshotRepositoryProtocol",
    "PortfolioPolicyRepository",
    "PortfolioPolicyRepositoryProtocol",
    "PortfolioPolicyTargetCreate",
    "PortfolioPolicyTargetCreateProtocol",
    "PortfolioRepository",
    "PortfolioRepositoryProtocol",
    "PositionLotRepository",
    "PositionLotRepositoryProtocol",
    "PortfolioSnapshotRepository",
    "PortfolioSnapshotRepositoryProtocol",
    "ReviewReportRepository",
    "ReviewReportRepositoryProtocol",
    "StrategyProposalRepository",
    "StrategyProposalRepositoryProtocol",
    "SystemEventLogRepository",
    "SystemEventLogRepositoryProtocol",
    "TransactionRepository",
    "TransactionRepositoryProtocol",
    "build_portfolio_code_seed",
    "normalize_portfolio_name",
    "resolve_authoritative_position_lots",
]
