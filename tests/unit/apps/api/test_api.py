"""API tests for the FastAPI layer."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

from fund_manager.apps.api.dependencies import get_db
from fund_manager.apps.api.main import app
from fund_manager.apps.api.routes.decisions import (
    DecisionFeedbackCreateRequest,
    create_decision_feedback,
)
from fund_manager.core.services import FundSyncDetailDTO, PortfolioFundSyncResultDTO
from fund_manager.storage.models import (
    AgentDebateLog,
    Base,
    DecisionFeedback,
    DecisionFeedbackStatus,
    DecisionRun,
    DecisionTransactionLink,
    FundMaster,
    NavSnapshot,
    Portfolio,
    PortfolioSnapshot,
    PositionLot,
    ReportPeriodType,
    ReviewReport,
    StrategyProposal,
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
    sess = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)()
    yield sess
    sess.close()


@pytest.fixture()
def client(session: Session, engine) -> TestClient:
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

    def _override_get_db():
        s = factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override_get_db
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def seed_portfolio_with_fund(session: Session) -> Portfolio:
    portfolio = Portfolio(portfolio_code="main", portfolio_name="Main Portfolio")
    fund = FundMaster(fund_code="000001", fund_name="Test Fund", source_name="test")
    session.add_all([portfolio, fund])
    session.flush()

    session.add(
        PositionLot(
            portfolio_id=portfolio.id,
            fund_id=fund.id,
            run_id="test-run",
            lot_key="test-lot",
            opened_on=date(2026, 3, 1),
            as_of_date=date(2026, 3, 15),
            remaining_units=Decimal("100.000000"),
            average_cost_per_unit=Decimal("1.00000000"),
            total_cost_amount=Decimal("100.0000"),
        )
    )
    session.commit()
    return portfolio


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["name"] == "fund-manager"


def test_list_portfolios_empty(client: TestClient) -> None:
    response = client.get("/api/v1/portfolios")
    assert response.status_code == 200
    assert response.json() == []


def test_list_portfolios_with_data(client: TestClient, session: Session) -> None:
    seed_portfolio_with_fund(session)
    response = client.get("/api/v1/portfolios")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["portfolio_code"] == "main"


def test_get_portfolio_snapshot_not_found(client: TestClient) -> None:
    response = client.get("/api/v1/portfolios/9999/snapshot")
    assert response.status_code == 404


def test_get_portfolio_snapshot(client: TestClient, session: Session) -> None:
    portfolio = seed_portfolio_with_fund(session)
    response = client.get(f"/api/v1/portfolios/{portfolio.id}/snapshot")
    assert response.status_code == 200
    data = response.json()
    assert data["portfolio_code"] == "main"
    assert data["position_count"] >= 1
    assert len(data["positions"]) >= 1
    assert data["positions"][0]["fund_code"] == "000001"


def test_get_position_breakdown(client: TestClient, session: Session) -> None:
    portfolio = seed_portfolio_with_fund(session)
    response = client.get(f"/api/v1/portfolios/{portfolio.id}/positions")
    assert response.status_code == 200
    data = response.json()
    assert data["portfolio_code"] == "main"
    assert len(data["positions"]) >= 1
    assert data["positions"][0]["fund_code"] == "000001"


def test_get_portfolio_metrics(client: TestClient, session: Session) -> None:
    portfolio = seed_portfolio_with_fund(session)
    fund = session.query(FundMaster).filter(FundMaster.fund_code == "000001").one()
    session.add(
        NavSnapshot(
            fund_id=fund.id,
            nav_date=date(2026, 3, 15),
            unit_nav_amount=Decimal("1.25000000"),
            source_name="test",
        )
    )
    session.commit()

    response = client.get(f"/api/v1/portfolios/{portfolio.id}/metrics?as_of_date=2026-03-15")
    assert response.status_code == 200
    data = response.json()
    assert data["portfolio_code"] == "main"
    assert data["metrics"]["position_count"] >= 1
    assert len(data["metrics"]["top_positions"]) >= 1


def test_get_portfolio_valuation_history(client: TestClient, session: Session) -> None:
    portfolio = seed_portfolio_with_fund(session)
    fund = session.query(FundMaster).filter(FundMaster.fund_code == "000001").one()
    session.add_all(
        [
            NavSnapshot(
                fund_id=fund.id,
                nav_date=date(2026, 3, 14),
                unit_nav_amount=Decimal("1.20000000"),
                source_name="test",
            ),
            NavSnapshot(
                fund_id=fund.id,
                nav_date=date(2026, 3, 15),
                unit_nav_amount=Decimal("1.25000000"),
                source_name="test",
            ),
        ]
    )
    session.commit()

    response = client.get(
        f"/api/v1/portfolios/{portfolio.id}/valuation-history?start_date=2026-03-14&end_date=2026-03-15"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["portfolio_code"] == "main"
    assert len(data["valuation_history"]) >= 1


def test_get_latest_report(client: TestClient, session: Session) -> None:
    portfolio = Portfolio(portfolio_code="main", portfolio_name="Main Portfolio")
    session.add(portfolio)
    session.flush()
    older_report = ReviewReport(
        portfolio_id=portfolio.id,
        run_id="weekly-review-20260308-abc12345",
        workflow_name="weekly_review",
        period_type=ReportPeriodType.WEEKLY,
        period_start=date(2026, 3, 1),
        period_end=date(2026, 3, 8),
        report_markdown="# Weekly Review\n\nOlder report.",
        summary_json={"summary": "Older report."},
        created_by_agent="ManualReviewAgent",
    )
    newer_report = ReviewReport(
        portfolio_id=portfolio.id,
        run_id="weekly-review-20260315-xyz98765",
        workflow_name="weekly_review",
        period_type=ReportPeriodType.WEEKLY,
        period_start=date(2026, 3, 8),
        period_end=date(2026, 3, 15),
        report_markdown="# Weekly Review\n\nNewer report.",
        summary_json={"summary": "Newer report."},
        created_by_agent="ManualReviewAgent",
    )
    session.add_all([older_report, newer_report])
    session.commit()

    response = client.get(f"/api/v1/portfolios/{portfolio.id}/latest-report")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == newer_report.id
    assert data["period_end"] == "2026-03-15"
    assert data["portfolio_code"] == "main"


def test_get_latest_report_not_found(client: TestClient, session: Session) -> None:
    portfolio = Portfolio(portfolio_code="main", portfolio_name="Main Portfolio")
    session.add(portfolio)
    session.commit()

    response = client.get(f"/api/v1/portfolios/{portfolio.id}/latest-report")

    assert response.status_code == 404
    assert response.json()["detail"] == "Report not found"


def test_get_latest_strategy_proposal(client: TestClient, session: Session) -> None:
    portfolio = Portfolio(portfolio_code="main", portfolio_name="Main Portfolio")
    session.add(portfolio)
    session.flush()
    older_proposal = StrategyProposal(
        portfolio_id=portfolio.id,
        run_id="strategy-debate-20260308-abc12345",
        workflow_name="strategy_debate",
        proposal_date=date(2026, 3, 8),
        thesis="Older proposal.",
        evidence_json={"summary": "Older."},
        recommended_actions_json=[{"action_type": "monitor"}],
        risk_notes="Older risk.",
        counterarguments="Older counterargument.",
        final_decision="monitor",
        confidence_score=Decimal("0.6500"),
        created_by_agent="ManualJudgeAgent",
    )
    newer_proposal = StrategyProposal(
        portfolio_id=portfolio.id,
        run_id="strategy-debate-20260315-xyz98765",
        workflow_name="strategy_debate",
        proposal_date=date(2026, 3, 15),
        thesis="Newer proposal.",
        evidence_json={"summary": "Newer."},
        recommended_actions_json=[{"action_type": "rebalance"}],
        risk_notes="Newer risk.",
        counterarguments="Newer counterargument.",
        final_decision="rebalance_required",
        confidence_score=Decimal("0.7800"),
        created_by_agent="ManualJudgeAgent",
    )
    session.add_all([older_proposal, newer_proposal])
    session.commit()

    response = client.get(f"/api/v1/portfolios/{portfolio.id}/latest-strategy-proposal")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == newer_proposal.id
    assert data["proposal_date"] == "2026-03-15"
    assert data["final_decision"] == "rebalance_required"


def test_get_latest_strategy_proposal_not_found(client: TestClient, session: Session) -> None:
    portfolio = Portfolio(portfolio_code="main", portfolio_name="Main Portfolio")
    session.add(portfolio)
    session.commit()

    response = client.get(f"/api/v1/portfolios/{portfolio.id}/latest-strategy-proposal")

    assert response.status_code == 404
    assert response.json()["detail"] == "Strategy proposal not found"


def test_get_fund_not_found(client: TestClient) -> None:
    response = client.get("/api/v1/funds/999999")
    assert response.status_code == 404


def test_get_fund_profile(client: TestClient, session: Session) -> None:
    seed_portfolio_with_fund(session)
    response = client.get("/api/v1/funds/000001")
    assert response.status_code == 200
    data = response.json()
    assert data["fund_name"] == "Test Fund"
    assert data["fund_code"] == "000001"


def test_get_fund_nav_history(client: TestClient, session: Session) -> None:
    seed_portfolio_with_fund(session)
    fund = session.query(FundMaster).filter(FundMaster.fund_code == "000001").one()
    session.add_all(
        [
            NavSnapshot(
                fund_id=fund.id,
                nav_date=date(2026, 3, 14),
                unit_nav_amount=Decimal("1.20000000"),
                source_name="test",
            ),
            NavSnapshot(
                fund_id=fund.id,
                nav_date=date(2026, 3, 15),
                unit_nav_amount=Decimal("1.25000000"),
                source_name="test",
            ),
        ]
    )
    session.commit()

    response = client.get(
        "/api/v1/funds/000001/nav-history?start_date=2026-03-14&end_date=2026-03-15"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["fund_code"] == "000001"
    assert len(data["points"]) == 2


def test_list_reports_empty(client: TestClient) -> None:
    response = client.get("/api/v1/reports")
    assert response.status_code == 200
    assert response.json() == []


def test_list_reports_with_data(client: TestClient, session: Session) -> None:
    portfolio = Portfolio(portfolio_code="main", portfolio_name="Main Portfolio")
    session.add(portfolio)
    session.flush()
    session.add(
        ReviewReport(
            portfolio_id=portfolio.id,
            run_id="weekly-review-20260315-abc12345",
            workflow_name="weekly_review",
            period_type=ReportPeriodType.WEEKLY,
            period_start=date(2026, 3, 8),
            period_end=date(2026, 3, 15),
            report_markdown="# Weekly Review",
            summary_json={"summary": "Stable week."},
            created_by_agent="ManualReviewAgent",
        )
    )
    session.commit()

    response = client.get(f"/api/v1/reports?portfolio_id={portfolio.id}")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["portfolio_id"] == portfolio.id
    assert data[0]["period_type"] == "weekly"
    assert data[0]["status"] == "completed"


def test_get_report_detail(client: TestClient, session: Session) -> None:
    portfolio = Portfolio(portfolio_code="main", portfolio_name="Main Portfolio")
    session.add(portfolio)
    session.flush()
    report = ReviewReport(
        portfolio_id=portfolio.id,
        run_id="weekly-review-20260315-abc12345",
        workflow_name="weekly_review",
        period_type=ReportPeriodType.WEEKLY,
        period_start=date(2026, 3, 8),
        period_end=date(2026, 3, 15),
        report_markdown="# Weekly Review\n\nStable week.",
        summary_json={"summary": "Stable week."},
        created_by_agent="ManualReviewAgent",
    )
    session.add(report)
    session.commit()

    response = client.get(f"/api/v1/reports/{report.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == report.id
    assert data["portfolio_code"] == "main"
    assert data["workflow_name"] == "weekly_review"
    assert data["report_markdown"].startswith("# Weekly Review")
    assert data["status"] == "completed"


def test_get_report_detail_not_found(client: TestClient) -> None:
    response = client.get("/api/v1/reports/9999")
    assert response.status_code == 404


def test_get_strategy_proposal_detail(client: TestClient, session: Session) -> None:
    portfolio = Portfolio(portfolio_code="main", portfolio_name="Main Portfolio")
    session.add(portfolio)
    session.flush()
    proposal = StrategyProposal(
        portfolio_id=portfolio.id,
        run_id="strategy-debate-20260315-abc12345",
        workflow_name="strategy_debate",
        proposal_date=date(2026, 3, 15),
        thesis="Keep current allocation.",
        evidence_json={"summary": "Valuation and trend support monitoring."},
        recommended_actions_json=[{"action_type": "monitor"}],
        risk_notes="Watch concentration risk.",
        counterarguments="Market volatility could rise.",
        final_decision="monitor",
        confidence_score=Decimal("0.7500"),
        created_by_agent="ManualJudgeAgent",
    )
    session.add(proposal)
    session.commit()

    response = client.get(f"/api/v1/strategy-proposals/{proposal.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == proposal.id
    assert data["portfolio_code"] == "main"
    assert data["workflow_name"] == "strategy_debate"
    assert data["final_decision"] == "monitor"
    assert data["confidence_score"] == 0.75


def test_get_strategy_proposal_detail_not_found(client: TestClient) -> None:
    response = client.get("/api/v1/strategy-proposals/9999")
    assert response.status_code == 404


def test_import_holdings_dry_run(client: TestClient) -> None:
    csv_content = (
        "fund_code,fund_name,units,avg_cost,total_cost,portfolio_name\n"
        "000002,New Fund,50.000000,1.50000000,75.0000,main\n"
    )
    response = client.post(
        "/api/v1/imports/holdings?dry_run=true",
        files={"file": ("holdings.csv", csv_content, "text/csv")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["dry_run"] is True


def test_create_decision_feedback_links_existing_transaction(
    session: Session,
) -> None:
    portfolio = Portfolio(portfolio_code="main", portfolio_name="Main Portfolio")
    fund = FundMaster(fund_code="000001", fund_name="Test Fund", source_name="test")
    session.add_all([portfolio, fund])
    session.flush()

    decision_run = DecisionRun(
        portfolio_id=portfolio.id,
        decision_date=date(2026, 3, 15),
        summary="Add Test Fund.",
        final_decision="rebalance_required",
        trigger_source="api_test",
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

    response = create_decision_feedback(
        decision_run.id,
        DecisionFeedbackCreateRequest(
            action_index=0,
            feedback_status="executed",
            feedback_date=date(2026, 3, 15),
            note="done",
            created_by="api-test",
        ),
        session,
    )

    assert response.decision_run_id == decision_run.id
    assert response.action_type == "add"
    assert response.linked_transaction_ids == [transaction.id]
    assert response.feedback_status.value == "executed"
    assert session.query(DecisionTransactionLink).count() == 1


def test_list_decision_runs(client: TestClient, session: Session) -> None:
    portfolio = Portfolio(portfolio_code="main", portfolio_name="Main Portfolio")
    older_run = DecisionRun(
        portfolio=portfolio,
        decision_date=date(2026, 3, 14),
        summary="Monitor existing positions.",
        final_decision="monitor",
        trigger_source="api_test",
        actions_json=[],
        created_by_agent="DecisionService",
    )
    newer_run = DecisionRun(
        portfolio=portfolio,
        decision_date=date(2026, 3, 15),
        summary="Add Test Fund.",
        final_decision="rebalance_required",
        trigger_source="api_test",
        actions_json=[
            {
                "action_type": "add",
                "fund_code": "000001",
            }
        ],
        created_by_agent="DecisionService",
    )
    session.add_all([portfolio, older_run, newer_run])
    session.commit()

    response = client.get(f"/api/v1/decisions?portfolio_id={portfolio.id}&limit=1")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == newer_run.id
    assert data[0]["final_decision"] == "rebalance_required"
    assert data[0]["action_count"] == 1


def test_get_decision_run_detail(client: TestClient, session: Session) -> None:
    portfolio = Portfolio(portfolio_code="main", portfolio_name="Main Portfolio")
    session.add(portfolio)
    session.flush()

    decision_run = DecisionRun(
        portfolio_id=portfolio.id,
        decision_date=date(2026, 3, 15),
        summary="Add Test Fund.",
        final_decision="rebalance_required",
        trigger_source="api_test",
        actions_json=[
            {
                "action_type": "add",
                "fund_code": "000001",
            }
        ],
        decision_summary_json={
            "policy_name": "baseline-current-allocation",
            "final_decision": "rebalance_required",
        },
        created_by_agent="DecisionService",
    )
    session.add(decision_run)
    session.commit()

    response = client.get(f"/api/v1/decisions/{decision_run.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == decision_run.id
    assert data["portfolio_code"] == "main"
    assert data["decision_summary_json"]["policy_name"] == "baseline-current-allocation"
    assert data["actions_json"][0]["action_type"] == "add"


def test_get_decision_run_detail_not_found(client: TestClient) -> None:
    response = client.get("/api/v1/decisions/9999")
    assert response.status_code == 404


def test_list_decision_feedback(client: TestClient, session: Session) -> None:
    portfolio = Portfolio(portfolio_code="main", portfolio_name="Main Portfolio")
    fund = FundMaster(fund_code="000001", fund_name="Test Fund", source_name="test")
    session.add_all([portfolio, fund])
    session.flush()

    decision_run = DecisionRun(
        portfolio_id=portfolio.id,
        decision_date=date(2026, 3, 15),
        summary="Add Test Fund.",
        final_decision="rebalance_required",
        trigger_source="api_test",
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
    session.add(decision_run)
    session.flush()

    feedback = DecisionFeedback(
        decision_run_id=decision_run.id,
        portfolio_id=portfolio.id,
        fund_id=fund.id,
        action_index=0,
        action_type="add",
        feedback_status=DecisionFeedbackStatus.EXECUTED,
        feedback_date=date(2026, 3, 16),
        note="done",
        created_by="api-test",
    )
    transaction = TransactionRecord(
        portfolio_id=portfolio.id,
        fund_id=fund.id,
        trade_date=date(2026, 3, 16),
        trade_type=TransactionType.BUY,
        units=Decimal("10.000000"),
        gross_amount=Decimal("12.0000"),
        source_name="manual",
    )
    session.add_all([feedback, transaction])
    session.flush()
    session.add(
        DecisionTransactionLink(
            feedback_id=feedback.id,
            transaction_id=transaction.id,
            match_source="reconcile_existing",
            match_reason="Matched buy transaction on feedback date.",
        )
    )
    session.commit()

    response = client.get(f"/api/v1/decisions/{decision_run.id}/feedback")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["feedback_status"] == "executed"
    assert data[0]["fund_code"] == "000001"
    assert data[0]["linked_transaction_ids"] == [transaction.id]


def test_list_decision_feedback_not_found(client: TestClient) -> None:
    response = client.get("/api/v1/decisions/9999/feedback")
    assert response.status_code == 404


def test_run_daily_decision_workflow(client: TestClient, session: Session) -> None:
    portfolio = seed_portfolio_with_fund(session)
    fund = session.query(FundMaster).filter(FundMaster.fund_code == "000001").one()
    session.add(
        NavSnapshot(
            fund_id=fund.id,
            nav_date=date(2026, 3, 14),
            unit_nav_amount=Decimal("1.25000000"),
            source_name="test",
        )
    )
    session.commit()

    response = client.post(
        "/api/v1/workflows/daily-decision/run",
        json={
            "portfolio_id": portfolio.id,
            "decision_date": "2026-03-15",
            "trigger_source": "api_test",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["portfolio_id"] == portfolio.id
    assert data["workflow_name"] == "daily_decision"
    assert data["final_decision"] == "no_active_policy"
    assert data["action_count"] == 1
    assert data["decision"]["actions"][0]["action_type"] == "set_policy"
    assert data["decision_run_id"] >= 1


def test_run_daily_decision_workflow_not_found(client: TestClient) -> None:
    response = client.post(
        "/api/v1/workflows/daily-decision/run",
        json={"portfolio_id": 9999, "decision_date": "2026-03-15"},
    )
    assert response.status_code == 404


def test_get_active_policy(client: TestClient, session: Session) -> None:
    portfolio = Portfolio(portfolio_code="main", portfolio_name="Main Portfolio")
    alpha_fund = FundMaster(fund_code="000001", fund_name="Alpha Fund", source_name="test")
    beta_fund = FundMaster(fund_code="000002", fund_name="Beta Fund", source_name="test")
    session.add_all([portfolio, alpha_fund, beta_fund])
    session.flush()

    PortfolioPolicyRepository(session).append(
        portfolio_id=portfolio.id,
        policy_name="core-balance",
        effective_from=date(2026, 3, 1),
        rebalance_threshold_ratio=Decimal("0.050000"),
        max_single_position_weight_ratio=Decimal("0.650000"),
        created_by="test",
        targets=(
            PortfolioPolicyTargetCreate(
                fund_id=alpha_fund.id,
                target_weight_ratio=Decimal("0.600000"),
            ),
            PortfolioPolicyTargetCreate(
                fund_id=beta_fund.id,
                target_weight_ratio=Decimal("0.400000"),
            ),
        ),
    )
    session.commit()

    response = client.get(
        f"/api/v1/policies/active?portfolio_id={portfolio.id}&as_of_date=2026-03-15"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["policy_name"] == "core-balance"
    assert data["portfolio_id"] == portfolio.id
    assert len(data["targets"]) == 2
    assert data["targets"][0]["fund_code"] == "000001"


def test_get_active_policy_not_found(client: TestClient, session: Session) -> None:
    portfolio = Portfolio(portfolio_code="main", portfolio_name="Main Portfolio")
    session.add(portfolio)
    session.commit()

    response = client.get(
        f"/api/v1/policies/active?portfolio_id={portfolio.id}&as_of_date=2026-03-15"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Active policy not found"


def test_create_policy(client: TestClient, session: Session) -> None:
    portfolio = Portfolio(portfolio_code="main", portfolio_name="Main Portfolio")
    alpha_fund = FundMaster(fund_code="000001", fund_name="Alpha Fund", source_name="test")
    beta_fund = FundMaster(fund_code="000002", fund_name="Beta Fund", source_name="test")
    session.add_all([portfolio, alpha_fund, beta_fund])
    session.commit()

    response = client.post(
        "/api/v1/policies",
        json={
            "portfolio_id": portfolio.id,
            "policy_name": "baseline-current-allocation",
            "effective_from": "2026-03-15",
            "rebalance_threshold_ratio": "0.030000",
            "max_single_position_weight_ratio": "0.350000",
            "created_by": "api-test",
            "notes": "seeded from canonical holdings",
            "targets": [
                {
                    "fund_code": "000001",
                    "target_weight_ratio": "0.550000",
                    "min_weight_ratio": "0.500000",
                    "max_weight_ratio": "0.600000",
                },
                {
                    "fund_code": "000002",
                    "target_weight_ratio": "0.450000",
                },
            ],
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["policy_name"] == "baseline-current-allocation"
    assert data["created_by"] == "api-test"
    assert len(data["targets"]) == 2
    assert data["targets"][1]["fund_code"] == "000002"


def test_create_policy_rejects_unknown_fund_code(client: TestClient, session: Session) -> None:
    portfolio = Portfolio(portfolio_code="main", portfolio_name="Main Portfolio")
    session.add(portfolio)
    session.commit()

    response = client.post(
        "/api/v1/policies",
        json={
            "portfolio_id": portfolio.id,
            "policy_name": "invalid-policy",
            "effective_from": "2026-03-15",
            "rebalance_threshold_ratio": "0.030000",
            "targets": [
                {
                    "fund_code": "999999",
                    "target_weight_ratio": "1.000000",
                }
            ],
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Fund '999999' was not found"


def test_run_daily_snapshot_workflow(
    client: TestClient,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    portfolio = seed_portfolio_with_fund(session)
    fund = session.query(FundMaster).filter(FundMaster.fund_code == "000001").one()
    session.add(
        NavSnapshot(
            fund_id=fund.id,
            nav_date=date(2026, 3, 15),
            unit_nav_amount=Decimal("1.25000000"),
            source_name="test",
        )
    )
    session.commit()

    def _fake_sync_portfolio_funds(self, portfolio_id: int, *, as_of_date: date):
        return PortfolioFundSyncResultDTO(
            portfolio_id=portfolio_id,
            as_of_date=as_of_date,
            processed_fund_count=1,
            profile_updated_count=0,
            nav_records_inserted=0,
            failed_fund_codes=(),
            funds=(
                FundSyncDetailDTO(
                    fund_id=fund.id,
                    fund_code=fund.fund_code,
                    fund_name=fund.fund_name,
                    profile_updated=False,
                    nav_records_inserted=0,
                    warnings=(),
                    errors=(),
                ),
            ),
        )

    monkeypatch.setattr(
        "fund_manager.apps.api.routes.workflows.FundDataSyncService.sync_portfolio_funds",
        _fake_sync_portfolio_funds,
    )

    response = client.post(
        "/api/v1/workflows/daily-snapshot/run",
        json={
            "portfolio_id": portfolio.id,
            "as_of_date": "2026-03-15",
            "trigger_source": "api_test",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["portfolio_id"] == portfolio.id
    assert data["workflow_name"] == "daily_snapshot"
    assert data["sync"]["processed_fund_count"] == 1
    assert data["snapshot"]["snapshot_record_id"] is not None
    assert session.query(PortfolioSnapshot).count() == 1


def test_run_monthly_strategy_debate_workflow(client: TestClient, session: Session) -> None:
    portfolio = seed_strategy_portfolio(session)

    response = client.post(
        "/api/v1/workflows/monthly-strategy-debate/run",
        json={
            "portfolio_id": portfolio.id,
            "period_start": "2026-03-08",
            "period_end": "2026-03-15",
            "trigger_source": "api_test",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["portfolio_id"] == portfolio.id
    assert data["workflow_name"] == "strategy_debate"
    assert data["strategy_proposal_record_id"] >= 1
    assert data["final_decision"] == "monitor_with_concentration_review"
    assert data["judge_output"]["final_judgment"] == "monitor_with_concentration_review"
    assert session.query(StrategyProposal).count() == 1
    assert session.query(AgentDebateLog).count() == 3


def test_run_monthly_strategy_debate_workflow_not_found(client: TestClient) -> None:
    response = client.post(
        "/api/v1/workflows/monthly-strategy-debate/run",
        json={"portfolio_id": 9999, "period_end": "2026-03-15"},
    )
    assert response.status_code == 404


def seed_strategy_portfolio(session: Session) -> Portfolio:
    portfolio = Portfolio(portfolio_code="strategy-main", portfolio_name="Strategy Main")
    alpha_fund = FundMaster(fund_code="000101", fund_name="Alpha Fund", source_name="test")
    beta_fund = FundMaster(fund_code="000102", fund_name="Beta Fund", source_name="test")
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
                unit_nav_amount=Decimal("3.50000000"),
                source_name="test",
            ),
        ]
    )
    session.commit()
    return portfolio
