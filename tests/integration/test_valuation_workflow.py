import pytest
from fastapi.testclient import TestClient
from actuary_engine.main import app
from actuary_engine.infrastructure.database import SessionLocal, engine, Base
import time

# Use a test database or clear tables for reliable testing
# For now, this assumes the DB is clean or we just create a new project which isolates data

client = TestClient(app)

def test_full_valuation_workflow():
    # 1. Create Project
    project_resp = client.post("/api/v1/workflow/start", json={
        "name": "E2E Test Project",
        "description": "E2E Validation"
    })
    assert project_resp.status_code == 200
    project_id = project_resp.json()["project_id"]
    
    # 2. Check current state
    state_resp = client.get(f"/api/v1/workflow/{project_id}/state")
    assert state_resp.status_code == 200
    assert state_resp.json()["step"] == "contract"
    
    # 3. Create Contract (with a simple blueprint)
    # The blueprint must pass validation in the backend
    blueprint = {
        "nodes": [
            {"id": "policy_1", "type": "input", "position": {"x": 0, "y": 0}, "config": {"age": 30, "sum_assured": 100000, "term": 10, "product_name": "Test", "interest_rate": 0.05}},
            {"id": "mort_1", "type": "mortality", "position": {"x": 100, "y": 0}, "config": {"table_path": "soa_ilt.csv"}},
            {"id": "sink_1", "type": "output", "position": {"x": 200, "y": 0}, "config": {}}
        ],
        "edges": [
            {"id": "e1", "source": "policy_1", "target": "mort_1"},
            {"id": "e2", "source": "mort_1", "target": "sink_1"}
        ]
    }
    contract_resp = client.post(f"/api/v1/workflow/{project_id}/contract", json={
        "name": "Test Whole Life",
        "product_type": "WholeLife",
        "blueprint_json": blueprint
    })
    assert contract_resp.status_code == 200
    assert contract_resp.json()["step"] == "assumptions"
    
    # Since we provided the blueprint upfront, it skips the blueprint step. 
    # Let's verify state is indeed assumptions.
    state_resp = client.get(f"/api/v1/workflow/{project_id}/state")
    assert state_resp.status_code == 200
    assert state_resp.json()["step"] == "assumptions"

    # 4. Set Assumptions
    assumptions_resp = client.post(f"/api/v1/workflow/{project_id}/assumptions", json={
        "name": "Base Scenario",
        "assumptions": {"discount_rate": 0.05, "mortality_table": "soa_ilt.csv"}
    })
    assert assumptions_resp.status_code == 200
    assert assumptions_resp.json()["step"] == "running"
    
    # 5. Run Valuation
    run_resp = client.post(f"/api/v1/workflow/{project_id}/run")
    assert run_resp.status_code == 200
    
    # 6. Poll until state is "results"
    for _ in range(15):
        time.sleep(1)
        state_resp = client.get(f"/api/v1/workflow/{project_id}/state")
        if state_resp.json()["step"] == "results":
            break
    
    final_state = state_resp.json()
    assert final_state["step"] == "results"
    assert "result" in final_state
    
    # Validate result contents
    assert final_state["result"]["bel"] >= 0
    assert "var_95" in final_state["result"]
    assert "cvar_95" in final_state["result"]

    print("\n[OK] Full valuation workflow completed successfully!")
