import pytest
from fastapi.testclient import TestClient

from actuary_engine.api.main import app
from actuary_engine.api.schemas import (
    ContractGraphPayload,
    GraphEdgeData,
    GraphNodeData,
    HealthStatus,
)
from actuary_engine.services.model_health_service import model_health_service

client = TestClient(app)


def test_perfect_model_health_score_100():
    """Verify that a fully specified, compliant model achieves 100/100 and PASS across all 7 categories."""
    nodes = [
        GraphNodeData(
            id="node-input",
            type="policyInput",
            data={
                "issue_age": 30,
                "term": 20,
                "sum_assured": 500000.0,
                "interest_rate": 0.05,
                "table_id": "soa_ilt",
                "gross_premium": 6500.0,
                "seed": 42,
                "expense_first_year_pct": 0.35,
                "expense_renewal_pct": 0.05,
                "lapse_rate": 0.03,
                "assumption_refs": [
                    {"type": "mortality", "id": "soa_ilt", "version": "v1.0"}
                ],
            },
        ),
        GraphNodeData(
            id="node-benefit",
            type="outflow",
            data={"benefit_type": "death_benefit", "amount": 500000.0},
        ),
        GraphNodeData(
            id="node-sink",
            type="valuationSink",
            data={"name": "Liabilities Aggregate"},
        ),
    ]
    edges = [
        GraphEdgeData(source="node-input", target="node-benefit"),
        GraphEdgeData(source="node-benefit", target="node-sink"),
    ]
    payload = ContractGraphPayload(
        contract_id="PROD-TERM-20Y",
        nodes=nodes,
        edges=edges,
        discount_rate=0.05,
    )

    report = model_health_service.evaluate_blueprint(payload)
    assert report.is_ready_to_run is True
    assert report.overall_status == HealthStatus.PASS
    assert report.overall_score == 100

    # Verify all 7 categories exist and are PASS
    expected_categories = [
        "structure",
        "data",
        "assumptions",
        "validation",
        "coverage",
        "reproducibility",
        "configuration",
    ]
    for cat in expected_categories:
        assert cat in report.categories
        assert report.categories[cat].status == HealthStatus.PASS
        assert report.categories[cat].score == 100
        assert len(report.categories[cat].issues) == 0


def test_structure_cycle_and_missing_nodes():
    """Verify structural defects (cycles, missing ingress/egress) trigger FAIL with deep link metadata."""
    # 1. Circular dependency
    nodes_cycle = [
        GraphNodeData(id="n1", type="policyInput", data={}),
        GraphNodeData(id="n2", type="outflow", data={}),
    ]
    edges_cycle = [
        GraphEdgeData(source="n1", target="n2"),
        GraphEdgeData(source="n2", target="n1"),
    ]
    report_cycle = model_health_service.evaluate_blueprint(
        ContractGraphPayload(nodes=nodes_cycle, edges=edges_cycle)
    )
    assert report_cycle.is_ready_to_run is False
    assert report_cycle.overall_status == HealthStatus.FAIL
    assert report_cycle.categories["structure"].status == HealthStatus.FAIL
    assert any(i.code == "GRAPH_CYCLE" for i in report_cycle.categories["structure"].issues)

    # 2. Missing sink
    nodes_no_sink = [
        GraphNodeData(id="n1", type="policyInput", data={})
    ]
    report_no_sink = model_health_service.evaluate_blueprint(
        ContractGraphPayload(nodes=nodes_no_sink, edges=[])
    )
    assert report_no_sink.categories["structure"].status == HealthStatus.FAIL
    assert any(i.code == "MISSING_VALUATION_SINK" for i in report_no_sink.categories["structure"].issues)

    # 3. Disconnected node triggers WARNING
    nodes_disconnected = [
        GraphNodeData(id="n1", type="policyInput", data={"issue_age": 30, "term": 10, "sum_assured": 100000.0}),
        GraphNodeData(id="n2", type="outflow", data={}),
        GraphNodeData(id="orphan-1", type="outflow", data={}),
    ]
    edges_connected = [GraphEdgeData(source="n1", target="n2")]
    report_disc = model_health_service.evaluate_blueprint(
        ContractGraphPayload(nodes=nodes_disconnected, edges=edges_connected)
    )
    assert report_disc.categories["structure"].status == HealthStatus.WARNING
    assert any(w.code == "DISCONNECTED_NODE" and w.node_id == "orphan-1" for w in report_disc.categories["structure"].warnings)


