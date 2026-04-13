"""Integration tests for syncing held-fund public data into canonical storage."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from fund_manager.core.services import FundDataSyncService
from fund_manager.data_adapters.akshare_adapter import (
    AkshareAdapterError,
    FundNavHistory,
    FundNavPoint,
    FundProfile,
)
from fund_manager.storage.models import Base, FundMaster, NavSnapshot, Portfolio, PositionLot


class FakeFundDataAdapter:
    """Configurable adapter for storage-backed sync tests."""

    def __init__(self) -> None:
        self.profile_responses: dict[str, FundProfile | None] = {}
        self.nav_responses: dict[str, FundNavHistory] = {}
        self.profile_errors: dict[str, str] = {}
        self.nav_errors: dict[str, str] = {}
        self.nav_calls: list[tuple[str, date | None, date | None]] = []

    def get_fund_profile(self, fund_code: str) -> FundProfile | None:
        if fund_code in self.profile_errors:
            raise AkshareAdapterError(self.profile_errors[fund_code])
        return self.profile_responses.get(fund_code)

    def get_fund_nav_history(
        self,
        fund_code: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> FundNavHistory:
        self.nav_calls.append((fund_code, start_date, end_date))
        if fund_code in self.nav_errors:
            raise AkshareAdapterError(self.nav_errors[fund_code])
        return self.nav_responses[fund_code]


def test_sync_service_updates_profiles_and_appends_incremental_nav(session: Session) -> None:
    portfolio, alpha_fund, beta_fund, gamma_fund = _seed_portfolio(session)
    session.add(
        NavSnapshot(
            fund_id=alpha_fund.id,
            nav_date=date(2026, 4, 2),
            unit_nav_amount=Decimal("1.01000000"),
            accumulated_nav_amount=Decimal("1.21000000"),
            daily_return_ratio=Decimal("0.010000"),
            source_name="seed",
        )
    )
    session.commit()

    adapter = FakeFundDataAdapter()
    adapter.profile_responses["000001"] = FundProfile(
        fund_code="000001",
        fund_name="Alpha Growth",
        full_name=None,
        fund_type="混合型",
        inception_date=None,
        latest_scale=None,
        company_name="Alpha AMC",
        manager_name="Manager A",
        custodian_bank=None,
        rating_source=None,
        rating=None,
        investment_strategy=None,
        investment_target=None,
        benchmark="CSI 300",
    )
    adapter.nav_responses["000001"] = FundNavHistory(
        fund_code="000001",
        requested_start_date=date(2026, 4, 2),
        requested_end_date=date(2026, 4, 3),
        points=(
            FundNavPoint(
                nav_date=date(2026, 4, 2),
                unit_nav=Decimal("1.01000000"),
                accumulated_nav=Decimal("1.21000000"),
                daily_return_pct=Decimal("1.00"),
            ),
            FundNavPoint(
                nav_date=date(2026, 4, 3),
                unit_nav=Decimal("1.02000000"),
                accumulated_nav=Decimal("1.22000000"),
                daily_return_pct=Decimal("0.99"),
            ),
        ),
        series_type="open_fund",
        source_endpoint="fund_open_fund_info_em",
    )
    adapter.nav_responses["000002"] = FundNavHistory(
        fund_code="000002",
        requested_start_date=None,
        requested_end_date=date(2026, 4, 3),
        points=(
            FundNavPoint(
                nav_date=date(2026, 4, 3),
                unit_nav=None,
                per_million_yield=Decimal("0.5500"),
                annualized_7d_yield_pct=Decimal("1.7800"),
            ),
        ),
        series_type="money_market",
        source_endpoint="fund_money_fund_info_em",
        warnings=("Money-market history does not expose unit or accumulated NAV values.",),
    )

    result = FundDataSyncService(session, adapter=adapter).sync_portfolio_funds(
        portfolio.id,
        as_of_date=date(2026, 4, 3),
    )
    session.commit()

    assert result.processed_fund_count == 2
    assert result.profile_updated_count == 1
    assert result.nav_records_inserted == 1
    assert result.failed_fund_codes == ()

    alpha_detail, beta_detail = result.funds
    assert alpha_detail.fund_code == "000001"
    assert alpha_detail.profile_updated is True
    assert alpha_detail.nav_records_inserted == 1
    assert alpha_detail.errors == ()
    assert beta_detail.fund_code == "000002"
    assert beta_detail.profile_updated is False
    assert beta_detail.nav_records_inserted == 0
    assert any("does not expose unit NAV" in warning for warning in beta_detail.warnings)

    updated_alpha = session.execute(
        select(FundMaster).where(FundMaster.id == alpha_fund.id)
    ).scalar_one()
    assert updated_alpha.fund_name == "Alpha Growth"
    assert updated_alpha.fund_type == "混合型"
    assert updated_alpha.company_name == "Alpha AMC"
    assert updated_alpha.manager_name == "Manager A"
    assert updated_alpha.benchmark_name == "CSI 300"
    assert updated_alpha.source_name == "akshare"
    assert updated_alpha.source_reference == "fund_profile"

    alpha_nav_rows = list(
        session.execute(
            select(NavSnapshot)
            .where(NavSnapshot.fund_id == alpha_fund.id)
            .order_by(NavSnapshot.nav_date.asc(), NavSnapshot.id.asc())
        ).scalars()
    )
    assert len(alpha_nav_rows) == 2
    assert alpha_nav_rows[-1].nav_date == date(2026, 4, 3)
    assert alpha_nav_rows[-1].daily_return_ratio == Decimal("0.009900")
    assert alpha_nav_rows[-1].source_name == "akshare"
    assert alpha_nav_rows[-1].source_reference == "fund_open_fund_info_em"
    assert session.scalar(
        select(func.count()).select_from(NavSnapshot).where(NavSnapshot.fund_id == beta_fund.id)
    ) == 0
    assert adapter.nav_calls == [
        ("000001", date(2026, 4, 2), date(2026, 4, 3)),
        ("000002", None, date(2026, 4, 3)),
    ]
    assert all(call[0] != gamma_fund.fund_code for call in adapter.nav_calls)


def test_sync_service_records_partial_failures_without_raising(session: Session) -> None:
    portfolio, alpha_fund, _, _ = _seed_portfolio(session)
    session.commit()

    adapter = FakeFundDataAdapter()
    adapter.profile_errors["000001"] = "profile unavailable"
    adapter.nav_errors["000001"] = "nav unavailable"
    adapter.nav_responses["000002"] = FundNavHistory(
        fund_code="000002",
        requested_start_date=None,
        requested_end_date=date(2026, 4, 3),
        points=(),
        series_type="open_fund",
        source_endpoint="fund_open_fund_info_em",
    )

    result = FundDataSyncService(session, adapter=adapter).sync_portfolio_funds(
        portfolio.id,
        as_of_date=date(2026, 4, 3),
    )

    assert result.processed_fund_count == 2
    assert result.failed_fund_codes == ("000001",)
    alpha_detail = next(detail for detail in result.funds if detail.fund_code == alpha_fund.fund_code)
    assert alpha_detail.profile_updated is False
    assert alpha_detail.nav_records_inserted == 0
    assert alpha_detail.errors == (
        "profile sync failed: profile unavailable",
        "NAV sync failed: nav unavailable",
    )


def _seed_portfolio(session: Session) -> tuple[Portfolio, FundMaster, FundMaster, FundMaster]:
    portfolio = Portfolio(
        portfolio_code="main",
        portfolio_name="Main",
    )
    alpha_fund = FundMaster(
        fund_code="000001",
        fund_name="Alpha",
        source_name="holdings_import",
    )
    beta_fund = FundMaster(
        fund_code="000002",
        fund_name="Beta Cash",
        source_name="holdings_import",
    )
    gamma_fund = FundMaster(
        fund_code="000003",
        fund_name="Gamma Old",
        source_name="holdings_import",
    )
    session.add_all([portfolio, alpha_fund, beta_fund, gamma_fund])
    session.flush()

    session.add_all(
        [
            PositionLot(
                portfolio_id=portfolio.id,
                fund_id=alpha_fund.id,
                run_id="rebuild-20260401",
                lot_key="alpha-core",
                opened_on=date(2026, 4, 1),
                as_of_date=date(2026, 4, 1),
                remaining_units=Decimal("10.000000"),
                average_cost_per_unit=Decimal("1.00000000"),
                total_cost_amount=Decimal("10.0000"),
            ),
            PositionLot(
                portfolio_id=portfolio.id,
                fund_id=beta_fund.id,
                run_id="rebuild-20260401",
                lot_key="beta-core",
                opened_on=date(2026, 4, 1),
                as_of_date=date(2026, 4, 1),
                remaining_units=Decimal("5.000000"),
                average_cost_per_unit=Decimal("2.00000000"),
                total_cost_amount=Decimal("10.0000"),
            ),
            PositionLot(
                portfolio_id=portfolio.id,
                fund_id=gamma_fund.id,
                run_id="rebuild-20260401",
                lot_key="gamma-core",
                opened_on=date(2026, 4, 1),
                as_of_date=date(2026, 4, 1),
                remaining_units=Decimal("0.000000"),
                average_cost_per_unit=Decimal("3.00000000"),
                total_cost_amount=Decimal("0.0000"),
            ),
        ]
    )
    return portfolio, alpha_fund, beta_fund, gamma_fund


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    database_path = tmp_path / "fund-sync.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    with session_factory() as db_session:
        yield db_session

    engine.dispose()
