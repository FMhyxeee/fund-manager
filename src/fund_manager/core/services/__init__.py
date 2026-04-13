"""Deterministic business services."""

from typing import Any

from fund_manager.core.services.analytics_service import (
    AnalyticsService,
    PortfolioMetrics,
    PortfolioPerformanceMetrics,
    PositionMetrics,
)
from fund_manager.core.services.decision_feedback_service import (
    DecisionActionNotFoundError,
    DecisionFeedbackError,
    DecisionFeedbackRecordResult,
    DecisionFeedbackService,
    DecisionRunNotFoundError,
)
from fund_manager.core.services.decision_reconciliation_service import (
    DecisionReconciliationService,
)
from fund_manager.core.services.decision_service import (
    DECISION_ENGINE_NAME,
    DecisionActionDTO,
    DecisionService,
    PortfolioDecisionDTO,
)
from fund_manager.core.services.fund_data_sync_service import (
    FundDataSyncService,
    FundSyncDetailDTO,
    PortfolioFundSyncResultDTO,
)
from fund_manager.core.services.policy_service import (
    PolicyService,
    PortfolioPolicyDTO,
    PortfolioPolicyTargetDTO,
)
from fund_manager.core.services.portfolio_read_service import (
    PortfolioReadService,
    PortfolioSnapshotReadResult,
    PortfolioSummaryDTO,
    PositionBreakdownReadResult,
)
from fund_manager.core.services.portfolio_service import (
    IncompletePortfolioSnapshotError,
    PortfolioNotFoundError,
    PortfolioPositionDTO,
    PortfolioService,
    PortfolioSnapshotDTO,
    PortfolioValuationDTO,
)
from fund_manager.core.services.transaction_lot_sync_service import (
    TRANSACTION_AGGREGATE_LOT_PREFIX,
    TransactionLotSyncResult,
    TransactionLotSyncService,
)

__all__ = [
    "AnalyticsService",
    "DECISION_ENGINE_NAME",
    "DecisionActionNotFoundError",
    "DecisionActionDTO",
    "DecisionFeedbackError",
    "DecisionFeedbackRecordResult",
    "DecisionFeedbackService",
    "DecisionReconciliationService",
    "DecisionService",
    "DecisionRunNotFoundError",
    "FundDataSyncService",
    "FundSyncDetailDTO",
    "IncompletePortfolioSnapshotError",
    "PortfolioMetrics",
    "PolicyService",
    "PortfolioDecisionDTO",
    "PortfolioPolicyDTO",
    "PortfolioPolicyTargetDTO",
    "PortfolioReadService",
    "PortfolioFundSyncResultDTO",
    "PortfolioNotFoundError",
    "PortfolioPerformanceMetrics",
    "PortfolioPositionDTO",
    "PortfolioSnapshotReadResult",
    "PortfolioService",
    "PortfolioSnapshotDTO",
    "PortfolioSummaryDTO",
    "PortfolioValuationDTO",
    "PositionBreakdownReadResult",
    "PositionMetrics",
    "TRANSACTION_AGGREGATE_LOT_PREFIX",
    "TransactionLotSyncResult",
    "TransactionLotSyncService",
    "CandidateFitAnalysisDTO",
    "FundLeaderDTO",
    "FundWatchlistService",
    "WatchlistCandidateDTO",
    "WatchlistResultDTO",
]

_WATCHLIST_EXPORTS = {
    "CandidateFitAnalysisDTO",
    "FundLeaderDTO",
    "FundWatchlistService",
    "WatchlistCandidateDTO",
    "WatchlistResultDTO",
}


def __getattr__(name: str) -> Any:
    if name not in _WATCHLIST_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    from fund_manager.core.watchlist import (
        CandidateFitAnalysisDTO,
        FundLeaderDTO,
        FundWatchlistService,
        WatchlistCandidateDTO,
        WatchlistResultDTO,
    )

    exports = {
        "CandidateFitAnalysisDTO": CandidateFitAnalysisDTO,
        "FundLeaderDTO": FundLeaderDTO,
        "FundWatchlistService": FundWatchlistService,
        "WatchlistCandidateDTO": WatchlistCandidateDTO,
        "WatchlistResultDTO": WatchlistResultDTO,
    }
    return exports[name]
