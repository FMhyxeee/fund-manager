"""Backward-compatible re-export for the AKShare public fund adapter."""

from datetime import date

from fund_manager.data_adapters.akshare import (
    AkshareAdapterError,
    AkshareDependencyError,
    AkshareFundDataAdapter,
    AkshareUpstreamError,
    FundNavHistory,
    FundNavPoint,
    FundProfile,
    FundSearchResult,
)

from fund_manager.data_adapters.akshare import (
    get_default_akshare_fund_data_adapter as _get_default_akshare_fund_data_adapter,
)


def get_default_akshare_fund_data_adapter() -> AkshareFundDataAdapter:
    """Return the shared adapter via the legacy module entrypoint."""
    return _get_default_akshare_fund_data_adapter()


def search_fund(query: str, *, limit: int = 20) -> tuple[FundSearchResult, ...]:
    """Legacy wrapper that preserves monkeypatchability on this module."""
    return get_default_akshare_fund_data_adapter().search_fund(query, limit=limit)


def get_fund_profile(fund_code: str) -> FundProfile | None:
    """Legacy wrapper that preserves monkeypatchability on this module."""
    return get_default_akshare_fund_data_adapter().get_fund_profile(fund_code)


def get_fund_nav_history(
    fund_code: str,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> FundNavHistory:
    """Legacy wrapper that preserves monkeypatchability on this module."""
    return get_default_akshare_fund_data_adapter().get_fund_nav_history(
        fund_code,
        start_date=start_date,
        end_date=end_date,
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
