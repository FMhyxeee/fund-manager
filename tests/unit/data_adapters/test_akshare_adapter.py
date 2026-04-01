"""Unit tests for the AKShare public fund adapter."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from fund_manager.data_adapters.akshare_adapter import (
    AkshareFundDataAdapter,
    FundNavHistory,
    FundProfile,
    FundSearchResult,
)


class FakeFrame:
    """Minimal DataFrame-like object for adapter tests."""

    def __init__(self, records: Sequence[dict[str, object]]) -> None:
        self._records = list(records)

    @property
    def empty(self) -> bool:
        return not self._records

    def to_dict(self, orient: str) -> list[dict[str, object]]:
        assert orient == "records"
        return list(self._records)


class FakeAkshareClient:
    """Configurable fake AKShare client used by unit tests."""

    def __init__(self) -> None:
        self.search_records: list[dict[str, object]] = []
        self.profile_records: list[dict[str, object]] = []
        self.open_unit_records: list[dict[str, object]] = []
        self.open_accumulated_records: list[dict[str, object]] = []
        self.money_records: list[dict[str, object]] = []
        self.etf_records: list[dict[str, object]] = []
        self.graded_records: list[dict[str, object]] = []
        self.financial_records: list[dict[str, object]] = []
        self.search_failures = 0
        self.profile_failures = 0
        self.search_calls = 0

    def fund_name_em(self) -> FakeFrame:
        self.search_calls += 1
        if self.search_failures > 0:
            self.search_failures -= 1
            msg = "temporary search failure"
            raise RuntimeError(msg)
        return FakeFrame(self.search_records)

    def fund_individual_basic_info_xq(
        self,
        *,
        symbol: str,
        timeout: float | None = None,
    ) -> FakeFrame:
        del symbol, timeout
        if self.profile_failures > 0:
            self.profile_failures -= 1
            msg = "temporary profile failure"
            raise RuntimeError(msg)
        return FakeFrame(self.profile_records)

    def fund_open_fund_info_em(
        self,
        *,
        symbol: str,
        indicator: str,
        period: str,
    ) -> FakeFrame:
        del symbol, period
        if indicator == "单位净值走势":
            return FakeFrame(self.open_unit_records)
        return FakeFrame(self.open_accumulated_records)

    def fund_money_fund_info_em(self, *, symbol: str) -> FakeFrame:
        del symbol
        return FakeFrame(self.money_records)

    def fund_etf_fund_info_em(
        self,
        *,
        fund: str,
        start_date: str,
        end_date: str,
    ) -> FakeFrame:
        del fund, start_date, end_date
        return FakeFrame(self.etf_records)

    def fund_graded_fund_info_em(self, *, symbol: str) -> FakeFrame:
        del symbol
        return FakeFrame(self.graded_records)

    def fund_financial_fund_info_em(self, *, symbol: str) -> FakeFrame:
        del symbol
        return FakeFrame(self.financial_records)


def test_search_fund_returns_normalized_matches_sorted_and_limited() -> None:
    client = FakeAkshareClient()
    client.search_records = [
        {
            "基金代码": "100001",
            "基金简称": "Alpha Income",
            "基金类型": "债券型",
            "拼音缩写": "ALPHAI",
            "拼音全称": "alphaincome",
        },
        {
            "基金代码": "000001",
            "基金简称": "Alpha Growth",
            "基金类型": "混合型",
            "拼音缩写": "ALPHAG",
            "拼音全称": "alphagrowth",
        },
        {
            "基金代码": "000002",
            "基金简称": "Beta Value",
            "基金类型": "股票型",
            "拼音缩写": "BETAV",
            "拼音全称": "betavalue",
        },
    ]
    adapter = AkshareFundDataAdapter(client=client, max_attempts=1, retry_delay_seconds=0)

    results = adapter.search_fund("Alpha", limit=2)

    assert results == (
        FundSearchResult(
            fund_code="000001",
            fund_name="Alpha Growth",
            fund_type="混合型",
            pinyin_abbr="ALPHAG",
            pinyin_full="alphagrowth",
        ),
        FundSearchResult(
            fund_code="100001",
            fund_name="Alpha Income",
            fund_type="债券型",
            pinyin_abbr="ALPHAI",
            pinyin_full="alphaincome",
        ),
    )


def test_get_fund_profile_falls_back_to_search_index_when_detail_endpoint_fails() -> None:
    client = FakeAkshareClient()
    client.search_records = [
        {
            "基金代码": "000001",
            "基金简称": "Alpha Growth",
            "基金类型": "混合型",
            "拼音缩写": "ALPHAG",
            "拼音全称": "alphagrowth",
        }
    ]
    client.profile_failures = 1
    adapter = AkshareFundDataAdapter(client=client, max_attempts=1, retry_delay_seconds=0)

    profile = adapter.get_fund_profile("1")

    assert profile == FundProfile(
        fund_code="000001",
        fund_name="Alpha Growth",
        full_name=None,
        fund_type="混合型",
        inception_date=None,
        latest_scale=None,
        company_name=None,
        manager_name=None,
        custodian_bank=None,
        rating_source=None,
        rating=None,
        investment_strategy=None,
        investment_target=None,
        benchmark=None,
        warnings=(
            "Fund detail endpoint was unavailable; "
            "returned the best available search-index fields.",
        ),
    )


def test_get_fund_nav_history_merges_open_fund_series_and_filters_by_date() -> None:
    client = FakeAkshareClient()
    client.open_unit_records = [
        {"净值日期": "2026-03-01", "单位净值": "1.1000", "日增长率": "0.50"},
        {"净值日期": "2026-03-02", "单位净值": "1.1200", "日增长率": "1.82"},
        {"净值日期": "2026-03-03", "单位净值": "1.1100", "日增长率": "-0.89"},
    ]
    client.open_accumulated_records = [
        {"净值日期": "2026-03-01", "累计净值": "1.3000"},
        {"净值日期": "2026-03-02", "累计净值": "1.3200"},
        {"净值日期": "2026-03-03", "累计净值": "1.3100"},
    ]
    adapter = AkshareFundDataAdapter(client=client, max_attempts=1, retry_delay_seconds=0)

    history = adapter.get_fund_nav_history(
        "000001",
        start_date=date(2026, 3, 2),
        end_date=date(2026, 3, 3),
    )

    assert history == FundNavHistory(
        fund_code="000001",
        requested_start_date=date(2026, 3, 2),
        requested_end_date=date(2026, 3, 3),
        points=(
            history.points[0],
            history.points[1],
        ),
        series_type="open_fund",
        source_endpoint="fund_open_fund_info_em",
    )
    assert history.points[0].nav_date == date(2026, 3, 2)
    assert history.points[0].unit_nav == Decimal("1.1200")
    assert history.points[0].accumulated_nav == Decimal("1.3200")
    assert history.points[0].daily_return_pct == Decimal("1.82")
    assert history.points[1].nav_date == date(2026, 3, 3)
    assert history.points[1].daily_return_pct == Decimal("-0.89")


def test_get_fund_nav_history_falls_back_to_money_market_series() -> None:
    client = FakeAkshareClient()
    client.money_records = [
        {
            "净值日期": "2026-03-02",
            "每万份收益": "0.5500",
            "7日年化收益率": "1.7800",
            "申购状态": "开放申购",
            "赎回状态": "开放赎回",
        }
    ]
    adapter = AkshareFundDataAdapter(client=client, max_attempts=1, retry_delay_seconds=0)

    history = adapter.get_fund_nav_history("000009")

    assert history.series_type == "money_market"
    assert history.source_endpoint == "fund_money_fund_info_em"
    assert history.warnings == (
        "Money-market history does not expose unit or accumulated NAV values.",
    )
    assert history.points == (
        history.points[0],
    )
    assert history.points[0].nav_date == date(2026, 3, 2)
    assert history.points[0].per_million_yield == Decimal("0.5500")
    assert history.points[0].annualized_7d_yield_pct == Decimal("1.7800")
    assert history.points[0].unit_nav is None


def test_search_fund_retries_safe_read_calls_before_succeeding() -> None:
    client = FakeAkshareClient()
    client.search_failures = 1
    client.search_records = [
        {
            "基金代码": "000001",
            "基金简称": "Alpha Growth",
            "基金类型": "混合型",
            "拼音缩写": "ALPHAG",
            "拼音全称": "alphagrowth",
        }
    ]
    sleep_calls: list[float] = []
    adapter = AkshareFundDataAdapter(
        client=client,
        max_attempts=2,
        retry_delay_seconds=0.05,
        sleeper=sleep_calls.append,
    )

    results = adapter.search_fund("Alpha")

    assert client.search_calls == 2
    assert sleep_calls == [0.05]
    assert results[0].fund_code == "000001"


def test_get_fund_nav_history_returns_empty_history_when_all_sources_are_empty() -> None:
    adapter = AkshareFundDataAdapter(
        client=FakeAkshareClient(),
        max_attempts=1,
        retry_delay_seconds=0,
    )

    history = adapter.get_fund_nav_history("000001")

    assert history.series_type is None
    assert history.source_endpoint is None
    assert history.points == ()
