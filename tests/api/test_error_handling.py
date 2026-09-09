import pytest
from fastapi.testclient import TestClient
from actuary_engine.main import app
from actuary_engine.domain.blueprint.models import Blueprint, Node, Edge, NodeType

client = TestClient(app)

def test_invalid_blueprint_cycle_error():
    bp = Blueprint(
        nodes=[
            Node(id="n1", type=NodeType.INPUT),
            Node(id="n2", type=NodeType.PREMIUM),
            Node(id="n3", type=NodeType.CASHFLOW)
        ],
        edges=[
            Edge(id="e1", source="n1", target="n2"),
            Edge(id="e2", source="n2", target="n3"),
            Edge(id="e3", source="n3", target="n1")  # Cycle
        ]
    )
    response = client.post("/api/v1/blueprint/execute", json=bp.model_dump())
    
    assert response.status_code == 400
    data = response.json()
    assert data["error"] == "CYCLE_DETECTED"
    assert "Cycle detected" in data["details"]["reason"]
    assert "timestamp" in data
    assert data["path"] == "/api/v1/blueprint/execute"

def test_disconnected_node_error():
    bp = Blueprint(
        nodes=[
            Node(id="n1", type=NodeType.INPUT),
            Node(id="n2", type=NodeType.OUTPUT),
            Node(id="n3", type=NodeType.PREMIUM)  # Floating
        ],
        edges=[
            Edge(id="e1", source="n1", target="n2")
        ]
    )
    response = client.post("/api/v1/blueprint/execute", json=bp.model_dump())
    
    assert response.status_code == 400
    data = response.json()
    assert data["error"] == "DISCONNECTED_NODE"
    assert "completely disconnected" in data["details"]["reason"]
