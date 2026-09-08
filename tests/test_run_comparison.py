"""
Tests for Valuation Run Comparison & Configuration Difference Explanation (Task 11).

Verifies:
1. Side-by-side metric comparison (BEL, CSM, risk metrics, premiums, benefits, expenses, profit/loss).
2. Accurate absolute and percentage delta calculations.
3. Accurate configuration diff detection (model version, assumption versions, scenario, discount rate, mortality, lapse, etc.).
4. Automated human-readable difference explanation generation.
5. Cross-valuation type support (Deterministic, Scenario, IFRS 17).
6. Non-existent run handling (404).
7. List comparable runs endpoint.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from actuary_engine.api.main import app

client = TestClient(app)


def test_list_comparable_runs_endpoint():
    """Verify GET /api/v1/runs/comparable returns completed runs."""
    # Execute a quick deterministic run first
    client.post(
        "/api/v1/valuation/deterministic",
        json={
            "product_type": "term",
            "issue_age": 35,
            "term": 20,
            "sum_assured": 250000.0,
            "interest_rate": 0.05,
        },
    )

    res = client.get("/api/v1/runs/comparable")
    assert res.status_code == 200
    runs = res.json()
    assert isinstance(runs, list)
    assert len(runs) > 0
    first = runs[0]
    assert "job_id" in first
    assert "valuation_type" in first
    assert first["status"] == "COMPLETED"


def test_compare_runs_with_different_discount_rate():
    """Verify comparing Run A (5% interest) vs Run B (4% interest) detects discount rate change and BEL increase."""
    # 1. Execute Run A: 5% interest
    res_a = client.post(
        "/api/v1/valuation/deterministic",
        json={
            "product_type": "term",
            "issue_age": 30,
            "term": 20,
            "sum_assured": 500000.0,
            "interest_rate": 0.05,
        },
    )
    assert res_a.status_code == 200
    # Find job_id for Run A from jobs list
    jobs_res = client.get("/api/v1/jobs?limit=2")
    job_a_id = jobs_res.json()[0]["job_id"]

    # 2. Execute Run B: 4% interest (lower interest increases term PV liabilities)
    res_b = client.post(
        "/api/v1/valuation/deterministic",
        json={
            "product_type": "term",
            "issue_age": 30,
            "term": 20,
            "sum_assured": 500000.0,
            "interest_rate": 0.04,
        },
    )
    assert res_b.status_code == 200
    jobs_res2 = client.get("/api/v1/jobs?limit=2")
    job_b_id = jobs_res2.json()[0]["job_id"]
    assert job_a_id != job_b_id

    # 3. Compare Run A vs Run B
    res_comp = client.post(
        "/api/v1/runs/compare",
        json={"run_a_id": job_a_id, "run_b_id": job_b_id},
    )
    assert res_comp.status_code == 200
    data = res_comp.json()

    # Check top-level summaries
    assert data["run_a"]["job_id"] == job_a_id
    assert data["run_b"]["job_id"] == job_b_id

    # Check changed configurations
    assert "Discount Rate" in data["changed_elements"]

    disc_item = next(c for c in data["configurations"] if c["element_key"] == "discount_rate")
    assert disc_item["has_changed"] is True
    assert "5.00%" in disc_item["value_a"]
    assert "4.00%" in disc_item["value_b"]

    # Check metric comparisons
    bel_metric = next(m for m in data["metrics"] if m["metric_key"] == "bel")
    assert bel_metric["value_a"] is not None
    assert bel_metric["value_b"] is not None
    assert bel_metric["absolute_delta"] != 0
    assert bel_metric["percentage_delta"] != 0

    # Explanation text should mention Discount Rate
    explanation = data["summary_explanation"]
    assert "Discount Rate" in explanation


def test_compare_scenarios_with_mortality_change():
    """Verify comparing Base scenario vs High Mortality scenario detects mortality and scenario change."""
    # 1. Run Base scenario
    res_base = client.post("/api/v1/scenarios/scen-base/run")
    assert res_base.status_code == 200
    job_base_id = res_base.json()["job_id"]

    # 2. Run High Mortality scenario (+10% mortality)
    res_mort = client.post("/api/v1/scenarios/scen-high-mortality/run")
    assert res_mort.status_code == 200
    job_mort_id = res_mort.json()["job_id"]

    # 3. Compare
    res_comp = client.post(
        "/api/v1/runs/compare",
        json={"run_a_id": job_base_id, "run_b_id": job_mort_id},
    )
    assert res_comp.status_code == 200
    data = res_comp.json()

    assert "Mortality Assumption" in data["changed_elements"] or "Scenario" in data["changed_elements"]

    # Check BEL shift
    bel_item = next(m for m in data["metrics"] if m["metric_key"] == "bel")
    assert bel_item["absolute_delta"] != 0


def test_compare_ifrs17_runs():
    """Verify comparing IFRS 17 valuations compares CSM, LRC, and fulfilment cash flows."""
    # Run A: 4.5% rate, gross premium 300
    res_a = client.post(
        "/api/v1/valuation/ifrs17",
        json={
            "product_type": "term",
            "issue_age": 35,
            "term": 15,
            "sum_assured": 100000.0,
            "interest_rate": 0.045,
            "gross_premium": 300.0,
        },
    )
    assert res_a.status_code == 200
    job_a_id = client.get("/api/v1/jobs?limit=1").json()[0]["job_id"]

    # Run B: 4.0% rate, gross premium 350
    res_b = client.post(
        "/api/v1/valuation/ifrs17",
        json={
            "product_type": "term",
            "issue_age": 35,
            "term": 15,
            "sum_assured": 100000.0,
            "interest_rate": 0.04,
            "gross_premium": 350.0,
        },
    )
    assert res_b.status_code == 200
    job_b_id = client.get("/api/v1/jobs?limit=1").json()[0]["job_id"]

    res_comp = client.post(
        "/api/v1/runs/compare",
        json={"run_a_id": job_a_id, "run_b_id": job_b_id},
    )
    assert res_comp.status_code == 200
    data = res_comp.json()

    metric_keys = {m["metric_key"] for m in data["metrics"]}
    assert "bel" in metric_keys
    assert "csm" in metric_keys
    assert "initial_lrc" in metric_keys


def test_compare_identical_run():
    """Verify comparing a run with itself yields zero deltas and no changed configurations."""
    jobs = client.get("/api/v1/jobs?limit=1").json()
    job_id = jobs[0]["job_id"]

    res_comp = client.post(
        "/api/v1/runs/compare",
        json={"run_a_id": job_id, "run_b_id": job_id},
    )
    assert res_comp.status_code == 200
    data = res_comp.json()

    assert len(data["changed_elements"]) == 0
    assert all(c["has_changed"] is False for c in data["configurations"])

    for m in data["metrics"]:
        if m["value_a"] is not None and m["value_b"] is not None:
            assert m["absolute_delta"] == pytest.approx(0.0, abs=1e-3)
            assert m["percentage_delta"] == pytest.approx(0.0, abs=1e-3)

    assert "identical" in data["summary_explanation"].lower()


def test_compare_non_existent_run_raises_404():
    """Verify comparing with non-existent job ID returns 404."""
    res = client.post(
        "/api/v1/runs/compare",
        json={"run_a_id": "non-existent-job-1", "run_b_id": "non-existent-job-2"},
    )
    assert res.status_code == 404
