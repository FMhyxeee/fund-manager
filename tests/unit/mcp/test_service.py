"""Tests for the MCP-oriented fund-manager service layer."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from fund_manager.mcp.service import FundManagerMCPService, ModelAllocation
from fund_manager.storage.models import (
    Base,
    DecisionFeedback,
    DecisionFeedbackStatus,
    DecisionRun,
    DecisionTransactionLink,
    FundMaster,
    NavSnapshot,
    Portfolio,
    PositionLot,
    ReportPeriodType,
    ReviewReport,
    TransactionRecord,
    TransactionType,
)
from fund_manager.storage.repo import PortfolioPolicyRepository, PortfolioPolicyTargetCreate


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    database_path = tmp_path / "mcp-service.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    with session_factory() as db_session:
        yield db_session

    engine.dispose()


def test_mcp_service_lists_snapshot_and_nav_history(session: Session) -> None:
    seed_portfolio_with_history(session)
    service = FundManagerMCPService(session)

    portfolios = service.list_portfolios()
    snapshot = service.get_portfolio_snapshot(portfolio_name="Main", as_of_date=date(2026, 3, 15))
    nav_history = service.get_fund_nav_history(
        fund_code="000001",
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 14),
    )
    valuation_history = service.get_portfolio_valuation_history(
        portfolio_name="Main",
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 15),
    )

    assert portfolios["portfolios"][0]["portfolio_name"] == "Main"
    assert snapshot["snapshot"]["total_market_value_amount"] == "33.5000"
    assert nav_history["fund"]["fund_name"] == "Alpha Fund"
    assert len(nav_history["points"]) == 3
    assert valuation_history["valuation_history"][0]["as_of_date"] == "2026-03-01"


def test_mcp_service_compact_metrics_and_simulation(session: Session) -> None:
    seed_portfolio_with_history(session)
    service = FundManagerMCPService(session)

    metrics = service.get_portfolio_metrics(
        portfolio_name="Main",
        as_of_date=date(2026, 3, 15),
    )
    simulation = service.simulate_model_portfolio(
        allocations=(
            ModelAllocation(fund_code="000001", weight=Decimal("0.6")),
            ModelAllocation(fund_code="000002", weight=Decimal("0.4")),
        ),
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 14),
        rebalance="monthly",
    )

    assert metrics["metrics"]["position_count"] == 2
    assert metrics["metrics"]["top_positions"][0]["fund_code"] == "000001"
    assert simulation["allocations"][0]["weight"] == "0.600000"
    assert simulation["valuation_history"][0]["market_value_amount"] == "1.0000"
    assert simulation["metrics"]["period_return_ratio"] is not None


def test_mcp_service_policy_decision_feedback_and_report_reads(session: Session) -> None:
    portfolio, alpha_fund, beta_fund = seed_portfolio_with_history(session)
    policy = PortfolioPolicyRepository(session).append(
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
    session.flush()

    decision_run = DecisionRun(
        portfolio_id=portfolio.id,
        policy_id=policy.id,
        run_id="daily-decision-20260315-abc12345",
        workflow_name="daily_decision",
        decision_date=date(2026, 3, 15),
        trigger_source="mcp_test",
        summary="Current holdings remain within policy bands.",
        final_decision="monitor",
        confidence_score=Decimal("0.8500"),
        actions_json=[],
        decision_summary_json={"final_decision": "monitor", "policy_name": policy.policy_name},
        created_by_agent="DecisionService",
    )
    transaction = TransactionRecord(
        portfolio_id=portfolio.id,
        fund_id=alpha_fund.id,
        trade_date=date(2026, 3, 15),
        trade_type=TransactionType.BUY,
        units=Decimal("1.000000"),
        gross_amount=Decimal("1.5000"),
        source_name="manual",
    )
    session.add_all([decision_run, transaction])
    session.flush()

    feedback = DecisionFeedback(
        decision_run_id=decision_run.id,
        portfolio_id=portfolio.id,
        fund_id=alpha_fund.id,
        action_index=0,
        action_type="add",
        feedback_status=DecisionFeedbackStatus.EXECUTED,
        feedback_date=date(2026, 3, 15),
        note="executed manually",
        created_by="tester",
    )
    session.add(feedback)
    session.flush()
    session.add(
        DecisionTransactionLink(
            feedback_id=feedback.id,
            transaction_id=transaction.id,
            match_source="reconcile_existing",
            match_reason="Matched buy transaction on feedback date.",
        )
    )
    review_report = ReviewReport(
        portfolio_id=portfolio.id,
        run_id="weekly-review-20260315-xyz98765",
        workflow_name="weekly_review",
        period_type=ReportPeriodType.WEEKLY,
        period_start=date(2026, 3, 8),
        period_end=date(2026, 3, 15),
        report_markdown="# Weekly Review\n\nEverything is stable.",
        summary_json={"summary": "Everything is stable."},
        created_by_agent="ManualReviewAgent",
    )
    session.add(review_report)
    session.commit()

    service = FundManagerMCPService(session)

    active_policy = service.get_active_policy(
        portfolio_id=portfolio.id,
        as_of_date=date(2026, 3, 15),
    )
    decision_runs = service.list_decision_runs(
        portfolio_name="Main",
        decision_date=date(2026, 3, 15),
        limit=5,
    )
    decision_run_payload = service.get_decision_run(decision_run_id=decision_run.id)
    feedback_payload = service.list_decision_feedback(decision_run_id=decision_run.id)
    review_report_payload = service.get_review_report(report_id=review_report.id)

    assert active_policy["policy"]["policy_name"] == "baseline-current-allocation"
    assert len(active_policy["policy"]["targets"]) == 2
    assert decision_runs["decision_runs"][0]["id"] == decision_run.id
    assert decision_run_payload["decision_run"]["final_decision"] == "monitor"
    assert feedback_payload["feedback_entries"][0]["linked_transaction_ids"] == [transaction.id]
    assert review_report_payload["review_report"]["workflow_name"] == "weekly_review"
    assert review_report_payload["review_report"]["portfolio_code"] == "main"


def test_mcp_service_watchlist_reads(session: Session) -> None:
    portfolio = seed_watchlist_portfolio(session)
    service = FundManagerMCPService(session)

    candidates = service.get_watchlist_candidates(
        portfolio_id=portfolio.id,
        as_of_date=date(2026, 4, 13),
    )
    fit = service.get_watchlist_candidate_fit(
        portfolio_id=portfolio.id,
        fund_code="006265",
        as_of_date=date(2026, 4, 13),
    )
    leaders = service.get_watchlist_style_leaders(
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


def seed_portfolio_with_history(session: Session) -> tuple[Portfolio, FundMaster, FundMaster]:
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
                daily_return_ratio=Decimal("0"),
                source_name="test",
            ),
            NavSnapshot(
                fund_id=alpha_fund.id,
                nav_date=date(2026, 3, 10),
                unit_nav_amount=Decimal("1.20000000"),
                daily_return_ratio=Decimal("0.200000"),
                source_name="test",
            ),
            NavSnapshot(
                fund_id=alpha_fund.id,
                nav_date=date(2026, 3, 14),
                unit_nav_amount=Decimal("1.50000000"),
                daily_return_ratio=Decimal("0.250000"),
                source_name="test",
            ),
            NavSnapshot(
                fund_id=beta_fund.id,
                nav_date=date(2026, 3, 1),
                unit_nav_amount=Decimal("3.00000000"),
                daily_return_ratio=Decimal("0"),
                source_name="test",
            ),
            NavSnapshot(
                fund_id=beta_fund.id,
                nav_date=date(2026, 3, 12),
                unit_nav_amount=Decimal("3.20000000"),
                daily_return_ratio=Decimal("0.066667"),
                source_name="test",
            ),
            NavSnapshot(
                fund_id=beta_fund.id,
                nav_date=date(2026, 3, 14),
                unit_nav_amount=Decimal("3.10000000"),
                daily_return_ratio=Decimal("-0.031250"),
                source_name="test",
            ),
        ]
    )
    session.commit()
    return portfolio, alpha_fund, beta_fund


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
