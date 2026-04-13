from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from fund_manager.core.watchlist.service import FundWatchlistService
from fund_manager.storage.models import Base, FundMaster, NavSnapshot, Portfolio, PositionLot


def make_session() -> Session:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    return factory()


def seed_watchlist_fixture(session: Session) -> Portfolio:
    portfolio = Portfolio(portfolio_code="main", portfolio_name="Main Portfolio")
    session.add(portfolio)
    session.flush()

    funds = [
        FundMaster(fund_code="202003", fund_name="南方绩优成长", fund_type="混合型"),
        FundMaster(fund_code="011506", fund_name="建信高端装备股票A", fund_type="股票型"),
        FundMaster(fund_code="010685", fund_name="工银瑞信前沿医疗股票C", fund_type="股票型"),
        FundMaster(fund_code="003095", fund_name="中欧医疗健康混合A", fund_type="混合型"),
        FundMaster(fund_code="006087", fund_name="华泰柏瑞沪深300ETF联接A", fund_type="指数型"),
        FundMaster(fund_code="003578", fund_name="中金中证500指数增强C", fund_type="指数型"),
        FundMaster(fund_code="013161", fund_name="红利低波ETF联接", fund_type="指数型"),
        FundMaster(fund_code="006265", fund_name="红土创新新科技股票A", fund_type="股票型"),
    ]
    session.add_all(funds)
    session.flush()

    held_ids = {fund.fund_code: fund.id for fund in funds}
    session.add_all(
        [
            PositionLot(
                portfolio_id=portfolio.id,
                fund_id=held_ids["202003"],
                run_id="seed-run",
                lot_key="lot-202003",
                opened_on=date(2026, 4, 1),
                as_of_date=date(2026, 4, 13),
                remaining_units=Decimal("100.000000"),
                average_cost_per_unit=Decimal("1.00000000"),
                total_cost_amount=Decimal("100.0000"),
            ),
            PositionLot(
                portfolio_id=portfolio.id,
                fund_id=held_ids["011506"],
                run_id="seed-run",
                lot_key="lot-011506",
                opened_on=date(2026, 4, 1),
                as_of_date=date(2026, 4, 13),
                remaining_units=Decimal("100.000000"),
                average_cost_per_unit=Decimal("1.00000000"),
                total_cost_amount=Decimal("100.0000"),
            ),
        ]
    )

    for fund in funds:
        session.add(
            NavSnapshot(
                fund_id=fund.id,
                nav_date=date(2026, 4, 10),
                unit_nav_amount=Decimal("1.23450000"),
                source_name="test",
            )
        )
    session.commit()
    return portfolio


def test_build_watchlist_candidates_filters_high_overlap() -> None:
    session = make_session()
    portfolio = seed_watchlist_fixture(session)
    service = FundWatchlistService(session)

    result = service.build_watchlist_candidates(
        as_of_date=date(2026, 4, 13),
        portfolio_id=portfolio.id,
        risk_profile="balanced",
    )

    codes = [item.fund_code for item in result.core_watchlist + result.extended_watchlist]
    assert "010685" in codes
    assert "006087" in codes
    assert "202003" not in codes


def test_candidate_fit_marks_duplicate_high_beta() -> None:
    session = make_session()
    portfolio = seed_watchlist_fixture(session)
    service = FundWatchlistService(session)

    fit = service.analyze_candidate_fit(
        as_of_date=date(2026, 4, 13),
        portfolio_id=portfolio.id,
        fund_code="006265",
    )

    assert fit.fit_label == "high_beta_duplicate"
    assert fit.overlap_level == "high"


def test_build_style_leaders_groups_by_category() -> None:
    session = make_session()
    seed_watchlist_fixture(session)
    service = FundWatchlistService(session)

    leaders = service.build_style_leaders(as_of_date=date(2026, 4, 13), max_per_category=1)

    assert "healthcare" in leaders
    assert leaders["healthcare"][0].fund_code in {"010685", "003095"}
