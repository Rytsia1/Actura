"""
Test suite for domain-aware actuarial validation of blueprint models.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from actuary_engine.api.main import app
from actuary_engine.api.schemas import ContractGraphPayload

client = TestClient(app)


def test_valid_blueprint() -> None:
    payload = {
        "nodes": [
            {
                "id": "policy_1",
                "type": "PolicyInput",
                "data": {"issue_age": 35, "term": 20, "sum_assured": 500000.0, "table_id": "soa_ilt", "interest_rate": 0.05}
            },
            {
                "id": "benefit_1",
                "type": "Outflow",
                "data": {"benefit_type": "Death Benefit", "formula": "1.0 * SA"}
            }
        ],
        "edges": [
            {"source": "policy_1", "target": "benefit_1"}
        ]
    }
    response = client.post("/api/v1/contracts/validate-graph", json=payload)
    assert response.status_code == 200
    res = response.json()
    assert res["is_valid"] is True
    # no ERROR issues
    assert not any(issue["severity"] == "ERROR" for issue in res["issues"])


def test_missing_policy_input() -> None:
    payload = {
        "nodes": [
            {
                "id": "benefit_1",
                "type": "Outflow",
                "data": {"benefit_type": "Death Benefit"}
            }
        ],
        "edges": []
    }
    response = client.post("/api/v1/contracts/validate-graph", json=payload)
    res = response.json()
    assert res["is_valid"] is False
    codes = [issue["code"] for issue in res["issues"]]
    assert "MISSING_POLICY_INPUT" in codes


def test_missing_valuation_sink() -> None:
    payload = {
        "nodes": [
            {
                "id": "policy_1",
                "type": "PolicyInput",
                "data": {"issue_age": 35, "term": 20}
            }
        ],
        "edges": []
    }
    response = client.post("/api/v1/contracts/validate-graph", json=payload)
    res = response.json()
    assert res["is_valid"] is False
    codes = [issue["code"] for issue in res["issues"]]
    assert "MISSING_VALUATION_SINK" in codes


def test_missing_mortality_data() -> None:
    payload = {
        "nodes": [
            {
                "id": "policy_1",
                "type": "PolicyInput",
                "data": {"issue_age": 35, "term": 20, "sum_assured": 500000.0, "table_id": "non_existent_table"}
            },
            {
                "id": "benefit_1",
                "type": "Outflow",
                "data": {"benefit_type": "Death Benefit"}
            }
        ],
        "edges": [
            {"source": "policy_1", "target": "benefit_1"}
        ]
    }
    response = client.post("/api/v1/contracts/validate-graph", json=payload)
    res = response.json()
    assert res["is_valid"] is False
    codes = [issue["code"] for issue in res["issues"]]
    assert "MISSING_MORTALITY_DATA" in codes


def test_mortality_coverage_exceeded() -> None:
    # SOA ILT max age is ~109. If issue_age + term > 109, it should fail.
    payload = {
        "nodes": [
            {
                "id": "policy_1",
                "type": "PolicyInput",
                "data": {"issue_age": 90, "term": 30, "sum_assured": 500000.0, "table_id": "soa_ilt"}
            },
            {
                "id": "benefit_1",
                "type": "Outflow",
                "data": {"benefit_type": "Death Benefit"}
            }
        ],
        "edges": [
            {"source": "policy_1", "target": "benefit_1"}
        ]
    }
    response = client.post("/api/v1/contracts/validate-graph", json=payload)
    res = response.json()
    assert res["is_valid"] is False
    codes = [issue["code"] for issue in res["issues"]]
    assert "MORTALITY_COVERAGE" in codes


def test_invalid_financial_assumptions() -> None:
    payload = {
        "nodes": [
            {
                "id": "policy_1",
                "type": "PolicyInput",
                "data": {"issue_age": 35, "term": 20, "sum_assured": -1000.0, "table_id": "soa_ilt"}
            },
            {
                "id": "benefit_1",
                "type": "Outflow",
                "data": {"benefit_type": "Death Benefit"}
            },
            {
                "id": "premium_1",
                "type": "Inflow",
                "data": {"mode": "fixed", "amount": -50.0}
            }
        ],
        "edges": [
            {"source": "policy_1", "target": "benefit_1"},
            {"source": "policy_1", "target": "premium_1"}
        ]
    }
    response = client.post("/api/v1/contracts/validate-graph", json=payload)
    res = response.json()
    assert res["is_valid"] is False
    codes = [issue["code"] for issue in res["issues"]]
    assert "NEGATIVE_FACE_AMOUNT" in codes
    assert "NEGATIVE_PREMIUM" in codes


def test_disconnected_node_warning() -> None:
    payload = {
        "nodes": [
            {
                "id": "policy_1",
                "type": "PolicyInput",
                "data": {"issue_age": 35, "term": 20, "sum_assured": 500000.0, "table_id": "soa_ilt"}
            },
            {
                "id": "benefit_1",
                "type": "Outflow",
                "data": {"benefit_type": "Death Benefit"}
            },
            {
                "id": "disconnected_contingency",
                "type": "Contingency",
                "data": {"decrement_type": "Mortality"}
            }
        ],
        "edges": [
            {"source": "policy_1", "target": "benefit_1"}
        ]
    }
    response = client.post("/api/v1/contracts/validate-graph", json=payload)
    res = response.json()
    # It should still be valid, but have a WARNING
    assert res["is_valid"] is True
    warnings = [issue for issue in res["issues"] if issue["severity"] == "WARNING"]
    assert len(warnings) > 0
    assert "DISCONNECTED_NODE" in [w["code"] for w in warnings]


def test_graph_cycle() -> None:
    payload = {
        "nodes": [
            {
                "id": "policy_1",
                "type": "PolicyInput",
                "data": {"issue_age": 35, "term": 20, "sum_assured": 500000.0, "table_id": "soa_ilt"}
            },
            {
                "id": "benefit_1",
                "type": "Outflow",
                "data": {"benefit_type": "Death Benefit"}
            }
        ],
        "edges": [
            {"source": "policy_1", "target": "benefit_1"},
            {"source": "benefit_1", "target": "policy_1"}  # cycle
        ]
    }
    response = client.post("/api/v1/contracts/validate-graph", json=payload)
    res = response.json()
    assert res["is_valid"] is False
    codes = [issue["code"] for issue in res["issues"]]
    assert "GRAPH_CYCLE" in codes


def test_simulate_endpoint_guard() -> None:
    """Ensure the simulate endpoint rejects invalid graphs based on the validator."""
    # This graph has a cycle, which should be rejected with 400 Bad Request
    payload = {
        "nodes": [
            {
                "id": "policy_1",
                "type": "PolicyInput",
                "data": {"issue_age": 35, "term": 20, "sum_assured": 500000.0, "table_id": "soa_ilt"}
            },
            {
                "id": "benefit_1",
                "type": "Outflow",
                "data": {"benefit_type": "Death Benefit"}
            }
        ],
        "edges": [
            {"source": "policy_1", "target": "benefit_1"},
            {"source": "benefit_1", "target": "policy_1"}  # cycle
        ]
    }
    response = client.post("/api/v1/contracts/simulate-graph", json=payload)
    assert response.status_code == 400
    assert "validation failed" in str(response.json()).lower()
