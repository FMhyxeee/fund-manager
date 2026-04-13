"""AKShare-backed public fund data adapter package."""

from fund_manager.data_adapters.akshare.client import (
    AkshareAdapterError,
    AkshareDependencyError,
    AkshareFundDataAdapter,
    AkshareUpstreamError,
    FundNavHistory,
    FundNavPoint,
    FundProfile,
    FundSearchResult,
    get_default_akshare_fund_data_adapter,
    get_fund_nav_history,
    get_fund_profile,
    search_fund,
)

__all__ = [
    "AkshareAdapterError",
    "AkshareDependencyError",
    "AkshareFundDataAdapter",
    "AkshareUpstreamError",
    "FundNavHistory",
    "FundNavPoint",
    "FundProfile",
    "FundSearchResult",
    "get_default_akshare_fund_data_adapter",
    "get_fund_nav_history",
    "get_fund_profile",
    "search_fund",
]
