"""Unit tests for the action-oriented admin CLI."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from fund_manager.admin import cli as admin_cli
from fund_manager.storage.models import (
    Base,
    DecisionRun,
    FundMaster,
    NavSnapshot,
    Portfolio,
    PortfolioPolicy,
    PositionLot,
    TransactionRecord,
    TransactionType,
)
from fund_manager.storage.repo import PortfolioPolicyRepository, PortfolioPolicyTargetCreate


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture()
def session(engine) -> Session:
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    sess = factory()
    yield sess
    sess.close()


def install_test_session_factory(monkeypatch: pytest.MonkeyPatch, engine) -> None:
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    monkeypatch.setattr(admin_cli, "get_session_factory", lambda: factory)


def seed_portfolio_with_fund(
    session: Session,
    *,
    fund_code: str = "000001",
    fund_name: str = "Alpha Fund",
) -> tuple[Portfolio, FundMaster]:
    portfolio = Portfolio(portfolio_code="main", portfolio_name="Main Portfolio")
    fund = FundMaster(fund_code=fund_code, fund_name=fund_name, source_name="test")
    session.add_all([portfolio, fund])
    session.flush()
    session.add(
        PositionLot(
            portfolio_id=portfolio.id,
            fund_id=fund.id,
            run_id="seed-run",
            lot_key=f"lot-{fund_code}",
            opened_on=date(2026, 3, 1),
            as_of_date=date(2026, 3, 15),
            remaining_units=Decimal("100.000000"),
            average_cost_per_unit=Decimal("1.00000000"),
            total_cost_amount=Decimal("100.0000"),
        )
    )
    session.commit()
    return portfolio, fund


def test_policy_show_outputs_active_policy_json(
    session: Session,
    engine,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_test_session_factory(monkeypatch, engine)
    portfolio, alpha_fund = seed_portfolio_with_fund(session)
    beta_fund = FundMaster(fund_code="000002", fund_name="Beta Fund", source_name="test")
    session.add(beta_fund)
    session.flush()
    PortfolioPolicyRepository(session).append(
        portfolio_id=portfolio.id,
        policy_name="baseline",
        effective_from=date(2026, 3, 15),
        rebalance_threshold_ratio=Decimal("0.03"),
        max_single_position_weight_ratio=Decimal("0.35"),
        created_by="test",
        targets=(
            PortfolioPolicyTargetCreate(
                fund_id=alpha_fund.id,
                target_weight_ratio=Decimal("0.60"),
            ),
            PortfolioPolicyTargetCreate(
                fund_id=beta_fund.id,
                target_weight_ratio=Decimal("0.40"),
            ),
        ),
    )
    session.commit()

    admin_cli.main(
        [
            "policy",
            "show",
            "--portfolio-id",
            str(portfolio.id),
            "--as-of-date",
            "2026-03-15",
        ]
    )

    data = json.loads(capsys.readouterr().out)
    assert data["policy_name"] == "baseline"
    assert data["portfolio_id"] == portfolio.id
    assert [target["fund_code"] for target in data["targets"]] == ["000001", "000002"]


def test_policy_create_appends_policy(
    session: Session,
    engine,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_test_session_factory(monkeypatch, engine)
    portfolio, _ = seed_portfolio_with_fund(session)
    session.add(FundMaster(fund_code="000002", fund_name="Beta Fund", source_name="test"))
    session.commit()

    admin_cli.main(
        [
            "policy",
            "create",
            "--portfolio-id",
            str(portfolio.id),
            "--policy-name",
            "rebalance-policy",
            "--effective-from",
            "2026-03-16",
            "--rebalance-threshold-ratio",
            "0.05",
            "--max-single-position-weight-ratio",
            "0.40",
            "--created-by",
            "cli-test",
            "--target",
            "fund_code=000001,target_weight_ratio=0.55,min_weight_ratio=0.50",
            "--target",
            "fund_code=000002,target_weight_ratio=0.45,max_weight_ratio=0.50,add_allowed=true",
        ]
    )

    data = json.loads(capsys.readouterr().out)
    assert data["policy_name"] == "rebalance-policy"
    assert data["created_by"] == "cli-test"
    assert len(data["targets"]) == 2

    policy_count = session.query(PortfolioPolicy).count()
    assert policy_count == 1


def test_decision_list_outputs_recent_runs(
    session: Session,
    engine,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_test_session_factory(monkeypatch, engine)
    portfolio = Portfolio(portfolio_code="main", portfolio_name="Main Portfolio")
    older_run = DecisionRun(
        portfolio=portfolio,
        decision_date=date(2026, 3, 14),
        summary="Monitor.",
        final_decision="monitor",
        trigger_source="cli_test",
        actions_json=[],
        created_by_agent="DecisionService",
    )
    newer_run = DecisionRun(
        portfolio=portfolio,
        decision_date=date(2026, 3, 15),
        summary="Rebalance.",
        final_decision="rebalance_required",
        trigger_source="cli_test",
        actions_json=[{"action_type": "add", "fund_code": "000001"}],
        created_by_agent="DecisionService",
    )
    session.add_all([portfolio, older_run, newer_run])
    session.commit()

    admin_cli.main(
        [
            "decision",
            "list",
            "--portfolio-id",
            str(portfolio.id),
            "--limit",
            "1",
        ]
    )

    data = json.loads(capsys.readouterr().out)
    assert len(data) == 1
    assert data[0]["id"] == newer_run.id
    assert data[0]["action_count"] == 1


def test_decision_show_outputs_detail_payload(
    session: Session,
    engine,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_test_session_factory(monkeypatch, engine)
    portfolio = Portfolio(portfolio_code="main", portfolio_name="Main Portfolio")
    session.add(portfolio)
    session.flush()
    decision_run = DecisionRun(
        portfolio_id=portfolio.id,
        decision_date=date(2026, 3, 15),
        summary="Add Alpha.",
        final_decision="rebalance_required",
        trigger_source="cli_test",
        actions_json=[{"action_type": "add", "fund_code": "000001"}],
        decision_summary_json={"policy_name": "baseline"},
        created_by_agent="DecisionService",
    )
    session.add(decision_run)
    session.commit()

    admin_cli.main(["decision", "show", "--decision-run-id", str(decision_run.id)])

    data = json.loads(capsys.readouterr().out)
    assert data["id"] == decision_run.id
    assert data["portfolio_code"] == "main"
    assert data["actions_json"][0]["action_type"] == "add"


def test_decision_run_executes_workflow(
    session: Session,
    engine,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_test_session_factory(monkeypatch, engine)
    portfolio, fund = seed_portfolio_with_fund(session)
    session.add(
        NavSnapshot(
            fund_id=fund.id,
            nav_date=date(2026, 3, 15),
            unit_nav_amount=Decimal("1.25000000"),
            source_name="test",
        )
    )
    session.commit()

    admin_cli.main(
        [
            "decision",
            "run",
            "--portfolio-id",
            str(portfolio.id),
            "--decision-date",
            "2026-03-15",
            "--trigger-source",
            "cli_test",
        ]
    )

    data = json.loads(capsys.readouterr().out)
    assert data["workflow_name"] == "daily_decision"
    assert data["final_decision"] == "no_active_policy"
    assert data["decision"]["actions"][0]["action_type"] == "set_policy"


def test_decision_feedback_records_manual_feedback(
    session: Session,
    engine,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_test_session_factory(monkeypatch, engine)
    portfolio, fund = seed_portfolio_with_fund(session)
    decision_run = DecisionRun(
        portfolio_id=portfolio.id,
        decision_date=date(2026, 3, 15),
        summary="Add Alpha.",
        final_decision="rebalance_required",
        trigger_source="cli_test",
        actions_json=[
            {
                "action_type": "add",
                "fund_id": fund.id,
                "fund_code": fund.fund_code,
                "fund_name": fund.fund_name,
            }
        ],
        created_by_agent="DecisionService",
    )
    transaction = TransactionRecord(
        portfolio_id=portfolio.id,
        fund_id=fund.id,
        trade_date=date(2026, 3, 15),
        trade_type=TransactionType.BUY,
        units=Decimal("10.000000"),
        gross_amount=Decimal("12.0000"),
        source_name="manual",
    )
    session.add_all([decision_run, transaction])
    session.commit()

    admin_cli.main(
        [
            "decision",
            "feedback",
            "--decision-run-id",
            str(decision_run.id),
            "--action-index",
            "0",
            "--feedback-status",
            "executed",
            "--feedback-date",
            "2026-03-15",
            "--created-by",
            "cli-test",
        ]
    )

    data = json.loads(capsys.readouterr().out)
    assert data["decision_run_id"] == decision_run.id
    assert data["feedback_status"] == "executed"
    assert data["linked_transaction_ids"] == [transaction.id]


def test_workflow_run_daily_snapshot_outputs_payload(
    session: Session,
    engine,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_test_session_factory(monkeypatch, engine)
    portfolio, _ = seed_portfolio_with_fund(session)

    class FakeSyncResult:
        def to_dict(self) -> dict[str, object]:
            return {"portfolio_id": portfolio.id, "updated_funds": 1}

    class FakeSnapshot:
        def to_dict(self) -> dict[str, object]:
            return {"portfolio_id": portfolio.id, "total_market_value_amount": Decimal("123.4500")}

    monkeypatch.setattr(
        admin_cli.FundDataSyncService,
        "sync_portfolio_funds",
        lambda self, portfolio_id, as_of_date: FakeSyncResult(),
    )
    monkeypatch.setattr(
        admin_cli.PortfolioService,
        "save_portfolio_snapshot",
        lambda self, portfolio_id, as_of_date, run_id, workflow_name: FakeSnapshot(),
    )

    admin_cli.main(
        [
            "workflow",
            "run",
            "daily-snapshot",
            "--portfolio-id",
            str(portfolio.id),
            "--as-of-date",
            "2026-03-15",
        ]
    )

    data = json.loads(capsys.readouterr().out)
    assert data["workflow_name"] == "daily_snapshot"
    assert data["sync"]["updated_funds"] == 1
    assert data["snapshot"]["total_market_value_amount"] == "123.4500"


def test_workflow_run_weekly_review_outputs_payload(
    session: Session,
    engine,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_test_session_factory(monkeypatch, engine)
    portfolio, _ = seed_portfolio_with_fund(session)

    monkeypatch.setattr(
        admin_cli.WeeklyReviewWorkflow,
        "run",
        lambda self, portfolio_id, period_start, period_end, trigger_source: SimpleNamespace(
            run_id="weekly-review-1",
            workflow_name="weekly_review",
            portfolio_id=portfolio_id,
            period_start=period_start,
            period_end=period_end,
            report_record_id=42,
        ),
    )

    admin_cli.main(
        [
            "workflow",
            "run",
            "weekly-review",
            "--portfolio-id",
            str(portfolio.id),
            "--period-start",
            "2026-03-08",
            "--period-end",
            "2026-03-15",
        ]
    )

    data = json.loads(capsys.readouterr().out)
    assert data["workflow_name"] == "weekly_review"
    assert data["report_record_id"] == 42


def test_workflow_run_monthly_strategy_debate_outputs_payload(
    session: Session,
    engine,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install_test_session_factory(monkeypatch, engine)
    portfolio, _ = seed_portfolio_with_fund(session)

    @dataclass(frozen=True)
    class FakeStrategyOutput:
        summary: str
        thesis: str

    @dataclass(frozen=True)
    class FakeChallengerOutput:
        summary: str
        concerns: tuple[str, ...]

    @dataclass(frozen=True)
    class FakeJudgeOutput:
        summary: str
        final_judgment: str
        confidence_score: Decimal

    monkeypatch.setattr(
        admin_cli.StrategyDebateWorkflow,
        "run",
        lambda self, portfolio_id, period_start, period_end, trigger_source: SimpleNamespace(
            run_id="strategy-debate-1",
            workflow_name="strategy_debate",
            portfolio_id=portfolio_id,
            period_start=period_start,
            period_end=period_end,
            strategy_proposal_record_id=7,
            strategy_output=FakeStrategyOutput(summary="Hold core funds.", thesis="Stay steady."),
            challenger_output=FakeChallengerOutput(
                summary="Watch concentration risk.",
                concerns=("concentration",),
            ),
            judge_output=FakeJudgeOutput(
                summary="Proceed with caution.",
                final_judgment="monitor",
                confidence_score=Decimal("0.75"),
            ),
        ),
    )

    admin_cli.main(
        [
            "workflow",
            "run",
            "monthly-strategy-debate",
            "--portfolio-id",
            str(portfolio.id),
            "--period-start",
            "2026-03-01",
            "--period-end",
            "2026-03-31",
        ]
    )

    data = json.loads(capsys.readouterr().out)
    assert data["workflow_name"] == "strategy_debate"
    assert data["final_decision"] == "monitor"
    assert data["confidence_score"] == 0.75
