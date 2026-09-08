import pytest
from fastapi.testclient import TestClient

from actuary_engine.api.main import app

client = TestClient(app)

def test_assumption_lifecycle():
    # 1. Create a new assumption
    payload = {
        "name": "Base Mortality 2026",
        "type": "mortality",
        "description": "Standard base mortality",
        "parameters": {"table": "soa_ilt", "multiplier": 1.0}
    }
    
    resp1 = client.post("/api/v1/assumptions", json=payload)
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["version"] == 1
    assert data1["name"] == "Base Mortality 2026"
    assert data1["status"] == "ACTIVE"
    
    assump_id = data1["id"]
    
    # 2. Retrieve latest
    resp2 = client.get(f"/api/v1/assumptions/{assump_id}")
    assert resp2.status_code == 200
    assert resp2.json()["version"] == 1
    
    # 3. Create new version
    version_payload = {
        "description": "Updated multiplier",
        "parameters": {"table": "soa_ilt", "multiplier": 1.1}
    }
    resp3 = client.post(f"/api/v1/assumptions/{assump_id}/version", json=version_payload)
    assert resp3.status_code == 200
    data3 = resp3.json()
    assert data3["version"] == 2
    assert data3["name"] == "Base Mortality 2026"  # Inherited
    assert data3["parameters"]["multiplier"] == 1.1
    
    # 4. Check history
    resp4 = client.get(f"/api/v1/assumptions/{assump_id}/history")
    assert resp4.status_code == 200
    history = resp4.json()
    assert len(history) == 2
    assert history[0]["version"] == 2
    assert history[1]["version"] == 1
    assert history[1]["parameters"]["multiplier"] == 1.0 # V1 remains unchanged
    
    # 5. List all latest
    resp5 = client.get("/api/v1/assumptions?type=mortality")
    assert resp5.status_code == 200
    all_latest = resp5.json()
    # Find ours
    ours = next((a for a in all_latest if a["id"] == assump_id), None)
    assert ours is not None
    assert ours["version"] == 2
    
    # 6. Deactivate
    resp6 = client.put(f"/api/v1/assumptions/{assump_id}/status", json={"status": "INACTIVE"})
    assert resp6.status_code == 200
    assert resp6.json()["status"] == "INACTIVE"
    assert resp6.json()["version"] == 2
