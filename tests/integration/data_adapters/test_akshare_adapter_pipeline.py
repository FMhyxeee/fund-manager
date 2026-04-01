"""Integration-style tests for the AKShare adapter public entrypoints."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from fund_manager.data_adapters import akshare_adapter
from fund_manager.data_adapters.akshare_adapter import AkshareFundDataAdapter


class FakeFrame:
    """Minimal DataFrame-like object for adapter entrypoint tests."""

    def __init__(self, records: Sequence[dict[str, object]]) -> None:
        self._records = list(records)

    @property
    def empty(self) -> bool:
        return not self._records

    def to_dict(self, orient: str) -> list[dict[str, object]]:
        assert orient == "records"
        return list(self._records)


class FakeAkshareClient:
    """Configurable fake AKShare client for entrypoint tests."""

    def __init__(self) -> None:
        self.search_records: list[dict[str, object]] = []
        self.profile_records: list[dict[str, object]] = []
        self.open_unit_records: list[dict[str, object]] = []
        self.open_accumulated_records: list[dict[str, object]] = []

    def fund_name_em(self) -> FakeFrame:
        return FakeFrame(self.search_records)

    def fund_individual_basic_info_xq(
        self,
        *,
        symbol: str,
        timeout: float | None = None,
    ) -> FakeFrame:
        del symbol, timeout
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
        return FakeFrame([])

    def fund_etf_fund_info_em(
        self,
        *,
        fund: str,
        start_date: str,
        end_date: str,
    ) -> FakeFrame:
        del fund, start_date, end_date
        return FakeFrame([])

    def fund_graded_fund_info_em(self, *, symbol: str) -> FakeFrame:
        del symbol
        return FakeFrame([])

    def fund_financial_fund_info_em(self, *, symbol: str) -> FakeFrame:
        del symbol
        return FakeFrame([])


def test_public_adapter_functions_use_the_shared_normalized_adapter(monkeypatch) -> None:
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
    client.profile_records = [
        {"item": "基金代码", "value": "000001"},
        {"item": "基金名称", "value": "Alpha Growth"},
        {"item": "基金全称", "value": "Alpha Growth Mixed Fund"},
        {"item": "基金类型", "value": "混合型"},
        {"item": "成立时间", "value": "2020-01-01"},
        {"item": "基金公司", "value": "Alpha AMC"},
        {"item": "基金经理", "value": "Manager A"},
        {"item": "业绩比较基准", "value": "CSI 300"},
    ]
    client.open_unit_records = [
        {"净值日期": "2026-03-01", "单位净值": "1.1000", "日增长率": "0.50"},
        {"净值日期": "2026-03-02", "单位净值": "1.1200", "日增长率": "1.82"},
    ]
    client.open_accumulated_records = [
        {"净值日期": "2026-03-01", "累计净值": "1.3000"},
        {"净值日期": "2026-03-02", "累计净值": "1.3200"},
    ]
    adapter = AkshareFundDataAdapter(client=client, max_attempts=1, retry_delay_seconds=0)
    monkeypatch.setattr(
        akshare_adapter,
        "get_default_akshare_fund_data_adapter",
        lambda: adapter,
    )

    search_results = akshare_adapter.search_fund("Alpha")
    profile = akshare_adapter.get_fund_profile("000001")
    history = akshare_adapter.get_fund_nav_history(
        "000001",
        start_date=date(2026, 3, 2),
        end_date=date(2026, 3, 2),
    )

    assert search_results[0].fund_name == "Alpha Growth"
    assert profile is not None
    assert profile.full_name == "Alpha Growth Mixed Fund"
    assert profile.company_name == "Alpha AMC"
    assert profile.benchmark == "CSI 300"
    assert history.series_type == "open_fund"
    assert len(history.points) == 1
    assert history.points[0].nav_date == date(2026, 3, 2)
    assert history.points[0].unit_nav == Decimal("1.1200")
    assert history.points[0].accumulated_nav == Decimal("1.3200")
