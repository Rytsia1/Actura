"""
Tests for Task 16: Audit Events and Model Lifecycle Management.
"""
import pytest
from fastapi.testclient import TestClient
from actuary_engine.api.main import app
from actuary_engine.infrastructure.audit_repo import audit_repo
from actuary_engine.infrastructure.scenario_repo import scenario_repo

from actuary_engine.api.dependencies import get_current_user
app.dependency_overrides.pop(get_current_user, None)

@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client

def set_role(role: str):
    user_id = f"{role.lower()}1"
    app.dependency_overrides[get_current_user] = lambda: {"id": user_id, "role": role, "org_id": "default-org"}

def test_create_model_emits_audit(client):
    set_role("Actuary")
    res = client.post("/api/v1/models", json={
        "name": "Audit Test Model",
        "product_type": "endowment",
        "issue_age": 40,
        "sum_assured": 500000,
        "interest_rate": 0.04
    })
    assert res.status_code == 200
    model_id = res.json()["id"]
    assert res.json()["lifecycle_status"] == "Draft"
    
    audit = client.get(f"/api/v1/models/{model_id}/audit")
    assert audit.status_code == 200
    logs = audit.json()
    assert len(logs) >= 1
    assert logs[0]["action"] == "MODEL_CREATED"
    assert logs[0]["user_id"] == "actuary1"

def test_update_model_emits_audit(client):
    set_role("Actuary")
    res = client.post("/api/v1/models", json={
        "name": "Update Test Model",
        "product_type": "endowment",
        "issue_age": 40,
        "sum_assured": 500000,
        "interest_rate": 0.04
    })
    model_id = res.json()["id"]
    
    update_res = client.put(f"/api/v1/models/{model_id}", json={
        "name": "Updated Name"
    })
    assert update_res.status_code == 200
    
    audit = client.get(f"/api/v1/models/{model_id}/audit")
    logs = audit.json()
    assert len(logs) >= 2
    assert logs[0]["action"] == "MODEL_UPDATED"
    assert logs[0]["previous_value"]["name"] == "Update Test Model"
    assert logs[0]["new_value"]["name"] == "Updated Name"

def test_lifecycle_transitions(client):
    set_role("Actuary")
    res = client.post("/api/v1/models", json={
        "name": "Lifecycle Test Model",
        "product_type": "endowment",
        "issue_age": 40,
        "sum_assured": 500000,
        "interest_rate": 0.04
    })
    model_id = res.json()["id"]
    
    # Actuary submits model
    submit_res = client.put(f"/api/v1/models/{model_id}/status", json={"status": "Submitted"})
    assert submit_res.status_code == 200
    assert submit_res.json()["lifecycle_status"] == "Submitted"
    
    # Actuary tries to approve model (should fail)
    approve_fail = client.put(f"/api/v1/models/{model_id}/status", json={"status": "Approved"})
    assert approve_fail.status_code == 403
    
    # Reviewer approves model
    set_role("Reviewer")
    approve_res = client.put(f"/api/v1/models/{model_id}/status", json={"status": "Approved"})
    assert approve_res.status_code == 200
    assert approve_res.json()["lifecycle_status"] == "Approved"
    
    # Check audit logs for approval
    audit = client.get(f"/api/v1/models/{model_id}/audit")
    logs = audit.json()
    assert logs[0]["action"] == "MODEL_APPROVED"

def test_locked_model_modification_blocked(client):
    set_role("Actuary")
    res = client.post("/api/v1/models", json={
        "name": "Lock Test Model",
        "product_type": "endowment",
        "issue_age": 40,
        "sum_assured": 500000,
        "interest_rate": 0.04
    })
    model_id = res.json()["id"]
    
    set_role("Reviewer")
    client.put(f"/api/v1/models/{model_id}/status", json={"status": "Locked"})
    
    # Try to modify locked model
    set_role("Actuary")
    update_fail = client.put(f"/api/v1/models/{model_id}", json={"name": "Hacked Name"})
    assert update_fail.status_code == 403
    assert "Locked" in update_fail.json()["detail"]
