"""
Comprehensive test suite for First-Class Sensitivity Analysis & Valuation Driver Ranking (Task 10).

Verifies:
1. Shocks applied correctly across all 4 variables (mortality, lapse, discount rate, expense).
2. Base case remains strictly unchanged (immutability).
3. Results are reproducible and deterministic.
4. Invalid shocks are rejected with appropriate error status codes.
5. Sensitivity results and reproducibility metadata are persisted in the jobs table.
6. Valuation drivers are accurately ranked by absolute impact (swing magnitude).
7. Multiple valuation metrics (BEL, CSM, profit/loss) are supported and consistent.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from actuary_engine.api.main import app
from actuary_engine.api.job_manager import job_manager
from actuary_engine.infrastructure.scenario_repo import scenario_repo

client = TestClient(app)


def test_sensitivity_defaults_endpoint():
    """Verify GET /api/v1/sensitivity/defaults returns standard shock configurations."""
    res = client.get("/api/v1/sensitivity/defaults")
    assert res.status_code == 200
    data = res.json()
    assert "mortality" in data
    assert "discount_rate" in data
    assert "lapse" in data
    assert "expense" in data
    assert data["discount_rate"]["unit"] == "bps"
    assert data["mortality"]["shocks"] == [-0.20, -0.10, 0.0, 0.10, 0.20]
    assert data["discount_rate"]["shocks"] == [-200.0, -100.0, 0.0, 100.0, 200.0]


def test_default_sensitivity_analysis_execution():
    """Verify running default sensitivity analysis against default-endowment base model."""
    payload = {
        "base_model_id": "default-endowment",
        "target_metric": "bel",
    }
    res = client.post("/api/v1/sensitivity/analyze", json=payload)
    assert res.status_code == 200
    data = res.json()

    # Check top-level metadata
    assert data["base_model_id"] == "default-endowment"
    assert data["target_metric"] == "bel"
    assert isinstance(data["base_bel"], (int, float))
    assert data["base_metric_value"] == data["base_bel"]
    assert "analysis_id" in data
    assert "job_id" in data

    # Check grid points
    grid = data["grid_points"]
    # 4 variables * 5 shocks = 20 points
    assert len(grid) == 20

    variables_found = {pt["variable"] for pt in grid}
    assert variables_found == {"mortality", "discount_rate", "lapse", "expense"}

    # Base points should have 0 absolute change and 0 percentage change
    base_points = [pt for pt in grid if pt["shock_label"] == "Base"]
    assert len(base_points) == 4
    for bp in base_points:
        assert bp["resulting_metric"] == pytest.approx(data["base_metric_value"], abs=1e-2)
        assert bp["absolute_change"] == pytest.approx(0.0, abs=1e-2)
        assert bp["percentage_change"] == pytest.approx(0.0, abs=1e-2)

    # Shocks directionality check for endowment contract:
    # 1. Mortality +20% should change BEL
    mort_plus = next(pt for pt in grid if pt["variable"] == "mortality" and pt["shock_label"] == "+20%")
    assert mort_plus["resulting_metric"] != data["base_bel"]

    # 2. Discount rate shocks should shift BEL monotonically
    ir_minus200 = next(pt for pt in grid if pt["variable"] == "discount_rate" and pt["shock_label"] == "-200 bps")
    ir_minus100 = next(pt for pt in grid if pt["variable"] == "discount_rate" and pt["shock_label"] == "-100 bps")
    ir_base = next(pt for pt in grid if pt["variable"] == "discount_rate" and pt["shock_label"] == "Base")
    ir_plus100 = next(pt for pt in grid if pt["variable"] == "discount_rate" and pt["shock_label"] == "+100 bps")
    ir_plus200 = next(pt for pt in grid if pt["variable"] == "discount_rate" and pt["shock_label"] == "+200 bps")

    assert ir_minus200["resulting_metric"] < ir_minus100["resulting_metric"] < ir_base["resulting_metric"] < ir_plus100["resulting_metric"] < ir_plus200["resulting_metric"]
    assert ir_minus200["absolute_change"] != 0
    assert ir_plus200["absolute_change"] != 0


def test_driver_ranking_ordering():
    """Verify that assumptions are correctly ranked by absolute swing in descending order."""
    payload = {
        "base_model_id": "default-endowment",
        "target_metric": "bel",
    }
    res = client.post("/api/v1/sensitivity/analyze", json=payload)
    assert res.status_code == 200
    data = res.json()
    drivers = data["drivers"]

    assert len(drivers) == 4
    # Ensure ranks are 1, 2, 3, 4
    ranks = [d["rank"] for d in drivers]
    assert ranks == [1, 2, 3, 4]

    # Verify strictly descending order of swing
    swings = [d["swing"] for d in drivers]
    for i in range(len(swings) - 1):
        assert swings[i] >= swings[i + 1]

    # Rank 1 driver has the largest swing
    top_driver = drivers[0]
    assert top_driver["swing"] == max(swings)
    assert top_driver["max_abs_change"] > 0
    assert top_driver["most_adverse_shock"] != ""
    assert top_driver["most_favorable_shock"] != ""


def test_custom_configurable_shocks():
    """Verify that custom configurable shock ranges are respected."""
    payload = {
        "base_model_id": "default-endowment",
        "target_metric": "bel",
        "shocks": {
            "mortality_shocks": [-0.30, 0.0, 0.30],
            "interest_shocks_bps": [-150.0, 0.0, 150.0],
            "lapse_shocks": [-0.10, 0.0, 0.10],
            "expense_shocks": [0.0, 0.25],
        },
    }
    res = client.post("/api/v1/sensitivity/analyze", json=payload)
    assert res.status_code == 200
    data = res.json()
    grid = data["grid_points"]

    # 3 + 3 + 3 + 2 = 11 points
    assert len(grid) == 11
    mort_labels = [pt["shock_label"] for pt in grid if pt["variable"] == "mortality"]
    assert mort_labels == ["-30%", "Base", "+30%"]

    ir_labels = [pt["shock_label"] for pt in grid if pt["variable"] == "discount_rate"]
    assert ir_labels == ["-150 bps", "Base", "+150 bps"]


def test_supported_metrics_csm_and_profit_loss():
    """Verify that CSM and Profit/Loss are supported target metrics."""
    # 1. Target metric = CSM
    res_csm = client.post(
        "/api/v1/sensitivity/analyze",
        json={"base_model_id": "default-endowment", "target_metric": "csm"},
    )
    assert res_csm.status_code == 200
    data_csm = res_csm.json()
    assert data_csm["target_metric"] == "csm"
    assert data_csm["base_metric_value"] == data_csm["base_csm"]
    assert len(data_csm["drivers"]) == 4

    # 2. Target metric = Profit/Loss
    res_pl = client.post(
        "/api/v1/sensitivity/analyze",
        json={"base_model_id": "default-endowment", "target_metric": "profit_loss"},
    )
    assert res_pl.status_code == 200
    data_pl = res_pl.json()
    assert data_pl["target_metric"] == "profit_loss"
    assert data_pl["base_metric_value"] == data_pl["base_profit_loss"]
    # Profit/Loss should be inverse of BEL
    assert data_pl["base_profit_loss"] == pytest.approx(-data_pl["base_bel"], abs=1.0)


def test_base_case_remains_unchanged():
    """Verify that executing sensitivity sweeps leaves the base model strictly unmodified."""
    res_before = client.get("/api/v1/models/default-endowment")
    assert res_before.status_code == 200
    before_model = res_before.json()

    # Execute heavy sensitivity analysis
    res_sens = client.post(
        "/api/v1/sensitivity/analyze",
        json={
            "base_model_id": "default-endowment",
            "shocks": {
                "mortality_shocks": [-0.50, 0.0, 0.50],
                "interest_shocks_bps": [-300.0, 0.0, 300.0],
            },
        },
    )
    assert res_sens.status_code == 200

    # Query model after analysis
    res_after = client.get("/api/v1/models/default-endowment")
    assert res_after.status_code == 200
    after_model = res_after.json()

    # Assert immutability
    assert before_model["interest_rate"] == after_model["interest_rate"] == 0.05
    assert before_model["sum_assured"] == after_model["sum_assured"] == 1000000.0
    assert before_model["expense"] == after_model["expense"]
    assert before_model["lapse"] == after_model["lapse"]
    assert before_model["updated_at"] == after_model["updated_at"]


def test_results_are_reproducible():
    """Verify that identical sensitivity runs yield deterministic, identical numbers."""
    req = {
        "base_model_id": "default-endowment",
        "target_metric": "bel",
    }
    res1 = client.post("/api/v1/sensitivity/analyze", json=req).json()
    res2 = client.post("/api/v1/sensitivity/analyze", json=req).json()

    assert res1["base_metric_value"] == res2["base_metric_value"]
    assert len(res1["grid_points"]) == len(res2["grid_points"])

    for pt1, pt2 in zip(res1["grid_points"], res2["grid_points"]):
        assert pt1["variable"] == pt2["variable"]
        assert pt1["shock_label"] == pt2["shock_label"]
        assert pt1["resulting_metric"] == pytest.approx(pt2["resulting_metric"], abs=1e-4)
        assert pt1["absolute_change"] == pytest.approx(pt2["absolute_change"], abs=1e-4)

    for d1, d2 in zip(res1["drivers"], res2["drivers"]):
        assert d1["variable"] == d2["variable"]
        assert d1["rank"] == d2["rank"]
        assert d1["swing"] == pytest.approx(d2["swing"], abs=1e-4)


def test_invalid_shocks_are_rejected():
    """Verify that actuarially impossible or out-of-bounds shocks are rejected with 422."""
    # 1. Negative interest rate shock (e.g. -600 bps on 5% base rate -> -1%)
    res_ir = client.post(
        "/api/v1/sensitivity/analyze",
        json={
            "base_model_id": "default-endowment",
            "shocks": {"interest_shocks_bps": [-600.0]},
        },
    )
    assert res_ir.status_code == 422
    assert "interest rate" in res_ir.json()["detail"].lower()

    # 2. Rate exceeding 50%
    res_high_ir = client.post(
        "/api/v1/sensitivity/analyze",
        json={
            "base_model_id": "default-endowment",
            "shocks": {"interest_shocks_bps": [5000.0]},
        },
    )
    assert res_high_ir.status_code == 422

    # 3. Mortality multiplier <= 0 (-100% or less)
    res_mort = client.post(
        "/api/v1/sensitivity/analyze",
        json={
            "base_model_id": "default-endowment",
            "shocks": {"mortality_shocks": [-1.0]},
        },
    )
    assert res_mort.status_code == 422
    assert "mortality" in res_mort.json()["detail"].lower()

    # 4. Negative lapse multiplier
    res_lapse = client.post(
        "/api/v1/sensitivity/analyze",
        json={
            "base_model_id": "default-endowment",
            "shocks": {"lapse_shocks": [-1.50]},
        },
    )
    assert res_lapse.status_code == 422
    assert "lapse" in res_lapse.json()["detail"].lower()

    # 5. Non-existent base model
    res_model = client.post(
        "/api/v1/sensitivity/analyze",
        json={"base_model_id": "non-existent-model-xyz"},
    )
    assert res_model.status_code == 404


def test_sensitivity_results_are_persisted():
    """Verify that sensitivity analysis executions are recorded in the jobs table with reproducibility metadata."""
    res = client.post(
        "/api/v1/sensitivity/analyze",
        json={"base_model_id": "default-endowment", "target_metric": "bel"},
    )
    assert res.status_code == 200
    data = res.json()
    job_id = data["job_id"]
    analysis_id = data["analysis_id"]

    # Check job retrieval endpoint
    res_job = client.get(f"/api/v1/jobs/{job_id}")
    assert res_job.status_code == 200
    job_record = res_job.json()
    assert job_record["status"] == "COMPLETED"
    assert job_record["run_metadata"]["valuation_type"] == "Sensitivity"
    assert job_record["run_metadata"]["analysis_id"] == analysis_id
    assert "top_driver" in job_record["run_metadata"]
    assert "engine_version" in job_record["run_metadata"]

    # Check GET /api/v1/sensitivity/{id} endpoint
    res_sens_id = client.get(f"/api/v1/sensitivity/{job_id}")
    assert res_sens_id.status_code == 200
    sens_record = res_sens_id.json()
    assert sens_record["analysis_id"] == analysis_id
    assert len(sens_record["grid_points"]) == 20
