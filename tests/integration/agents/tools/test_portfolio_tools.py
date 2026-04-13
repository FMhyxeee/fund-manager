"""Integration tests for agent-facing portfolio tools."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from fund_manager.agents.tools import PortfolioSummaryDTO, PortfolioTools
from fund_manager.storage.models import (
    Base,
    DecisionRun,
    DecisionTransactionLink,
    FundMaster,
    NavSnapshot,
    Portfolio,
    PositionLot,
    ReviewReport,
    TransactionRecord,
    TransactionType,
)
from fund_manager.storage.repo import PortfolioPolicyRepository, PortfolioPolicyTargetCreate


def test_portfolio_tools_list_and_read_snapshot_by_name(session: Session) -> None:
    portfolio = seed_portfolio_with_valuation_history(session)
    tools = PortfolioTools(session)

    portfolios = tools.list_portfolios()
    assert portfolios == (
        PortfolioSummaryDTO(
            portfolio_id=portfolio.id,
            portfolio_code="main",
            portfolio_name="Main",
            base_currency_code="CNY",
            is_default=False,
        ),
    )

    snapshot_payload = tools.get_portfolio_snapshot(
        portfolio_name="Main",
        as_of_date=date(2026, 3, 15),
    )
    assert snapshot_payload["portfolio"]["portfolio_id"] == portfolio.id
    assert snapshot_payload["snapshot"]["portfolio_name"] == "Main"
    assert snapshot_payload["snapshot"]["total_market_value_amount"] == "33.5000"
    assert snapshot_payload["snapshot"]["missing_nav_fund_codes"] == []

    position_payload = tools.get_position_breakdown(
        portfolio_name="Main",
        as_of_date=date(2026, 3, 15),
    )
    assert position_payload["as_of_date"] == "2026-03-15"
    assert len(position_payload["positions"]) == 2
    assert position_payload["positions"][0]["fund_code"] == "000001"
    assert position_payload["positions"][1]["weight_ratio"] == "0.462687"


def test_portfolio_tools_run_weekly_review_returns_json_safe_result(session: Session) -> None:
    portfolio = seed_portfolio_with_valuation_history(session)
    tools = PortfolioTools(session)

    result = tools.run_weekly_review(
        portfolio_id=portfolio.id,
        period_start=date(2026, 3, 8),
        period_end=date(2026, 3, 15),
    )

    assert result["workflow_name"] == "weekly_review"
    assert result["portfolio_id"] == portfolio.id
    assert result["period_start"] == "2026-03-08"
    assert result["facts"]["period_return_ratio"] == "0.139456"
    assert result["review_output"]["summary"]
    assert result["report_markdown"].startswith("# Weekly Review")

    persisted_report = session.execute(select(ReviewReport)).scalar_one()
    assert persisted_report.id == result["report_record_id"]
    assert persisted_report.run_id == result["run_id"]


def test_portfolio_tools_metrics_policy_and_daily_decision(session: Session) -> None:
    portfolio = seed_portfolio_with_valuation_history(session)
    alpha_fund = session.execute(
        select(FundMaster).where(FundMaster.fund_code == "000001")
    ).scalar_one()
    beta_fund = session.execute(
        select(FundMaster).where(FundMaster.fund_code == "000002")
    ).scalar_one()
    PortfolioPolicyRepository(session).append(
        portfolio_id=portfolio.id,
        policy_name="baseline-current-allocation",
        effective_from=date(2026, 3, 15),
        rebalance_threshold_ratio=Decimal("0.03"),
        max_single_position_weight_ratio=Decimal("0.60"),
        targets=(
            PortfolioPolicyTargetCreate(
                fund_id=alpha_fund.id,
                target_weight_ratio=Decimal("0.537313"),
            ),
            PortfolioPolicyTargetCreate(
                fund_id=beta_fund.id,
                target_weight_ratio=Decimal("0.462687"),
            ),
        ),
    )
    session.commit()

    tools = PortfolioTools(session)
    metrics = tools.get_portfolio_metrics(
        portfolio_id=portfolio.id,
        as_of_date=date(2026, 3, 15),
    )
    valuation_history = tools.get_portfolio_valuation_history(
        portfolio_name="Main",
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 15),
    )
    active_policy = tools.get_active_policy(
        portfolio_id=portfolio.id,
        as_of_date=date(2026, 3, 15),
    )
    decision_result = tools.run_daily_decision(
        portfolio_id=portfolio.id,
        decision_date=date(2026, 3, 15),
    )
    decision_payload = tools.get_decision_run(
        decision_run_id=decision_result["decision_run_id"],
    )

    assert metrics["metrics"]["position_count"] == 2
    assert metrics["metrics"]["top_positions"][0]["fund_code"] == "000001"
    assert valuation_history["valuation_history"][0]["as_of_date"] == "2026-03-01"
    assert active_policy["policy"]["policy_name"] == "baseline-current-allocation"
    assert decision_result["workflow_name"] == "daily_decision"
    assert decision_result["final_decision"] == "monitor"
    assert decision_payload["decision_run"]["final_decision"] == "monitor"

    persisted_decision = session.execute(select(DecisionRun)).scalar_one()
    assert persisted_decision.id == decision_result["decision_run_id"]


def test_portfolio_tools_record_decision_feedback(session: Session) -> None:
    portfolio = seed_portfolio_with_valuation_history(session)
    alpha_fund = session.execute(
        select(FundMaster).where(FundMaster.fund_code == "000001")
    ).scalar_one()
    decision_run = DecisionRun(
        portfolio_id=portfolio.id,
        decision_date=date(2026, 3, 15),
        summary="Add Alpha Fund.",
        final_decision="rebalance_required",
        trigger_source="tool_test",
        actions_json=[
            {
                "action_type": "add",
                "fund_id": alpha_fund.id,
                "fund_code": alpha_fund.fund_code,
                "fund_name": alpha_fund.fund_name,
            }
        ],
        created_by_agent="DecisionService",
    )
    transaction = TransactionRecord(
        portfolio_id=portfolio.id,
        fund_id=alpha_fund.id,
        trade_date=date(2026, 3, 15),
        trade_type=TransactionType.BUY,
        units=Decimal("2.000000"),
        gross_amount=Decimal("3.0000"),
        source_name="manual",
    )
    session.add_all([decision_run, transaction])
    session.commit()

    tools = PortfolioTools(session)
    feedback_result = tools.record_decision_feedback(
        decision_run_id=decision_run.id,
        action_index=0,
        feedback_status="executed",
        feedback_date=date(2026, 3, 15),
        created_by="tool-test",
    )

    assert feedback_result["decision_run_id"] == decision_run.id
    assert feedback_result["feedback_status"] == "executed"
    assert feedback_result["linked_transaction_ids"] == [transaction.id]

    persisted_link = session.execute(select(DecisionTransactionLink)).scalar_one()
    assert persisted_link.transaction_id == transaction.id


def test_portfolio_tools_watchlist_reads(session: Session) -> None:
    portfolio = seed_watchlist_portfolio(session)
    tools = PortfolioTools(session)

    candidates = tools.get_watchlist_candidates(
        portfolio_id=portfolio.id,
        as_of_date=date(2026, 4, 13),
    )
    fit = tools.get_watchlist_candidate_fit(
        portfolio_id=portfolio.id,
        fund_code="006265",
        as_of_date=date(2026, 4, 13),
    )
    leaders = tools.get_watchlist_style_leaders(
        as_of_date=date(2026, 4, 13),
        categories=("healthcare",),
    )

    all_codes = [
        item["fund_code"]
        for item in candidates["core_watchlist"] + candidates["extended_watchlist"]
    ]
    assert "010685" in all_codes
    assert "006265" not in all_codes
    assert fit["fit_label"] == "high_beta_duplicate"
    assert leaders["leaders"]["healthcare"][0]["fund_code"] in {"010685", "003095"}


def seed_portfolio_with_valuation_history(session: Session) -> Portfolio:
    portfolio = Portfolio(
        portfolio_code="main",
        portfolio_name="Main",
    )
    alpha_fund = FundMaster(
        fund_code="000001",
        fund_name="Alpha Fund",
        source_name="test",
    )
    beta_fund = FundMaster(
        fund_code="000002",
        fund_name="Beta Fund",
        source_name="test",
    )
    session.add_all([portfolio, alpha_fund, beta_fund])
    session.flush()

    session.add_all(
        [
            PositionLot(
                portfolio_id=portfolio.id,
                fund_id=alpha_fund.id,
                run_id="rebuild-20260301",
                lot_key="alpha-core",
                opened_on=date(2026, 3, 1),
                as_of_date=date(2026, 3, 1),
                remaining_units=Decimal("10.000000"),
                average_cost_per_unit=Decimal("1.00000000"),
                total_cost_amount=Decimal("10.0000"),
            ),
            PositionLot(
                portfolio_id=portfolio.id,
                fund_id=alpha_fund.id,
                run_id="rebuild-20260310",
                lot_key="alpha-core",
                opened_on=date(2026, 3, 1),
                as_of_date=date(2026, 3, 10),
                remaining_units=Decimal("12.000000"),
                average_cost_per_unit=Decimal("1.00000000"),
                total_cost_amount=Decimal("12.0000"),
            ),
            PositionLot(
                portfolio_id=portfolio.id,
                fund_id=beta_fund.id,
                run_id="rebuild-20260301",
                lot_key="beta-core",
                opened_on=date(2026, 3, 1),
                as_of_date=date(2026, 3, 1),
                remaining_units=Decimal("5.000000"),
                average_cost_per_unit=Decimal("3.00000000"),
                total_cost_amount=Decimal("15.0000"),
            ),
            NavSnapshot(
                fund_id=alpha_fund.id,
                nav_date=date(2026, 3, 1),
                unit_nav_amount=Decimal("1.00000000"),
                source_name="test",
            ),
            NavSnapshot(
                fund_id=alpha_fund.id,
                nav_date=date(2026, 3, 10),
                unit_nav_amount=Decimal("1.20000000"),
                source_name="test",
            ),
            NavSnapshot(
                fund_id=alpha_fund.id,
                nav_date=date(2026, 3, 14),
                unit_nav_amount=Decimal("1.50000000"),
                source_name="test",
            ),
            NavSnapshot(
                fund_id=beta_fund.id,
                nav_date=date(2026, 3, 1),
                unit_nav_amount=Decimal("3.00000000"),
                source_name="test",
            ),
            NavSnapshot(
                fund_id=beta_fund.id,
                nav_date=date(2026, 3, 12),
                unit_nav_amount=Decimal("3.20000000"),
                source_name="test",
            ),
            NavSnapshot(
                fund_id=beta_fund.id,
                nav_date=date(2026, 3, 14),
                unit_nav_amount=Decimal("3.10000000"),
                source_name="test",
            ),
        ]
    )
    session.commit()
    return portfolio


def seed_watchlist_portfolio(session: Session) -> Portfolio:
    portfolio = Portfolio(
        portfolio_code="main",
        portfolio_name="Main",
    )
    funds = [
        FundMaster(fund_code="011506", fund_name="建信高端装备股票A", source_name="test"),
        FundMaster(fund_code="010685", fund_name="工银前沿医疗股票C", source_name="test"),
        FundMaster(fund_code="003095", fund_name="中欧医疗健康混合A", source_name="test"),
        FundMaster(fund_code="006087", fund_name="华泰柏瑞沪深300ETF联接A", source_name="test"),
        FundMaster(fund_code="006265", fund_name="红土创新新科技股票A", source_name="test"),
    ]
    session.add(portfolio)
    session.add_all(funds)
    session.flush()

    held = next(fund for fund in funds if fund.fund_code == "011506")
    session.add(
        PositionLot(
            portfolio_id=portfolio.id,
            fund_id=held.id,
            run_id="watchlist-seed",
            lot_key="lot-011506",
            opened_on=date(2026, 4, 1),
            as_of_date=date(2026, 4, 13),
            remaining_units=Decimal("100.000000"),
            average_cost_per_unit=Decimal("1.00000000"),
            total_cost_amount=Decimal("100.0000"),
        )
    )
    for fund in funds:
        session.add(
            NavSnapshot(
                fund_id=fund.id,
                nav_date=date(2026, 4, 10),
                unit_nav_amount=Decimal("1.11110000"),
                source_name="test",
            )
        )
    session.commit()
    return portfolio


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    database_path = tmp_path / "portfolio-tools.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    with session_factory() as db_session:
        yield db_session

    engine.dispose()
