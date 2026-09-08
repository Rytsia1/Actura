"""
Tests for Actuarial Scenario Management, Assumption Overrides, Validation, Execution,
and Base Model Immutability.
"""
import pytest
from fastapi.testclient import TestClient

from actuary_engine.api.main import app
from actuary_engine.infrastructure.scenario_repo import scenario_repo
from actuary_engine.api.job_manager import job_manager

client = TestClient(app)


def test_scenario_creation_and_defaults():
    """Verify default pre-seeded scenarios exist and a custom scenario can be created."""
    # 1. Verify default base models exist
    res_models = client.get("/api/v1/models")
    assert res_models.status_code == 200
    models = res_models.json()
    model_ids = [m["id"] for m in models]
    assert "default-endowment" in model_ids

    # 2. Verify initial 5 scenarios exist for default-endowment
    res_scenarios = client.get("/api/v1/scenarios?base_model_id=default-endowment")
    assert res_scenarios.status_code == 200
    scenarios = res_scenarios.json()
    names = [s["name"] for s in scenarios]
    assert "Base" in names
    assert "High Mortality" in names
    assert "High Lapse" in names
    assert "Low Interest" in names
    assert "High Expense" in names

    # 3. Create a custom scenario
    custom_payload = {
        "name": "Severe Pandemic Shock",
        "description": "+50% mortality with -50 bps discount rate",
        "base_model_id": "default-endowment",
        "overrides": {
            "mortality_multiplier": 1.50,
            "interest_rate_bps": -50.0,
        },
        "status": "ACTIVE",
    }
    res_create = client.post("/api/v1/scenarios", json=custom_payload)
    assert res_create.status_code == 200
    created = res_create.json()
    assert created["name"] == "Severe Pandemic Shock"
    assert created["overrides"]["mortality_multiplier"] == 1.50
    assert created["overrides"]["interest_rate_bps"] == -50.0
    assert created["base_model_id"] == "default-endowment"


def test_scenario_duplicate():
    """Verify duplicating a scenario produces a new independent scenario with identical overrides."""
    res_dup = client.post("/api/v1/scenarios/scen-high-mortality/duplicate")
    assert res_dup.status_code == 200
    dup_data = res_dup.json()
    assert dup_data["id"] != "scen-high-mortality"
    assert "Copy of High Mortality" in dup_data["name"]
    assert dup_data["base_model_id"] == "default-endowment"
    assert dup_data["overrides"]["mortality_multiplier"] == 1.10

    # Custom name duplication
    res_dup_custom = client.post("/api/v1/scenarios/scen-high-lapse/duplicate?name=Extreme%20Lapse")
    assert res_dup_custom.status_code == 200
    assert res_dup_custom.json()["name"] == "Extreme Lapse"


def test_assumption_override():
    """Verify modifying overrides updates the scenario record correctly."""
    # Create a scenario to modify
    create_res = client.post(
        "/api/v1/scenarios",
        json={
            "name": "Test Override Mod",
            "base_model_id": "default-endowment",
            "overrides": {"interest_rate_bps": -25.0},
        },
    )
    scen_id = create_res.json()["id"]

    # Update the overrides
    update_res = client.put(
        f"/api/v1/scenarios/{scen_id}",
        json={
            "name": "Updated Override Mod",
            "overrides": {
                "interest_rate_bps": -75.0,
                "expense_multiplier": 1.25,
            },
            "status": "DRAFT",
        },
    )
    assert update_res.status_code == 200
    updated = update_res.json()
    assert updated["name"] == "Updated Override Mod"
    assert updated["overrides"]["interest_rate_bps"] == -75.0
    assert updated["overrides"]["expense_multiplier"] == 1.25
    assert updated["status"] == "DRAFT"


