"""Smoke tests for the API scaffold."""

from fastapi.testclient import TestClient

from fund_manager.apps.api.main import app


def test_health_endpoint_returns_service_status() -> None:
    """The scaffolded health endpoint should return service metadata."""
    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "environment": "local",
        "name": "fund-manager",
        "status": "ok",
    }
