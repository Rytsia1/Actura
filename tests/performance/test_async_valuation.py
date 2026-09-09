import pytest
import time
from fastapi.testclient import TestClient
from actuary_engine.main import app

client = TestClient(app)

@pytest.mark.performance
def test_async_valuation_end_to_end():
    """Test that async valuation completes and can be polled."""
    
    # 1. Setup - Create Project
    project_resp = client.post("/api/v1/workflow/start", json={
        "name": "Async Test Project",
        "description": "Async Polling Validation"
    })
    project_id = project_resp.json()["project_id"]
    
    # 2. Setup - Create Contract
    blueprint = {
        "nodes": [
            {"id": "policy_1", "type": "input", "config": {"age": 30, "sum_assured": 100000, "term": 10, "product_name": "Test", "interest_rate": 0.05}},
            {"id": "mort_1", "type": "mortality", "config": {"table_path": "soa_ilt.csv"}},
            {"id": "sink_1", "type": "output", "config": {}}
        ],
        "edges": [
            {"id": "e1", "source": "policy_1", "target": "mort_1"},
            {"id": "e2", "source": "mort_1", "target": "sink_1"}
        ]
    }
    client.post(f"/api/v1/workflow/{project_id}/contract", json={
        "name": "Async Test Contract",
        "product_type": "WholeLife",
        "blueprint_json": blueprint
    })
    
    # 3. Setup - Set Assumptions
    client.post(f"/api/v1/workflow/{project_id}/assumptions", json={
        "name": "Base Scenario",
        "assumptions": {"discount_rate": 0.05, "mortality_table": "soa_ilt.csv"}
    })
    
    # 4. Submit async job
    response = client.post(f"/api/v1/workflow/{project_id}/run")
    assert response.status_code == 200
    
    data = response.json()
    assert data["step"] == "running"
    assert "job_id" in data
    job_id = data["job_id"]
    
    # 2. Poll until completion (max 10 seconds)
    start_time = time.time()
    completed_data = None
    
    for _ in range(20):
        status_response = client.get(f"/api/v1/workflow/status/{job_id}")
        assert status_response.status_code == 200
        
        status_data = status_response.json()
        
        if status_data["step"] == "results":
            completed_data = status_data
            break
        
        time.sleep(0.5)
    
    elapsed = time.time() - start_time
    print(f"\n⏱️ Async Valuation completed in {elapsed:.2f} seconds")
    
    assert completed_data is not None, "Async valuation timed out"
    assert completed_data["step"] == "results"
    assert "result" in completed_data
    assert "bel" in completed_data["result"]
    assert completed_data["result"]["bel"] >= 0
