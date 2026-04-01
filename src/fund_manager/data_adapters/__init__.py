"""External data acquisition and normalization adapters."""

from fund_manager.data_adapters.akshare_adapter import (
    AkshareFundDataAdapter,
    FundNavHistory,
    FundNavPoint,
    FundProfile,
    FundSearchResult,
    get_fund_nav_history,
    get_fund_profile,
    search_fund,
)
from fund_manager.data_adapters.import_holdings import (
    HoldingsImporter,
    HoldingsImportSummary,
    import_holdings_csv,
)
from fund_manager.data_adapters.import_transactions import (
    TransactionsImporter,
    TransactionsImportSummary,
    import_transactions_csv,
)

__all__ = [
    "AkshareFundDataAdapter",
    "FundNavHistory",
    "FundNavPoint",
    "FundProfile",
    "FundSearchResult",
    "HoldingsImportSummary",
    "HoldingsImporter",
    "TransactionsImportSummary",
    "TransactionsImporter",
    "get_fund_nav_history",
    "get_fund_profile",
    "import_holdings_csv",
    "import_transactions_csv",
    "search_fund",
]
