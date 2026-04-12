"""Fund profile fetching helpers for the AKShare adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fund_manager.data_adapters.akshare.client import (
    AkshareAdapterError,
    FundProfile,
    _coalesce,
    _coerce_date,
    _frame_to_records,
    _normalize_fund_code,
    _normalize_text,
)
from fund_manager.data_adapters.akshare.search_fetcher import find_exact_search_match

if TYPE_CHECKING:
    from fund_manager.data_adapters.akshare.client import AkshareFundDataAdapter


def get_fund_profile(
    adapter: "AkshareFundDataAdapter",
    fund_code: str,
) -> FundProfile | None:
    """Return one normalized public profile, or None when unavailable."""
    normalized_code = _normalize_fund_code(fund_code)
    if normalized_code is None:
        msg = "fund_code must not be blank"
        raise ValueError(msg)

    warnings: list[str] = []
    exact_match = None
    profile_items: dict[str, str] = {}
    search_error: AkshareAdapterError | None = None
    profile_error: AkshareAdapterError | None = None

    try:
        exact_match = find_exact_search_match(adapter, normalized_code)
    except AkshareAdapterError as exc:
        search_error = exc

    try:
        profile_items = fetch_profile_items(adapter, normalized_code)
    except AkshareAdapterError as exc:
        profile_error = exc

    if not profile_items and exact_match is None:
        if profile_error is not None:
            raise profile_error
        if search_error is not None:
            raise search_error
        return None

    if profile_error is not None and exact_match is not None:
        warnings.append(
            "Fund detail endpoint was unavailable; "
            "returned the best available search-index fields."
        )
    if search_error is not None and profile_items:
        warnings.append(
            "Fund search index was unavailable; "
            "returned detail fields without index enrichment."
        )

    return FundProfile(
        fund_code=normalized_code,
        fund_name=_coalesce(
            profile_items.get("基金名称"),
            exact_match.fund_name if exact_match is not None else None,
        ),
        full_name=profile_items.get("基金全称"),
        fund_type=_coalesce(
            profile_items.get("基金类型"),
            exact_match.fund_type if exact_match is not None else None,
        ),
        inception_date=_coerce_date(profile_items.get("成立时间")),
        latest_scale=profile_items.get("最新规模"),
        company_name=profile_items.get("基金公司"),
        manager_name=profile_items.get("基金经理"),
        custodian_bank=profile_items.get("托管银行"),
        rating_source=profile_items.get("评级机构"),
        rating=profile_items.get("基金评级"),
        investment_strategy=profile_items.get("投资策略"),
        investment_target=profile_items.get("投资目标"),
        benchmark=profile_items.get("业绩比较基准"),
        warnings=tuple(warnings),
    )


def fetch_profile_items(
    adapter: "AkshareFundDataAdapter",
    fund_code: str,
) -> dict[str, str]:
    """Load the AKShare detail item/value pairs for one fund."""
    frame = adapter._call_with_retry(
        "fund_individual_basic_info_xq",
        symbol=fund_code,
        timeout=adapter.request_timeout,
    )
    records = _frame_to_records(frame)
    item_map: dict[str, str] = {}
    for record in records:
        item_name = _normalize_text(record.get("item"))
        item_value = _normalize_text(record.get("value"))
        if item_name is None or item_value is None:
            continue
        item_map[item_name] = item_value
    return item_map
