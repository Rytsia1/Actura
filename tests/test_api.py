"""
Tests for the FastAPI valuation endpoints.
"""

import pytest
from fastapi.testclient import TestClient

from actuary_engine.main import app


@pytest.fixture(scope="session")
def client() -> TestClient:
    """FastAPI TestClient instance."""
    return TestClient(app)


def test_health_check(client: TestClient) -> None:
    """Health check endpoint returns healthy status."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "SOA Illustrative Life Table" in data["table"]


def test_table_metadata(client: TestClient) -> None:
    """SOA ILT metadata endpoint returns expected ranges."""
    response = client.get("/api/v1/tables/soa_ilt")
    assert response.status_code == 200
    data = response.json()
    assert data["min_age"] == 0
    assert data["omega"] == 110
    assert "q30" in data["sample_qx"]


def test_deterministic_valuation_endpoint(client: TestClient) -> None:
    """Deterministic endpoint calculates net premium, reserves, and cash flows."""
    payload = {
        "product_type": "endowment",
        "issue_age": 30,
        "term": 20,
        "sum_assured": 1_000_000,
        "interest_rate": 0.05,
    }
    response = client.post("/api/v1/valuation/deterministic", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["product_type"] == "endowment"
    assert data["annual_net_premium"] > 0
    assert len(data["reserve_profile"]) == 21  # t=0..20
    assert len(data["cash_flows"]) == 20
    # Boundary reserves: t=0 is 0, t=20 is 1,000,000
    assert data["reserve_profile"][0]["reserve_prospective"] == 0.0
    assert data["reserve_profile"][-1]["reserve_prospective"] == 1_000_000.0


def test_stochastic_valuation_endpoint(client: TestClient) -> None:
    """Stochastic endpoint runs Monte Carlo simulation and returns risk metrics & fan chart."""
    payload = {
        "product_type": "term",
        "issue_age": 30,
        "term": 15,
        "sum_assured": 500_000,
        "vasicek": {
            "r0": 0.05,
            "kappa": 0.20,
            "theta": 0.05,
            "sigma": 0.015,
        },
        "dynamic_lapse": {
            "credited_rate": 0.04,
            "sensitivity": 20.0,
        },
        "n_scenarios": 200,
        "seed": 42,
    }
    response = client.post("/api/v1/valuation/stochastic", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert "mean_bel" in data
    assert "var_95" in data
    assert "cvar_95" in data
    assert data["var_95"] <= data["var_99"]
    assert len(data["fan_chart_rates"]) == 16  # 0..15 years
    assert len(data["liability_histogram"]) > 0


def test_deterministic_valuation_zero_interest_rate(client: TestClient) -> None:
    """Deterministic endpoint accepts interest_rate=0.0 (v=1.0) and computes valid results."""
    payload = {
        "product_type": "whole_life",
        "issue_age": 30,
        "sum_assured": 100_000,
        "interest_rate": 0.0,
    }
    response = client.post("/api/v1/valuation/deterministic", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["product_type"] == "whole_life"
    assert data["nsp"] == 100_000.0  # Whole life NSP at 0% interest is sum_assured * 1.0
    assert data["annual_net_premium"] > 0


def test_deterministic_valuation_invalid_duration_rates_rejected(client: TestClient) -> None:
    """Deterministic endpoint rejects duration_rates outside [0, 1] with 422 Unprocessable Entity."""
    payload = {
        "product_type": "endowment",
        "issue_age": 30,
        "term": 10,
        "sum_assured": 100_000,
        "lapse": {
            "duration_rates": [-0.5, 2.0],
            "flat_annual_rate": 0.03,
        },
    }
    response = client.post("/api/v1/valuation/deterministic", json=payload)
    assert response.status_code == 422


