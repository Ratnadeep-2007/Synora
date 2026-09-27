import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.services.audit_service import AuditService
from app.services.metrics import metrics


def test_health_check_endpoints(client: TestClient):
    """Verify multi-component /health and /health/ready endpoints."""
    # 1. Detailed health check
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert "status" in data
    assert data["status"] in ("healthy", "degraded")
    assert "components" in data
    assert "database" in data["components"]
    assert data["components"]["database"]["status"] == "healthy"
    assert "connectors" in data["components"]
    assert "google_meet" in data["components"]["connectors"]
    assert "slack" in data["components"]["connectors"]

    # 2. Readiness check
    ready_res = client.get("/health/ready")
    assert ready_res.status_code == 200
    assert ready_res.json() == {"status": "ready"}


def test_operational_metrics_endpoint(client: TestClient):
    """Verify /metrics endpoint exposes live operational counters."""
    # Increment some real counters
    metrics.increment("ingestion_events_total", 5, labels={"source": "slack"})
    metrics.increment("state_changes_total", 2)
    metrics.increment("conflicts_total", 1)

    res = client.get("/metrics")
    assert res.status_code == 200
    snapshot = res.json()

    assert "summary" in snapshot
    assert snapshot["summary"]["ingestion_events_total"] >= 5
    assert snapshot["summary"]["state_changes_total"] >= 2
    assert snapshot["summary"]["conflicts_total"] >= 1


def test_audit_log_service_and_api(client: TestClient, db_session: Session):
    """Verify audit log recording, secret masking, and RBAC-controlled /audit endpoint."""
    audit_service = AuditService()

    # Record governance events
    entry = audit_service.record_event(
        action="state_change_approved",
        actor_id="admin_user_1",
        actor_role="admin",
        resource_type="project_state",
        resource_id="state_v2",
        before_state={"version": 1, "access_token": "secret_oauth_token"},
        after_state={"version": 2, "access_token": "secret_oauth_token"},
        db=db_session,
        tenant_id="tenant_audit_test",
    )

    assert entry.action == "state_change_approved"
    assert entry.tenant_id == "tenant_audit_test"
    # Secrets must be masked in audit trail
    assert "secret_oauth_token" not in entry.before_state_json
    assert "[REDACTED_SECRET]" in entry.before_state_json

    # Test /audit endpoint with ADMIN role -> succeeds
    res_admin = client.get("/audit?tenant_id=tenant_audit_test&role=admin")
    assert res_admin.status_code == 200
    logs = res_admin.json()
    assert len(logs) >= 1
    assert logs[0]["action"] == "state_change_approved"

    # Test /audit endpoint with VIEWER role -> rejected 403 Forbidden
    res_viewer = client.get("/audit?tenant_id=tenant_audit_test&role=viewer")
    assert res_viewer.status_code == 403
