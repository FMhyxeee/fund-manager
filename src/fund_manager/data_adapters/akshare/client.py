"""AKShare client shell, shared DTOs, and shared normalization helpers."""

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
        from fund_manager.data_adapters.akshare.search_fetcher import search_fund

        return search_fund(self, query, limit=limit)

    def get_fund_profile(self, fund_code: str) -> FundProfile | None:
        """Return one normalized public profile, or None when unavailable."""
        from fund_manager.data_adapters.akshare.profile_fetcher import get_fund_profile

        return get_fund_profile(self, fund_code)

    def get_fund_nav_history(
        self,
        fund_code: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> FundNavHistory:
        """Return normalized NAV or yield history with source fallbacks."""
        from fund_manager.data_adapters.akshare.nav_fetcher import get_fund_nav_history

        return get_fund_nav_history(
            self,
            fund_code,
            start_date=start_date,
            end_date=end_date,
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
