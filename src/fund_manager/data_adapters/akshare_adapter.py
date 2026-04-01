"""AKShare-backed public fund data adapter.

This module keeps all AKShare endpoint names, response shapes, and Chinese
column mappings inside the adapter layer. Callers only see normalized internal
DTOs and do not depend on third-party payload details.

Extension points:
- add new public-data endpoints by extending ``AkshareFundDataAdapter`` with a
  new fetch helper that returns one of the DTOs below
- enrich ``FundProfile`` by mapping additional AKShare item/value fields here
- support more fund NAV sources by appending another fetcher in
  ``_nav_history_fetchers``
"""

from __future__ import annotations

import importlib
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from typing import Any, Literal, Protocol, cast

FundNavSeriesType = Literal[
    "open_fund",
    "money_market",
    "exchange_traded",
    "graded",
    "financial",
]

_DEFAULT_SOURCE = "akshare"


@dataclass(frozen=True)
class FundSearchResult:
    """Normalized fund match from the AKShare search index."""

    fund_code: str
    fund_name: str
    fund_type: str | None
    pinyin_abbr: str | None
    pinyin_full: str | None
    source: str = _DEFAULT_SOURCE


@dataclass(frozen=True)
class FundProfile:
    """Normalized public profile for one fund."""

    fund_code: str
    fund_name: str | None
    full_name: str | None
    fund_type: str | None
    inception_date: date | None
    latest_scale: str | None
    company_name: str | None
    manager_name: str | None
    custodian_bank: str | None
    rating_source: str | None
    rating: str | None
    investment_strategy: str | None
    investment_target: str | None
    benchmark: str | None
    source: str = _DEFAULT_SOURCE
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class FundNavPoint:
    """One normalized NAV or yield observation."""

    nav_date: date
    unit_nav: Decimal | None = None
    accumulated_nav: Decimal | None = None
    daily_return_pct: Decimal | None = None
    per_million_yield: Decimal | None = None
    annualized_7d_yield_pct: Decimal | None = None
    purchase_status: str | None = None
    redemption_status: str | None = None
    dividend_description: str | None = None


@dataclass(frozen=True)
class FundNavHistory:
    """Normalized NAV or yield history for one fund."""

    fund_code: str
    requested_start_date: date | None
    requested_end_date: date | None
    points: tuple[FundNavPoint, ...]
    series_type: FundNavSeriesType | None
    source_endpoint: str | None
    source: str = _DEFAULT_SOURCE
    warnings: tuple[str, ...] = ()


class AkshareAdapterError(RuntimeError):
    """Base exception for adapter failures."""


class AkshareDependencyError(AkshareAdapterError):
    """Raised when the optional AKShare dependency is unavailable."""


class AkshareUpstreamError(AkshareAdapterError):
    """Raised when AKShare calls fail after retrying."""

    def __init__(self, endpoint_name: str, details: str) -> None:
        self.endpoint_name = endpoint_name
        super().__init__(f"AKShare endpoint '{endpoint_name}' failed: {details}")


class AkshareClientProtocol(Protocol):
    """Minimal protocol for the AKShare fund endpoints used in v1."""

    def fund_name_em(self) -> Any: ...

    def fund_individual_basic_info_xq(
        self,
        symbol: str = ...,
        timeout: float | None = ...,
    ) -> Any: ...

    def fund_open_fund_info_em(
        self,
        symbol: str = ...,
        indicator: str = ...,
        period: str = ...,
    ) -> Any: ...

    def fund_money_fund_info_em(self, symbol: str = ...) -> Any: ...

    def fund_etf_fund_info_em(
        self,
        fund: str = ...,
        start_date: str = ...,
        end_date: str = ...,
    ) -> Any: ...

    def fund_graded_fund_info_em(self, symbol: str = ...) -> Any: ...

    def fund_financial_fund_info_em(self, symbol: str = ...) -> Any: ...


