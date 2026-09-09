"""
Tests for visual node-based contract graph DAG parser and simulation endpoint.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from actuary_engine.main import app
from actuary_engine.api.schemas import ContractGraphPayload, GraphEdgeData, GraphNodeData
from actuary_engine.valuation.graph_parser import ContractGraphSimulator


class TestContractGraphSimulator:
    """Test DAG validation, cycle detection, and cash flow projections."""

    def test_cycle_detection_raises_error(self) -> None:
        simulator = ContractGraphSimulator()
        payload = ContractGraphPayload(
            nodes=[
                GraphNodeData(id="node-1", type="policyInput", data={"age": 30, "term": 10}),
                GraphNodeData(id="node-2", type="inflow", data={"amount": 5000}),
            ],
            edges=[
                GraphEdgeData(source="node-1", target="node-2"),
                GraphEdgeData(source="node-2", target="node-1"),  # cycle!
            ],
        )

        with pytest.raises(ValueError, match="contains a cycle"):
            simulator.simulate(payload)

    def test_term_life_graph_simulation(self) -> None:
        simulator = ContractGraphSimulator()
        payload = ContractGraphPayload(
            contract_id="TEST-TERM-20",
            nodes=[
                GraphNodeData(
                    id="node-1",
                    type="policyInput",
                    data={
                        "product_name": "Term Life 20Y",
                        "age": 35,
                        "term": 20,
                        "sum_assured": 1_000_000.0,
                        "interest_rate": 0.05,
                        "table_id": "soa_ilt",
                    },
                ),
                GraphNodeData(
                    id="node-2",
                    type="inflow",
                    data={"inflow_type": "Gross Premium", "mode": "formula"},
                ),
                GraphNodeData(
                    id="node-3",
                    type="contingency",
                    data={"decrement_type": "Mortality", "multiplier": 1.0},
                ),
                GraphNodeData(
                    id="node-4",
                    type="outflow",
                    data={"benefit_type": "Death Benefit", "formula": "1.0 * SA"},
                ),
                GraphNodeData(
                    id="node-5",
                    type="valuationSink",
                    data={},
                ),
            ],
            edges=[
                GraphEdgeData(source="node-1", target="node-2", sourceHandle="policy_meta", targetHandle="inflow_in"),
                GraphEdgeData(source="node-1", target="node-3", sourceHandle="policy_meta", targetHandle="contingency_in"),
                GraphEdgeData(source="node-3", target="node-4", sourceHandle="on_death", targetHandle="outflow_in"),
                GraphEdgeData(source="node-2", target="node-5", sourceHandle="cash_inflow", targetHandle="sink_inflow"),
                GraphEdgeData(source="node-4", target="node-5", sourceHandle="cash_outflow", targetHandle="sink_outflow"),
            ],
        )

        res = simulator.simulate(payload)
        assert res.contract_id == "TEST-TERM-20"
        assert res.term == 20
        assert res.issue_age == 35
        assert res.sum_assured == 1_000_000.0
        assert res.annual_premium > 0
        assert len(res.years) == 20
        assert len(res.premiums) == 20
        assert len(res.death_claims) == 20
        assert len(res.reserves) == 21  # t=0..20
        assert res.maturity_payouts == [0.0] * 20  # no maturity in term life

    def test_endowment_graph_simulation(self) -> None:
        simulator = ContractGraphSimulator()
        payload = ContractGraphPayload(
            contract_id="TEST-ENDOW-15",
            nodes=[
                GraphNodeData(
                    id="node-1",
                    type="policyInput",
                    data={"age": 30, "term": 15, "sum_assured": 500_000.0, "interest_rate": 0.045},
                ),
                GraphNodeData(
                    id="node-2",
                    type="inflow",
                    data={"inflow_type": "Gross Premium", "mode": "formula"},
                ),
                GraphNodeData(
                    id="node-3",
                    type="contingency",
                    data={"decrement_type": "Mortality", "multiplier": 1.0},
                ),
                GraphNodeData(
                    id="node-4",
                    type="outflow",
                    data={"benefit_type": "Death Benefit", "formula": "1.0 * SA"},
                ),
                GraphNodeData(
                    id="node-5",
                    type="outflow",
                    data={"benefit_type": "Maturity Benefit", "formula": "1.0 * SA", "maturity_year": 15},
                ),
                GraphNodeData(
                    id="node-6",
                    type="valuationSink",
                    data={},
                ),
            ],
            edges=[
                GraphEdgeData(source="node-1", target="node-2"),
                GraphEdgeData(source="node-1", target="node-3"),
                GraphEdgeData(source="node-3", target="node-4"),
                GraphEdgeData(source="node-3", target="node-5"),
                GraphEdgeData(source="node-2", target="node-6"),
                GraphEdgeData(source="node-4", target="node-6"),
                GraphEdgeData(source="node-5", target="node-6"),
            ],
        )

        res = simulator.simulate(payload)
        assert res.term == 15
        assert res.maturity_payouts[-1] > 0  # Paid at maturity year 15
        assert res.annual_premium > 0
        assert len(res.reserves) == 16  # t=0..15


class TestContractGraphAPI:
    """Test FastAPI endpoint POST /api/v1/contracts/simulate-graph."""

    def test_api_simulate_graph_endpoint(self) -> None:
        client = TestClient(app)
        payload = {
            "contract_id": "API-GRAPH-01",
            "nodes": [
                {
                    "id": "node-1",
                    "type": "policyInput",
                    "data": {"product_name": "API Term", "age": 40, "term": 10, "sum_assured": 250_000.0},
                },
                {
                    "id": "node-2",
                    "type": "inflow",
                    "data": {"mode": "fixed", "amount": 1200.0},
                },
                {
                    "id": "node-3",
                    "type": "contingency",
                    "data": {"decrement_type": "Mortality"},
                },
                {
                    "id": "node-4",
                    "type": "outflow",
                    "data": {"benefit_type": "Death Benefit", "formula": "1.0 * SA"},
                },
                {
                    "id": "node-5",
                    "type": "valuationSink",
                    "data": {},
                },
            ],
            "edges": [
                {"source": "node-1", "target": "node-2"},
                {"source": "node-1", "target": "node-3"},
                {"source": "node-3", "target": "node-4"},
                {"source": "node-2", "target": "node-5"},
                {"source": "node-4", "target": "node-5"},
            ],
        }

        response = client.post("/api/v1/contracts/simulate-graph", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["contract_id"] == "API-GRAPH-01"
        assert data["annual_premium"] == 1200.0
        assert len(data["years"]) == 10
        assert len(data["reserves"]) == 11
        assert "total_bel" in data
