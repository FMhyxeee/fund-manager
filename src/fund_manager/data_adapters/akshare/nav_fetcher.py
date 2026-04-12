"""NAV and yield history fetching helpers for the AKShare adapter."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, cast

from fund_manager.data_adapters.akshare.client import (
    AkshareAdapterError,
    AkshareUpstreamError,
    FundNavHistory,
    FundNavPoint,
    FundNavSeriesType,
    _coerce_date,
)
from fund_manager.data_adapters.akshare.client import (
    _frame_to_records,
    _normalize_fund_code,
    _normalize_text,
    _parse_decimal,
)

if TYPE_CHECKING:
    from fund_manager.data_adapters.akshare.client import AkshareFundDataAdapter


def get_fund_nav_history(
    adapter: "AkshareFundDataAdapter",
    fund_code: str,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> FundNavHistory:
    """Return normalized NAV or yield history with source fallbacks."""
    normalized_code = _normalize_fund_code(fund_code)
    if normalized_code is None:
        msg = "fund_code must not be blank"
        raise ValueError(msg)

    requested_start_date = _coerce_date(start_date)
    requested_end_date = _coerce_date(end_date)
    if (
        requested_start_date is not None
        and requested_end_date is not None
        and requested_start_date > requested_end_date
    ):
        msg = "start_date cannot be after end_date"
        raise ValueError(msg)

    errors: list[str] = []
    successful_empty_fetch = False

    for fetcher in nav_history_fetchers(adapter):
        try:
            history = fetcher(
                normalized_code,
                requested_start_date=requested_start_date,
                requested_end_date=requested_end_date,
            )
        except AkshareAdapterError as exc:
            errors.append(str(exc))
            continue

        if history is None:
            successful_empty_fetch = True
            continue

        return history

    if errors and not successful_empty_fetch:
        raise AkshareUpstreamError("fund_nav_history", "; ".join(errors))

    warnings = []
    if errors:
        warnings.append(
            "Some AKShare NAV endpoints failed while probing supported fund "
            "types; no usable series was returned."
        )

    return FundNavHistory(
        fund_code=normalized_code,
        requested_start_date=requested_start_date,
        requested_end_date=requested_end_date,
        points=(),
        series_type=None,
        source_endpoint=None,
        warnings=tuple(warnings),
    )


def nav_history_fetchers(
    adapter: "AkshareFundDataAdapter",
) -> tuple[
    Callable[..., FundNavHistory | None],
    Callable[..., FundNavHistory | None],
    Callable[..., FundNavHistory | None],
    Callable[..., FundNavHistory | None],
    Callable[..., FundNavHistory | None],
]:
    """Return the ordered list of NAV-history fetch fallbacks."""
    return (
        lambda *args, **kwargs: fetch_open_fund_nav_history(adapter, *args, **kwargs),
        lambda *args, **kwargs: fetch_money_market_nav_history(adapter, *args, **kwargs),
        lambda *args, **kwargs: fetch_exchange_traded_nav_history(adapter, *args, **kwargs),
        lambda *args, **kwargs: fetch_graded_nav_history(adapter, *args, **kwargs),
        lambda *args, **kwargs: fetch_financial_nav_history(adapter, *args, **kwargs),
    )


def fetch_open_fund_nav_history(
    adapter: "AkshareFundDataAdapter",
    fund_code: str,
    *,
    requested_start_date: date | None,
    requested_end_date: date | None,
) -> FundNavHistory | None:
    """Fetch and merge open-fund unit and accumulated NAV series."""
    unit_records = _frame_to_records(
        adapter._call_with_retry(
            "fund_open_fund_info_em",
            symbol=fund_code,
            indicator="单位净值走势",
            period="成立来",
        )
    )
    accumulated_records = _frame_to_records(
        adapter._call_with_retry(
            "fund_open_fund_info_em",
            symbol=fund_code,
            indicator="累计净值走势",
            period="成立来",
        )
    )
    if not unit_records and not accumulated_records:
        return None

    warnings: list[str] = []
    if unit_records and not accumulated_records:
        warnings.append("Accumulated NAV series was unavailable from the open-fund endpoint.")
    if accumulated_records and not unit_records:
        warnings.append("Unit NAV series was unavailable from the open-fund endpoint.")

    point_map: dict[date, dict[str, object]] = {}
    for record in unit_records:
        nav_date = _coerce_date(record.get("净值日期"))
        if nav_date is None:
            continue
        point_map.setdefault(nav_date, {})
        point_map[nav_date]["unit_nav"] = _parse_decimal(record.get("单位净值"))
        point_map[nav_date]["daily_return_pct"] = _parse_decimal(record.get("日增长率"))

    for record in accumulated_records:
        nav_date = _coerce_date(record.get("净值日期"))
        if nav_date is None:
            continue
        point_map.setdefault(nav_date, {})
        point_map[nav_date]["accumulated_nav"] = _parse_decimal(record.get("累计净值"))

    return build_nav_history(
        fund_code=fund_code,
        requested_start_date=requested_start_date,
        requested_end_date=requested_end_date,
        point_map=point_map,
        series_type="open_fund",
        source_endpoint="fund_open_fund_info_em",
        warnings=warnings,
    )


def fetch_money_market_nav_history(
    adapter: "AkshareFundDataAdapter",
    fund_code: str,
    *,
    requested_start_date: date | None,
    requested_end_date: date | None,
) -> FundNavHistory | None:
    """Fetch money-market yield history when standard NAV series are unavailable."""
    records = _frame_to_records(adapter._call_with_retry("fund_money_fund_info_em", symbol=fund_code))
    if not records:
        return None

    point_map: dict[date, dict[str, object]] = {}
    for record in records:
        nav_date = _coerce_date(record.get("净值日期"))
        if nav_date is None:
            continue
        point_map[nav_date] = {
            "per_million_yield": _parse_decimal(record.get("每万份收益")),
            "annualized_7d_yield_pct": _parse_decimal(record.get("7日年化收益率")),
            "purchase_status": _normalize_text(record.get("申购状态")),
            "redemption_status": _normalize_text(record.get("赎回状态")),
        }

    return build_nav_history(
        fund_code=fund_code,
        requested_start_date=requested_start_date,
        requested_end_date=requested_end_date,
        point_map=point_map,
        series_type="money_market",
        source_endpoint="fund_money_fund_info_em",
        warnings=("Money-market history does not expose unit or accumulated NAV values.",),
    )


def fetch_exchange_traded_nav_history(
    adapter: "AkshareFundDataAdapter",
    fund_code: str,
    *,
    requested_start_date: date | None,
    requested_end_date: date | None,
) -> FundNavHistory | None:
    """Fetch ETF-style NAV history."""
    records = _frame_to_records(
        adapter._call_with_retry(
            "fund_etf_fund_info_em",
            fund=fund_code,
            start_date=format_yyyymmdd(requested_start_date, default="20000101"),
            end_date=format_yyyymmdd(requested_end_date, default="20500101"),
        )
    )
    if not records:
        return None

    return build_standard_nav_history(
        fund_code=fund_code,
        records=records,
        requested_start_date=requested_start_date,
        requested_end_date=requested_end_date,
        series_type="exchange_traded",
        source_endpoint="fund_etf_fund_info_em",
    )


def fetch_graded_nav_history(
    adapter: "AkshareFundDataAdapter",
    fund_code: str,
    *,
    requested_start_date: date | None,
    requested_end_date: date | None,
) -> FundNavHistory | None:
    """Fetch graded-fund NAV history."""
    records = _frame_to_records(adapter._call_with_retry("fund_graded_fund_info_em", symbol=fund_code))
    if not records:
        return None

    return build_standard_nav_history(
        fund_code=fund_code,
        records=records,
        requested_start_date=requested_start_date,
        requested_end_date=requested_end_date,
        series_type="graded",
        source_endpoint="fund_graded_fund_info_em",
    )


def fetch_financial_nav_history(
    adapter: "AkshareFundDataAdapter",
    fund_code: str,
    *,
    requested_start_date: date | None,
    requested_end_date: date | None,
) -> FundNavHistory | None:
    """Fetch financial-fund NAV history."""
    records = _frame_to_records(
        adapter._call_with_retry("fund_financial_fund_info_em", symbol=fund_code)
    )
    if not records:
        return None

    return build_standard_nav_history(
        fund_code=fund_code,
        records=records,
        requested_start_date=requested_start_date,
        requested_end_date=requested_end_date,
        series_type="financial",
        source_endpoint="fund_financial_fund_info_em",
    )


def build_standard_nav_history(
    *,
    fund_code: str,
    records: Sequence[Mapping[str, object]],
    requested_start_date: date | None,
    requested_end_date: date | None,
    series_type: FundNavSeriesType,
    source_endpoint: str,
) -> FundNavHistory:
    """Normalize standard NAV endpoints that share the same column layout."""
    point_map: dict[date, dict[str, object]] = {}
    for record in records:
        nav_date = _coerce_date(record.get("净值日期"))
        if nav_date is None:
            continue
        point_map[nav_date] = {
            "unit_nav": _parse_decimal(record.get("单位净值")),
            "accumulated_nav": _parse_decimal(record.get("累计净值")),
            "daily_return_pct": _parse_decimal(record.get("日增长率")),
            "purchase_status": _normalize_text(record.get("申购状态")),
            "redemption_status": _normalize_text(record.get("赎回状态")),
            "dividend_description": _normalize_text(record.get("分红送配")),
        }

    return build_nav_history(
        fund_code=fund_code,
        requested_start_date=requested_start_date,
        requested_end_date=requested_end_date,
        point_map=point_map,
        series_type=series_type,
        source_endpoint=source_endpoint,
        warnings=(),
    )


def build_nav_history(
    *,
    fund_code: str,
    requested_start_date: date | None,
    requested_end_date: date | None,
    point_map: Mapping[date, Mapping[str, object]],
    series_type: FundNavSeriesType,
    source_endpoint: str,
    warnings: Sequence[str],
) -> FundNavHistory:
    """Materialize normalized point maps into an ordered immutable history DTO."""
    points = tuple(
        FundNavPoint(
            nav_date=nav_date,
            unit_nav=cast(Decimal | None, values.get("unit_nav")),
            accumulated_nav=cast(Decimal | None, values.get("accumulated_nav")),
            daily_return_pct=cast(Decimal | None, values.get("daily_return_pct")),
            per_million_yield=cast(Decimal | None, values.get("per_million_yield")),
            annualized_7d_yield_pct=cast(
                Decimal | None,
                values.get("annualized_7d_yield_pct"),
            ),
            purchase_status=cast(str | None, values.get("purchase_status")),
            redemption_status=cast(str | None, values.get("redemption_status")),
            dividend_description=cast(str | None, values.get("dividend_description")),
        )
        for nav_date, values in sorted(point_map.items())
        if date_in_range(nav_date, requested_start_date, requested_end_date)
    )
    return FundNavHistory(
        fund_code=fund_code,
        requested_start_date=requested_start_date,
        requested_end_date=requested_end_date,
        points=points,
        series_type=series_type,
        source_endpoint=source_endpoint,
        warnings=tuple(warnings),
    )


def date_in_range(
    value: date,
    start_date: date | None,
    end_date: date | None,
) -> bool:
    """Return whether one NAV date falls inside the requested bounds."""
    if start_date is not None and value < start_date:
        return False
    if end_date is not None and value > end_date:
        return False
    return True


def format_yyyymmdd(value: date | None, *, default: str) -> str:
    """Format a date for AKShare endpoints that expect YYYYMMDD strings."""
    if value is None:
        return default
    return value.strftime("%Y%m%d")
