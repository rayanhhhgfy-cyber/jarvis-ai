# ====================================================================
# JARVIS OMEGA — Main FastAPI Unit Tests
# ====================================================================
"""
Unit tests for backend main entry point, routing, and health check.
"""

from fastapi.testclient import TestClient
from backend.main import app


def test_app_metadata():
    """Verify application title and metadata."""
    assert app.title == "JARVIS OMEGA Backend"
    assert app.version == "1.0.0"


def test_routes_registered():
    """Verify that all core modular routers are registered."""
    route_paths = [route.path for route in app.routes]
    
    # Check REST and WS endpoints are present
    assert "/health" in route_paths
    assert "/ws/{device_id}" in route_paths
    assert "/api/system/vitals" in route_paths
    assert "/api/devices/pair/initiate" in route_paths
    assert "/api/approvals/pending" in route_paths
    assert "/api/tasks" in route_paths
    assert "/api/chat" in route_paths
    assert "/api/shortcuts" in route_paths


def test_health_endpoint():
    """Verify that the health check endpoint returns correctly even without services initialized."""
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "online"
        assert "health" in data
        assert "active_connections" in data
        assert "tasks_in_queue" in data