def test_data_unknown_table_triggers_fail():
    """Verify nonexistent mortality table triggers FAIL in Data category."""
    nodes = [
        GraphNodeData(
            id="policy-1",
            type="policyInput",
            data={"table_id": "nonexistent_mortality_table_9999", "issue_age": 30, "term": 20},
        ),
        GraphNodeData(id="sink-1", type="valuationSink", data={}),
    ]
    edges = [GraphEdgeData(source="policy-1", target="sink-1")]
    report = model_health_service.evaluate_blueprint(
        ContractGraphPayload(nodes=nodes, edges=edges)
    )
    assert report.is_ready_to_run is False
    assert report.categories["data"].status == HealthStatus.FAIL
    assert report.categories["data"].score == 0
    issue = report.categories["data"].issues[0]
    assert issue.code == "MISSING_MORTALITY_DATA"
    assert issue.node_id == "policy-1"
    assert issue.field == "table_id"


def test_assumptions_warnings_and_unit_mismatch():
    """Verify assumption checks detect unit mismatch (>100%), unloaded expenses, and zero lapse."""
    nodes = [
        GraphNodeData(
            id="policy-1",
            type="policyInput",
            data={
                "issue_age": 35,
                "term": 20,
                "sum_assured": 100000.0,
                "interest_rate": 5.0,  # 500% -> should trigger unit warning
                "table_id": "soa_ilt",
            },
        ),
        GraphNodeData(id="sink-1", type="valuationSink", data={}),
    ]
    edges = [GraphEdgeData(source="policy-1", target="sink-1")]
    report = model_health_service.evaluate_blueprint(
        ContractGraphPayload(nodes=nodes, edges=edges)
    )
    assert report.is_ready_to_run is True
    assert report.categories["assumptions"].status == HealthStatus.WARNING
    warn_codes = [w.code for w in report.categories["assumptions"].warnings]
    assert "UNIT_MISMATCH" in warn_codes
    assert "UNLOADED_EXPENSES" in warn_codes
    assert "ZERO_LAPSE_ASSUMPTION" in warn_codes


def test_coverage_overflow_and_proximity_to_omega():
    """Verify coverage checks detect age + term exceeding table omega (FAIL) or approaching omega (WARNING)."""
    # 1. Overflow: Age 95 + Term 25 = 120 (soa_ilt omega is 110)
    nodes_overflow = [
        GraphNodeData(
            id="policy-1",
            type="policyInput",
            data={"issue_age": 95, "term": 25, "sum_assured": 10000.0, "table_id": "soa_ilt"},
        ),
        GraphNodeData(id="sink-1", type="valuationSink", data={}),
    ]
    report_of = model_health_service.evaluate_blueprint(
        ContractGraphPayload(nodes=nodes_overflow, edges=[GraphEdgeData(source="policy-1", target="sink-1")])
    )
    assert report_of.is_ready_to_run is False
    assert report_of.categories["coverage"].status == HealthStatus.FAIL
    assert any(i.code == "MORTALITY_COVERAGE_OVERFLOW" for i in report_of.categories["coverage"].issues)

    # 2. Proximity: Age 86 + Term 20 = 106 (within 5 years of omega 110)
    nodes_prox = [
        GraphNodeData(
            id="policy-2",
            type="policyInput",
            data={"issue_age": 86, "term": 20, "sum_assured": 10000.0, "table_id": "soa_ilt"},
        ),
        GraphNodeData(id="sink-2", type="valuationSink", data={}),
    ]
    report_prox = model_health_service.evaluate_blueprint(
        ContractGraphPayload(nodes=nodes_prox, edges=[GraphEdgeData(source="policy-2", target="sink-2")])
    )
    assert report_prox.categories["coverage"].status == HealthStatus.WARNING
    assert any(w.code == "PROXIMITY_TO_OMEGA" for w in report_prox.categories["coverage"].warnings)