@dataclass
class AkshareFundDataAdapter:
    """Read-only adapter that normalizes public fund data from AKShare."""

    client: AkshareClientProtocol | None = None
    max_attempts: int = 3
    retry_delay_seconds: float = 0.25
    request_timeout: float | None = 10.0
    sleeper: Callable[[float], None] = time.sleep
    _search_index_cache: tuple[FundSearchResult, ...] | None = field(
        default=None,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            msg = "max_attempts must be at least 1"
            raise ValueError(msg)
        if self.retry_delay_seconds < 0:
            msg = "retry_delay_seconds cannot be negative"
            raise ValueError(msg)
        if self.request_timeout is not None and self.request_timeout <= 0:
            msg = "request_timeout must be positive when provided"
            raise ValueError(msg)

    def search_fund(self, query: str, *, limit: int = 20) -> tuple[FundSearchResult, ...]:
        """Search the public fund index by code, Chinese name, or pinyin."""
        normalized_query = _normalize_text(query)
        if normalized_query is None or limit <= 0:
            return ()

        matches = [
            entry
            for entry in self._get_search_index()
            if _matches_search_query(entry, normalized_query)
        ]
        matches.sort(key=lambda entry: _search_sort_key(entry, normalized_query))
        return tuple(matches[:limit])

    def get_fund_profile(self, fund_code: str) -> FundProfile | None:
        """Return one normalized public profile, or ``None`` when unavailable."""
        normalized_code = _normalize_fund_code(fund_code)
        if normalized_code is None:
            msg = "fund_code must not be blank"
            raise ValueError(msg)

        warnings: list[str] = []
        exact_match: FundSearchResult | None = None
        profile_items: dict[str, str] = {}
        search_error: AkshareAdapterError | None = None
        profile_error: AkshareAdapterError | None = None

        try:
            exact_match = self._find_exact_search_match(normalized_code)
        except AkshareAdapterError as exc:
            search_error = exc

        try:
            profile_items = self._fetch_profile_items(normalized_code)
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

    def get_fund_nav_history(
        self,
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

        for fetcher in self._nav_history_fetchers():
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

    def _get_search_index(self) -> tuple[FundSearchResult, ...]:
        if self._search_index_cache is not None:
            return self._search_index_cache

        records = _frame_to_records(self._call_with_retry("fund_name_em"))
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
            self._search_index_cache = normalized_results
        return normalized_results

    def _find_exact_search_match(self, fund_code: str) -> FundSearchResult | None:
        for entry in self._get_search_index():
            if entry.fund_code == fund_code:
                return entry
        return None

    def _fetch_profile_items(self, fund_code: str) -> dict[str, str]:
        frame = self._call_with_retry(
            "fund_individual_basic_info_xq",
            symbol=fund_code,
            timeout=self.request_timeout,
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

    def _nav_history_fetchers(
        self,
    ) -> tuple[
        Callable[..., FundNavHistory | None],
        Callable[..., FundNavHistory | None],
        Callable[..., FundNavHistory | None],
        Callable[..., FundNavHistory | None],
        Callable[..., FundNavHistory | None],
    ]:
        return (
            self._fetch_open_fund_nav_history,
            self._fetch_money_market_nav_history,
            self._fetch_exchange_traded_nav_history,
            self._fetch_graded_nav_history,
            self._fetch_financial_nav_history,
        )

    def _fetch_open_fund_nav_history(
        self,
        fund_code: str,
        *,
        requested_start_date: date | None,
        requested_end_date: date | None,
    ) -> FundNavHistory | None:
        unit_records = _frame_to_records(
            self._call_with_retry(
                "fund_open_fund_info_em",
                symbol=fund_code,
                indicator="单位净值走势",
                period="成立来",
            )
        )
        accumulated_records = _frame_to_records(
            self._call_with_retry(
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

        return self._build_nav_history(
            fund_code=fund_code,
            requested_start_date=requested_start_date,
            requested_end_date=requested_end_date,
            point_map=point_map,
            series_type="open_fund",
            source_endpoint="fund_open_fund_info_em",
            warnings=warnings,
        )

    def _fetch_money_market_nav_history(
        self,
        fund_code: str,
        *,
        requested_start_date: date | None,
        requested_end_date: date | None,
    ) -> FundNavHistory | None:
        records = _frame_to_records(
            self._call_with_retry("fund_money_fund_info_em", symbol=fund_code)
        )
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

        return self._build_nav_history(
            fund_code=fund_code,
            requested_start_date=requested_start_date,
            requested_end_date=requested_end_date,
            point_map=point_map,
            series_type="money_market",
            source_endpoint="fund_money_fund_info_em",
            warnings=("Money-market history does not expose unit or accumulated NAV values.",),
        )

    def _fetch_exchange_traded_nav_history(
        self,
        fund_code: str,
        *,
        requested_start_date: date | None,
        requested_end_date: date | None,
    ) -> FundNavHistory | None:
        records = _frame_to_records(
            self._call_with_retry(
                "fund_etf_fund_info_em",
                fund=fund_code,
                start_date=_format_yyyymmdd(requested_start_date, default="20000101"),
                end_date=_format_yyyymmdd(requested_end_date, default="20500101"),
            )
        )
        if not records:
            return None

        return self._build_standard_nav_history(
            fund_code=fund_code,
            records=records,
            requested_start_date=requested_start_date,
            requested_end_date=requested_end_date,
            series_type="exchange_traded",
            source_endpoint="fund_etf_fund_info_em",
        )

    def _fetch_graded_nav_history(
        self,
        fund_code: str,
        *,
        requested_start_date: date | None,
        requested_end_date: date | None,
    ) -> FundNavHistory | None:
        records = _frame_to_records(
            self._call_with_retry("fund_graded_fund_info_em", symbol=fund_code)
        )
        if not records:
            return None

        return self._build_standard_nav_history(
            fund_code=fund_code,
            records=records,
            requested_start_date=requested_start_date,
            requested_end_date=requested_end_date,
            series_type="graded",
            source_endpoint="fund_graded_fund_info_em",
        )

    def _fetch_financial_nav_history(
        self,
        fund_code: str,
        *,
        requested_start_date: date | None,
        requested_end_date: date | None,
    ) -> FundNavHistory | None:
        records = _frame_to_records(
            self._call_with_retry("fund_financial_fund_info_em", symbol=fund_code)
        )
        if not records:
            return None

        return self._build_standard_nav_history(
            fund_code=fund_code,
            records=records,
            requested_start_date=requested_start_date,
            requested_end_date=requested_end_date,
            series_type="financial",
            source_endpoint="fund_financial_fund_info_em",
        )

    def _build_standard_nav_history(
        self,
        *,
        fund_code: str,
        records: Sequence[Mapping[str, object]],
        requested_start_date: date | None,
        requested_end_date: date | None,
        series_type: FundNavSeriesType,
        source_endpoint: str,
    ) -> FundNavHistory:
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

        return self._build_nav_history(
            fund_code=fund_code,
            requested_start_date=requested_start_date,
            requested_end_date=requested_end_date,
            point_map=point_map,
            series_type=series_type,
            source_endpoint=source_endpoint,
            warnings=(),
        )

    def _build_nav_history(
        self,
        *,
        fund_code: str,
        requested_start_date: date | None,
        requested_end_date: date | None,
        point_map: Mapping[date, Mapping[str, object]],
        series_type: FundNavSeriesType,
        source_endpoint: str,
        warnings: Sequence[str],
    ) -> FundNavHistory:
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
            if _date_in_range(nav_date, requested_start_date, requested_end_date)
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

    def _call_with_retry(self, endpoint_name: str, /, **kwargs: object) -> object:
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                client = self.client or _load_akshare_client()
                endpoint = getattr(client, endpoint_name)
                return endpoint(**kwargs)
            except AkshareDependencyError:
                raise
            except Exception as exc:  # pragma: no cover - exercised via tests
                last_error = exc
                if attempt >= self.max_attempts:
                    break
                if self.retry_delay_seconds > 0:
                    self.sleeper(self.retry_delay_seconds * attempt)

        if last_error is None:
            msg = "AKShare call failed without an exception"
            raise AkshareUpstreamError(endpoint_name, msg)
        raise AkshareUpstreamError(endpoint_name, str(last_error)) from last_error


@lru_cache
def get_default_akshare_fund_data_adapter() -> AkshareFundDataAdapter:
    """Return a lazily configured shared adapter instance."""
    return AkshareFundDataAdapter()


def search_fund(query: str, *, limit: int = 20) -> tuple[FundSearchResult, ...]:
    """Convenience wrapper around the shared AKShare fund adapter."""
    return get_default_akshare_fund_data_adapter().search_fund(query, limit=limit)


def get_fund_profile(fund_code: str) -> FundProfile | None:
    """Convenience wrapper around the shared AKShare fund adapter."""
    return get_default_akshare_fund_data_adapter().get_fund_profile(fund_code)


def get_fund_nav_history(
    fund_code: str,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> FundNavHistory:
    """Convenience wrapper around the shared AKShare fund adapter."""
    return get_default_akshare_fund_data_adapter().get_fund_nav_history(
        fund_code,
        start_date=start_date,
        end_date=end_date,
    )


def _load_akshare_client() -> AkshareClientProtocol:
    try:
        ak = importlib.import_module("akshare")
    except ImportError as exc:  # pragma: no cover - depends on optional install state
        msg = (
            "AKShare is not installed. Install optional data dependencies with "
            "`uv sync --extra data`."
        )
        raise AkshareDependencyError(msg) from exc
    return cast(AkshareClientProtocol, ak)


def _frame_to_records(frame: object) -> list[Mapping[str, object]]:
    if frame is None:
        return []

    empty = getattr(frame, "empty", None)
    if isinstance(empty, bool) and empty:
        return []

    to_dict = getattr(frame, "to_dict", None)
    if callable(to_dict):
        records = to_dict("records")
        if isinstance(records, list):
            return [
                cast(Mapping[str, object], record)
                for record in records
                if isinstance(record, Mapping)
            ]

    if isinstance(frame, Sequence) and not isinstance(frame, (str, bytes)):
        return [
            cast(Mapping[str, object], record)
            for record in frame
            if isinstance(record, Mapping)
        ]

    msg = "AKShare response object is not convertible to record dictionaries"
    raise AkshareAdapterError(msg)


def _matches_search_query(result: FundSearchResult, query: str) -> bool:
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


def _search_sort_key(result: FundSearchResult, query: str) -> tuple[int, int, int, int, str]:
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


def _coalesce(*values: str | None) -> str | None:
    for value in values:
        if value is not None:
            return value
    return None


def _normalize_fund_code(value: object) -> str | None:
    text = _normalize_text(value)
    if text is None:
        return None
    if text.isdigit() and len(text) <= 6:
        return text.zfill(6)
    return text


def _normalize_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    date_method = getattr(value, "date", None)
    if callable(date_method):
        try:
            maybe_date = date_method()
        except TypeError:
            maybe_date = None
        if isinstance(maybe_date, date):
            return maybe_date

    text = _normalize_text(value)
    if text is None:
        return None

    for parser in (date.fromisoformat, _parse_yyyymmdd_date):
        try:
            return parser(text)
        except ValueError:
            continue
    return None


def _parse_yyyymmdd_date(value: str) -> date:
    if len(value) != 8 or not value.isdigit():
        msg = "expected YYYYMMDD format"
        raise ValueError(msg)
    return date.fromisoformat(f"{value[:4]}-{value[4:6]}-{value[6:]}")


def _parse_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int | float):
        text = str(value)
    else:
        text = str(value).strip().replace(",", "").rstrip("%")

    if not text or text.casefold() in {"nan", "none", "null", "nat"}:
        return None

    try:
        parsed = Decimal(text)
    except InvalidOperation:
        return None
    if not parsed.is_finite():
        return None
    return parsed


def _date_in_range(
    value: date,
    start_date: date | None,
    end_date: date | None,
) -> bool:
    if start_date is not None and value < start_date:
        return False
    if end_date is not None and value > end_date:
        return False
    return True


def _format_yyyymmdd(value: date | None, *, default: str) -> str:
    if value is None:
        return default
    return value.strftime("%Y%m%d")


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
