"""Tests for the dashboard endpoint."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

from fund_manager.apps.api.dependencies import get_db
from fund_manager.apps.api.main import app
from fund_manager.storage.models import (
    Base,
    FundMaster,
    Portfolio,
    PositionLot,
    ReportPeriodType,
    ReviewReport,
)


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


def seed_portfolio(session: Session) -> Portfolio:
    portfolio = Portfolio(portfolio_code="main", portfolio_name="Main Portfolio", is_default=True)
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


def seed_report(session: Session, portfolio_id: int) -> ReviewReport:
    report = ReviewReport(
        portfolio_id=portfolio_id,
        period_type=ReportPeriodType.WEEKLY,
        period_start=date(2026, 3, 9),
        period_end=date(2026, 3, 15),
        report_markdown="# Weekly Report\nAll good.",
        created_by_agent="ReviewAgent",
        workflow_name="weekly_review",
    )
    session.add(report)
    session.commit()
    return report


def test_dashboard_empty(client: TestClient) -> None:
    response = client.get("/api/v1/dashboard")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Fund Manager" in response.text
    assert "No portfolio data available" in response.text


def test_dashboard_with_portfolio(client: TestClient, session: Session) -> None:
    seed_portfolio(session)
    response = client.get("/api/v1/dashboard")
    assert response.status_code == 200
    assert "Main Portfolio" in response.text
    assert "000001" in response.text
    assert "Test Fund" in response.text


def test_dashboard_with_reports(client: TestClient, session: Session) -> None:
    portfolio = seed_portfolio(session)
    seed_report(session, portfolio.id)
    response = client.get("/api/v1/dashboard")
    assert response.status_code == 200
    assert "2026-03-09" in response.text
    assert "weekly" in response.text
    assert "ReviewAgent" in response.text


def test_dashboard_theme_toggle_present(client: TestClient) -> None:
    response = client.get("/api/v1/dashboard")
    assert response.status_code == 200
    assert "theme-toggle" in response.text
    assert "data-theme" in response.text


def test_dashboard_positions_table_headers(client: TestClient, session: Session) -> None:
    seed_portfolio(session)
    response = client.get("/api/v1/dashboard")
    assert response.status_code == 200
    assert "Fund Code" in response.text
    assert "Weight" in response.text
    assert "PnL" in response.text
