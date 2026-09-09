import pytest
from fastapi.testclient import TestClient

from actuary_engine.api.main import app

client = TestClient(app)

def test_generate_guided_term_life_success():
    payload = {
        "product_type": "term_life",
        "issue_age": 30,
        "term": 15,
        "sum_assured": 500000.0,
        "premium_freq": "annual",
        "table_id": "soa_ilt",
        "interest_rate": 0.05,
        "lapse_rate": 0.02,
        "expense_first_year_pct": 0.35,
        "expense_renewal_pct": 0.05
    }
    
    response = client.post("/api/v1/contracts/guided/term-life", json=payload)
    assert response.status_code == 200
    
    data = response.json()
    assert data["contract_id"] == "guided_term_life"
    assert len(data["nodes"]) == 6  # policyInput, inflow, contingency, outflow(death), outflow(expense), sink
    assert len(data["edges"]) == 7  # 5 standard + 2 expense
    
    # Verify policy node configuration
    policy_node = next(n for n in data["nodes"] if n["type"] == "policyInput")
    assert policy_node["data"]["age"] == 30
    assert policy_node["data"]["term"] == 15
    assert policy_node["data"]["sum_assured"] == 500000.0


def test_generate_guided_term_life_without_expenses():
    payload = {
        "product_type": "term_life",
        "issue_age": 40,
        "term": 20,
        "sum_assured": 1000000.0,
        "premium_freq": "annual",
        "table_id": "soa_ilt",
        "interest_rate": 0.04,
        "lapse_rate": 0.0,
        "expense_first_year_pct": None,
        "expense_renewal_pct": None
    }
    
    response = client.post("/api/v1/contracts/guided/term-life", json=payload)
    assert response.status_code == 200
    
    data = response.json()
    assert len(data["nodes"]) == 5  # No expense node
    assert len(data["edges"]) == 5


def test_generate_guided_term_life_invalid_age():
    payload = {
        "product_type": "term_life",
        "issue_age": -5,
        "term": 15,
        "sum_assured": 500000.0
    }
    
    response = client.post("/api/v1/contracts/guided/term-life", json=payload)
    assert response.status_code == 422  # Pydantic validation error


def test_generate_guided_term_life_invalid_table():
    payload = {
        "product_type": "term_life",
        "issue_age": 30,
        "term": 15,
        "sum_assured": 500000.0,
        "table_id": "invalid_table"
    }
    
    response = client.post("/api/v1/contracts/guided/term-life", json=payload)
    assert response.status_code == 400
    assert "Generated blueprint is invalid" in response.json()["detail"]