def test_scenario_validation():
    """Verify actuarial validation rules for scenario overrides."""
    # 1. Valid scenario passes validation
    res_val_base = client.post("/api/v1/scenarios/scen-base/validate")
    assert res_val_base.status_code == 200
    val_base = res_val_base.json()
    assert val_base["is_valid"] is True
    assert len(val_base["errors"]) == 0

    # 2. Invalid interest rate (resulting in negative rate)
    bad_ir_scen = client.post(
        "/api/v1/scenarios",
        json={
            "name": "Negative Rate Shock",
            "base_model_id": "default-endowment",
            "overrides": {"interest_rate_delta": -0.10},  # 5% - 10% = -5%
        },
    ).json()
    res_val_ir = client.post(f"/api/v1/scenarios/{bad_ir_scen['id']}/validate")
    assert res_val_ir.status_code == 200
    assert res_val_ir.json()["is_valid"] is False
    assert any("interest rate" in e.lower() for e in res_val_ir.json()["errors"])

    # 3. Invalid lapse rate (> 100%)
    bad_lapse_scen = client.post(
        "/api/v1/scenarios",
        json={
            "name": "Excessive Lapse Shock",
            "base_model_id": "default-endowment",
            "overrides": {"lapse_override": 1.50},  # 150% lapse
        },
    ).json()
    res_val_lapse = client.post(f"/api/v1/scenarios/{bad_lapse_scen['id']}/validate")
    assert res_val_lapse.status_code == 200
    assert res_val_lapse.json()["is_valid"] is False
    assert any("lapse rate" in e.lower() for e in res_val_lapse.json()["errors"])

    # 4. Invalid mortality multiplier (<= 0)
    bad_mort_scen = client.post(
        "/api/v1/scenarios",
        json={
            "name": "Negative Mortality Shock",
            "base_model_id": "default-endowment",
            "overrides": {"mortality_multiplier": -0.2},
        },
    ).json()
    res_val_mort = client.post(f"/api/v1/scenarios/{bad_mort_scen['id']}/validate")
    assert res_val_mort.status_code == 200
    assert res_val_mort.json()["is_valid"] is False
    assert any("mortality multiplier" in e.lower() for e in res_val_mort.json()["errors"])


def test_scenario_execution():
    """Verify running scenarios computes valuation metrics and expected actuarial relationships."""
    # 1. Execute Base scenario
    res_base = client.post("/api/v1/scenarios/scen-base/run")
    assert res_base.status_code == 200
    base_data = res_base.json()
    assert base_data["status"] == "COMPLETED"
    assert isinstance(base_data["bel"], (int, float))
    assert base_data["baseline_bel"] == pytest.approx(base_data["bel"], rel=1e-3)
    assert base_data["delta_bel"] == pytest.approx(0.0, abs=1.0)
    assert len(base_data["cash_flows"]) == 20
    assert len(base_data["reserve_profile"]) == 21

    # 2. Execute High Mortality scenario (+10% mortality)
    res_mort = client.post("/api/v1/scenarios/scen-high-mortality/run")
    assert res_mort.status_code == 200
    mort_data = res_mort.json()
    # High mortality increases death outgo and therefore increases net liability (delta_bel > 0)
    assert mort_data["bel"] != base_data["bel"]
    assert mort_data["delta_bel"] > 0
    assert mort_data["effective_mortality_multiplier"] == 1.10

    # 3. Execute Low Interest scenario (-100 bps)
    res_low_i = client.post("/api/v1/scenarios/scen-low-interest/run")
    assert res_low_i.status_code == 200
    low_i_data = res_low_i.json()
    assert low_i_data["bel"] != base_data["bel"]
    assert low_i_data["delta_bel"] != 0
    assert low_i_data["effective_interest_rate"] == pytest.approx(0.04, rel=1e-3)


def test_scenario_result_persistence():
    """Verify scenario execution persists a completed job in the jobs table with reproducibility metadata."""
    res_run = client.post("/api/v1/scenarios/scen-high-expense/run")
    assert res_run.status_code == 200
    run_data = res_run.json()
    job_id = run_data["job_id"]
    assert job_id is not None

    # Check job history endpoint
    res_job = client.get(f"/api/v1/jobs/{job_id}")
    assert res_job.status_code == 200
    job_record = res_job.json()
    assert job_record["status"] == "COMPLETED"
    assert job_record["run_metadata"]["scenario_id"] == "scen-high-expense"
    assert job_record["run_metadata"]["valuation_type"] == "Scenario"
    assert job_record["run_metadata"]["assumption_overrides"]["expense_multiplier"] == 1.10
    assert "engine_version" in job_record["run_metadata"]


def test_base_model_remains_unchanged():
    """Verify that running multiple scenarios against a base model leaves the base model strictly unmodified."""
    # Capture base model state before runs
    res_before = client.get("/api/v1/models/default-endowment")
    assert res_before.status_code == 200
    model_before = res_before.json()

    # Execute multiple heavy shock scenarios
    client.post("/api/v1/scenarios/scen-high-mortality/run")
    client.post("/api/v1/scenarios/scen-low-interest/run")
    client.post("/api/v1/scenarios/scen-high-lapse/run")

    # Capture base model state after runs
    res_after = client.get("/api/v1/models/default-endowment")
    assert res_after.status_code == 200
    model_after = res_after.json()

    # Assert strict equality
    assert model_before["interest_rate"] == model_after["interest_rate"] == 0.05
    assert model_before["sum_assured"] == model_after["sum_assured"] == 1000000.0
    assert model_before["expense"] == model_after["expense"]
    assert model_before["lapse"] == model_after["lapse"]
    assert model_before["product_type"] == model_after["product_type"] == "endowment"
    assert model_before["updated_at"] == model_after["updated_at"]
