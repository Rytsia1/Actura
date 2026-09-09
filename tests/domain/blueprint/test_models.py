import pytest
from pydantic import ValidationError
from actuary_engine.domain.blueprint.models import Blueprint, Node, Edge, NodeType

def test_node_serialization():
    node = Node(
        id="input_1",
        type=NodeType.INPUT,
        config={"age": 30, "benefit": 100000},
        position={"x": 100, "y": 200}
    )
    
    dump = node.model_dump()
    assert dump["id"] == "input_1"
    assert dump["type"] == "input"
    assert dump["config"]["age"] == 30
    assert dump["position"]["x"] == 100

def test_blueprint_serialization():
    bp = Blueprint(
        name="Test",
        nodes=[
            Node(id="n1", type=NodeType.INPUT, config={"age": 30}),
            Node(id="n2", type=NodeType.MORTALITY, config={"table_name": "soa_ilt"})
        ],
        edges=[
            Edge(id="e1", source="n1", target="n2")
        ]
    )
    
    dump = bp.model_dump()
    assert len(dump["nodes"]) == 2
    assert len(dump["edges"]) == 1
    assert "id" in dump

def test_invalid_node_type_raises():
    with pytest.raises(ValidationError):
        Node(id="n1", type="UNKNOWN_TYPE", config={})
