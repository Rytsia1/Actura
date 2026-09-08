import pytest
from fastapi.testclient import TestClient
from actuary_engine.api.main import app
from actuary_engine.api.job_manager import job_manager

client = TestClient(app)

def test_deterministic_job_persistence():
    # Execute a deterministic valuation
    payload = {
        "product_type": "term",
        "issue_age": 30,
        "term": 20,
        "sum_assured": 100000.0,
        "premium_paying_term": 20,
        "interest_rate": 0.05,
        "table_id": "soa_ilt",
        "expense": {
            "percent_of_premium_first": 0.35,
            "percent_of_premium_renewal": 0.05,
            "per_policy_first": 200.0,
            "per_policy_renewal": 20.0
        },
        "lapse": {
            "flat_annual_rate": 0.03
        }
    }
    res = client.post("/api/v1/valuation/deterministic", json=payload)
    assert res.status_code == 200, res.json()
    
    # Query jobs
    jobs_res = client.get("/api/v1/jobs?limit=5")
    assert jobs_res.status_code == 200
    jobs = jobs_res.json()
    assert len(jobs) > 0
    
    # Find the newly created job
    det_job = None
    for j in jobs:
        meta = j.get("run_metadata") or {}
        if meta.get("valuation_type") == "Deterministic":
            det_job = j
            break
            
    assert det_job is not None
    assert det_job["status"] == "COMPLETED"
    assert det_job["progress"] == 100.0
    
    # Assert result payload is captured
    assert det_job["result"] is not None
    assert "bel" in det_job["result"]
    assert det_job["original_request"]["product_type"] == "term"


def test_ifrs17_job_persistence():
    payload = {
        "product_type": "term",
        "issue_age": 40,
        "term": 10,
        "sum_assured": 50000.0,
        "premium_paying_term": 10,
        "interest_rate": 0.04,
        "gross_premium": 250.0,
        "ra_ratio": 0.06
    }
    res = client.post("/api/v1/valuation/ifrs17", json=payload)
    assert res.status_code == 200, res.json()
    
    jobs_res = client.get("/api/v1/jobs?limit=5")
    assert jobs_res.status_code == 200
    jobs = jobs_res.json()
    
    ifrs_job = None
    for j in jobs:
        meta = j.get("run_metadata") or {}
        if meta.get("valuation_type") == "IFRS17":
            ifrs_job = j
            break
            
    assert ifrs_job is not None
    assert ifrs_job["status"] == "COMPLETED"
    assert "total_csm_released" in ifrs_job["result"]
