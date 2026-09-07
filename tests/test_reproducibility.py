import pytest
from fastapi.testclient import TestClient

from actuary_engine.api.main import app
from actuary_engine.api.schemas import StochasticValuationRequest
from actuary_engine.api.job_manager import job_manager

client = TestClient(app)

@pytest.fixture(autouse=True)
def clear_jobs():
    """Clear jobs table before and after each test."""
    from sqlalchemy import text
    with job_manager.engine.begin() as conn:
        conn.execute(text("DELETE FROM jobs"))
    yield
    with job_manager.engine.begin() as conn:
        conn.execute(text("DELETE FROM jobs"))


def get_base_request_dict() -> dict:
    return {
        "product_type": "term",
        "issue_age": 30,
        "term": 20,
        "sum_assured": 1_000_000,
        "n_scenarios": 100,  # Small enough for fast tests
        "table_id": "soa_ilt",
        "vasicek": {
            "r0": 0.05,
            "kappa": 0.1,
            "theta": 0.05,
            "sigma": 0.01
        }
    }


def test_sync_reproducibility_same_seed():
    """Test that two synchronous requests with the same seed yield identical results."""
    req_dict = get_base_request_dict()
    req_dict["seed"] = 12345

    res1 = client.post("/api/v1/valuation/stochastic", json=req_dict)
    assert res1.status_code == 200
    data1 = res1.json()

    res2 = client.post("/api/v1/valuation/stochastic", json=req_dict)
    assert res2.status_code == 200
    data2 = res2.json()

    assert data1["mean_bel"] == data2["mean_bel"]
    assert data1["var_99"] == data2["var_99"]
    assert data1["liability_histogram"] == data2["liability_histogram"]


def test_sync_reproducibility_different_seed():
    """Test that different seeds yield different results."""
    req_dict1 = get_base_request_dict()
    req_dict1["seed"] = 11111

    req_dict2 = get_base_request_dict()
    req_dict2["seed"] = 22222

    res1 = client.post("/api/v1/valuation/stochastic", json=req_dict1)
    res2 = client.post("/api/v1/valuation/stochastic", json=req_dict2)

    data1 = res1.json()
    data2 = res2.json()

    # Highly unlikely to be exactly identical for different seeds
    assert data1["mean_bel"] != data2["mean_bel"] or data1["var_99"] != data2["var_99"]


def test_async_auto_generated_seed_persisted():
    """Test that if a seed is omitted, the backend generates and persists one."""
    req_dict = get_base_request_dict()
    if "seed" in req_dict:
        del req_dict["seed"]

    res = client.post("/api/v1/valuation/stochastic/async", json=req_dict)
    assert res.status_code == 202
    job_id = res.json()["job_id"]

    status_res = client.get(f"/api/v1/valuation/stochastic/status/{job_id}")
    assert status_res.status_code == 200
    status_data = status_res.json()

    assert status_data["run_metadata"] is not None
    assert "seed" in status_data["run_metadata"]
    assert isinstance(status_data["run_metadata"]["seed"], int)

    assert status_data["original_request"] is not None
    assert status_data["original_request"]["seed"] is not None


def test_rerun_endpoint_preserves_configuration():
    """Test that the /rerun endpoint creates a new job with the identical original configuration."""
    req_dict = get_base_request_dict()
    req_dict["seed"] = 99999
    
    # 1. Start original job
    res1 = client.post("/api/v1/valuation/stochastic/async", json=req_dict)
    assert res1.status_code == 202
    job1_id = res1.json()["job_id"]

    # Wait for the job to complete to get the full run_metadata
    import time
    for _ in range(20):
        status1 = client.get(f"/api/v1/valuation/stochastic/status/{job1_id}").json()
        if status1["status"] in ["COMPLETED", "FAILED"]:
            break
        time.sleep(0.1)

    assert status1["status"] == "COMPLETED"
    meta1 = status1["run_metadata"]

    # 2. Rerun job
    res2 = client.post(f"/api/v1/valuation/stochastic/rerun/{job1_id}")
    assert res2.status_code == 202
    job2_id = res2.json()["job_id"]

    # Wait for the rerun job to complete
    for _ in range(20):
        status2 = client.get(f"/api/v1/valuation/stochastic/status/{job2_id}").json()
        if status2["status"] in ["COMPLETED", "FAILED"]:
            break
        time.sleep(0.1)

    assert status2["status"] == "COMPLETED"
    meta2 = status2["run_metadata"]

    assert job1_id != job2_id
    assert meta1["seed"] == meta2["seed"]
    assert meta1["n_scenarios"] == meta2["n_scenarios"]


def test_rerun_endpoint_with_new_seed():
    """Test that the /rerun endpoint can override the seed while keeping everything else."""
    req_dict = get_base_request_dict()
    req_dict["seed"] = 123
    
    res1 = client.post("/api/v1/valuation/stochastic/async", json=req_dict)
    job1_id = res1.json()["job_id"]

    res2 = client.post(f"/api/v1/valuation/stochastic/rerun/{job1_id}?new_seed=456")
    assert res2.status_code == 202
    job2_id = res2.json()["job_id"]

    status1 = client.get(f"/api/v1/valuation/stochastic/status/{job1_id}").json()
    status2 = client.get(f"/api/v1/valuation/stochastic/status/{job2_id}").json()

    assert status1["run_metadata"]["seed"] == 123
    assert status2["run_metadata"]["seed"] == 456
    assert status1["run_metadata"]["product_type"] == status2["run_metadata"]["product_type"]