def test_reproducibility_stochastic_seed_check():
    """Verify stochastic models without a pinned seed trigger a WARNING in Reproducibility."""
    nodes = [
        GraphNodeData(
            id="policy-1",
            type="policyInput",
            data={"issue_age": 30, "term": 10, "sum_assured": 100000.0, "seed": None},
        ),
        GraphNodeData(id="esg-node", type="esg", data={"model": "vasicek"}),
        GraphNodeData(id="sink-1", type="valuationSink", data={}),
    ]
    edges = [
        GraphEdgeData(source="policy-1", target="esg-node"),
        GraphEdgeData(source="esg-node", target="sink-1"),
    ]
    report = model_health_service.evaluate_blueprint(
        ContractGraphPayload(nodes=nodes, edges=edges)
    )
    assert report.categories["reproducibility"].status == HealthStatus.WARNING
    assert any(w.code == "UNPINNED_RANDOM_SEED" for w in report.categories["reproducibility"].warnings)


def test_explainable_scoring_transparency():
    """Verify that the health score is 100% explainable without arbitrary hidden weights."""
    nodes = [
        GraphNodeData(
            id="policy-1",
            type="policyInput",
            data={
                "issue_age": 30,
                "term": 10,
                "sum_assured": 100000.0,
                "interest_rate": 0.05,
                "table_id": "soa_ilt",
            },
        ),
        GraphNodeData(id="sink-1", type="valuationSink", data={}),
    ]
    edges = [GraphEdgeData(source="policy-1", target="sink-1")]
    report = model_health_service.evaluate_blueprint(
        ContractGraphPayload(nodes=nodes, edges=edges)
    )
    assert report.is_ready_to_run is True
    assert len(report.score_breakdown) > 0
    assert report.score_breakdown[0] == "Base Score: 100/100"
    # Verify score deductions add up
    total_deductions = 0
    for line in report.score_breakdown[1:]:
        if line.startswith("-"):
            pts = int(line.split(" ")[0].replace("-", "").replace("pts:", ""))
            total_deductions += pts
    assert report.overall_score == max(50, 100 - total_deductions)


def test_model_health_api_endpoints():
    """Test POST /api/v1/health/model and POST /api/v1/contracts/health endpoints."""
    nodes = [
        GraphNodeData(
            id="p-1",
            type="policyInput",
            data={"issue_age": 35, "term": 20, "sum_assured": 500000.0, "interest_rate": 0.05, "table_id": "soa_ilt"},
        ),
        GraphNodeData(id="s-1", type="valuationSink", data={}),
    ]
    edges = [GraphEdgeData(source="p-1", target="s-1")]
    blueprint_payload = {"contract_id": "API-TEST", "nodes": [n.model_dump() for n in nodes], "edges": [e.model_dump() for e in edges]}

    # 1. POST /api/v1/contracts/health
    res1 = client.post("/api/v1/contracts/health", json=blueprint_payload)
    assert res1.status_code == 200, res1.json()
    data1 = res1.json()
    assert "overall_score" in data1
    assert "categories" in data1
    assert len(data1["categories"]) == 7

    # 2. POST /api/v1/health/model with blueprint
    res2 = client.post("/api/v1/health/model", json={"blueprint": blueprint_payload})
    assert res2.status_code == 200, res2.json()
    data2 = res2.json()
    assert data2["overall_score"] == data1["overall_score"]

    # 3. POST /api/v1/health/model with configuration dict
    res3 = client.post("/api/v1/health/model", json={
        "configuration": {
            "product_type": "endowment",
            "issue_age": 30,
            "term": 20,
            "sum_assured": 100000.0,
            "interest_rate": 0.05,
            "table_id": "soa_ilt",
        }
    })
    assert res3.status_code == 200, res3.json()
    data3 = res3.json()
    assert data3["is_ready_to_run"] is True
    assert "structure" in data3["categories"]
