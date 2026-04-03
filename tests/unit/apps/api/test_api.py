"""API tests for the FastAPI layer."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, StaticPool
from sqlalchemy.orm import Session, sessionmaker

from fund_manager.apps.api.dependencies import get_db
from fund_manager.apps.api.main import app
from fund_manager.storage.models import Base, FundMaster, Portfolio, PositionLot


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


def test_list_reports_empty(client: TestClient) -> None:
    response = client.get("/api/v1/reports")
    assert response.status_code == 200
    assert response.json() == []


def test_import_holdings_dry_run(client: TestClient) -> None:
    csv_content = "fund_code,fund_name,units,avg_cost,total_cost,portfolio_name\n000002,New Fund,50.000000,1.50000000,75.0000,main\n"
    response = client.post(
        "/api/v1/imports/holdings?dry_run=true",
        files={"file": ("holdings.csv", csv_content, "text/csv")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["dry_run"] is True
