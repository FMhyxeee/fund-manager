"""Search-index loading and query helpers for the AKShare adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fund_manager.data_adapters.akshare.client import (
    FundSearchResult,
    _frame_to_records,
    _normalize_fund_code,
    _normalize_text,
)

if TYPE_CHECKING:
    from fund_manager.data_adapters.akshare.client import AkshareFundDataAdapter


def search_fund(
    adapter: "AkshareFundDataAdapter",
    query: str,
    *,
    limit: int = 20,
) -> tuple[FundSearchResult, ...]:
    """Search the public fund index by code, Chinese name, or pinyin."""
    normalized_query = _normalize_text(query)
    if normalized_query is None or limit <= 0:
        return ()

    matches = [
        entry
        for entry in get_search_index(adapter)
        if matches_search_query(entry, normalized_query)
    ]
    matches.sort(key=lambda entry: search_sort_key(entry, normalized_query))
    return tuple(matches[:limit])


def get_search_index(adapter: "AkshareFundDataAdapter") -> tuple[FundSearchResult, ...]:
    """Load and cache the normalized AKShare search index."""
    if adapter._search_index_cache is not None:
        return adapter._search_index_cache

    records = _frame_to_records(adapter._call_with_retry("fund_name_em"))
    normalized_results = tuple(
        FundSearchResult(
            fund_code=fund_code,
            fund_name=fund_name,
            fund_type=_normalize_text(record.get("基金类型")),
            pinyin_abbr=_normalize_text(record.get("拼音缩写")),
            pinyin_full=_normalize_text(record.get("拼音全称")),
        )
        for record in records
        if (fund_code := _normalize_fund_code(record.get("基金代码"))) is not None
        and (fund_name := _normalize_text(record.get("基金简称"))) is not None
    )

    if normalized_results:
        adapter._search_index_cache = normalized_results
    return normalized_results


def find_exact_search_match(
    adapter: "AkshareFundDataAdapter",
    fund_code: str,
) -> FundSearchResult | None:
    """Resolve one exact search-index match by normalized fund code."""
    for entry in get_search_index(adapter):
        if entry.fund_code == fund_code:
            return entry
    return None


def matches_search_query(result: FundSearchResult, query: str) -> bool:
    """Return whether a normalized search result matches the query."""
    query_key = query.casefold()
    return any(
        query_key in candidate.casefold()
        for candidate in (
            result.fund_code,
            result.fund_name,
            result.pinyin_abbr or "",
            result.pinyin_full or "",
        )
    )


def search_sort_key(result: FundSearchResult, query: str) -> tuple[int, int, int, int, str]:
    """Sort exact and prefix matches ahead of loose partial matches."""
    query_key = query.casefold()
    exact_code_match = int(result.fund_code != query)
    exact_name_match = int(result.fund_name.casefold() != query_key)
    prefix_code_match = int(not result.fund_code.startswith(query))
    prefix_name_match = int(not result.fund_name.casefold().startswith(query_key))
    return (
        exact_code_match,
        exact_name_match,
        prefix_code_match,
        prefix_name_match,
        result.fund_code,
    )
