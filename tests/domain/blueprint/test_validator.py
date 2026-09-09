import pytest
from actuary_engine.domain.blueprint.models import Blueprint, Node, Edge, NodeType
from actuary_engine.domain.blueprint.validator import BlueprintValidator
from actuary_engine.domain.blueprint.exceptions import BlueprintValidationError

def test_empty_blueprint_raises():
    bp = Blueprint(nodes=[], edges=[])
    with pytest.raises(BlueprintValidationError, match="at least one node"):
        BlueprintValidator.validate(bp)

def test_cycle_detection():
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
    with pytest.raises(BlueprintValidationError, match="Cycle detected"):
        BlueprintValidator.validate(bp)

def test_disconnected_node():
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
    with pytest.raises(BlueprintValidationError, match="completely disconnected"):
        BlueprintValidator.validate(bp)

def test_invalid_connections_output():
    bp = Blueprint(
        nodes=[
            Node(id="n1", type=NodeType.INPUT),
            Node(id="n2", type=NodeType.OUTPUT),
            Node(id="n3", type=NodeType.PREMIUM)
        ],
        edges=[
            Edge(id="e1", source="n1", target="n2"),
            Edge(id="e2", source="n2", target="n3")  # OUTPUT pointing somewhere
        ]
    )
    with pytest.raises(BlueprintValidationError, match="Cannot connect OUTPUT node"):
        BlueprintValidator.validate(bp)

def test_missing_config_keys():
    bp = Blueprint(
        nodes=[
            Node(id="n1", type=NodeType.INPUT, config={"age": -1}),
            Node(id="n2", type=NodeType.OUTPUT)
        ],
        edges=[
            Edge(id="e1", source="n1", target="n2")
        ]
    )
    with pytest.raises(BlueprintValidationError, match="requires 'age' > 0"):
        BlueprintValidator.validate(bp)

def test_valid_graph():
    bp = Blueprint(
        nodes=[
            Node(id="in", type=NodeType.INPUT, config={"age": 30, "benefit_amount": 100000}),
            Node(id="mort", type=NodeType.MORTALITY, config={"table_name": "soa_ilt"}),
            Node(id="surv", type=NodeType.SURVIVAL),
            Node(id="ben", type=NodeType.BENEFIT),
            Node(id="cf", type=NodeType.CASHFLOW),
            Node(id="out", type=NodeType.OUTPUT)
        ],
        edges=[
            Edge(id="e1", source="in", target="mort"),
            Edge(id="e2", source="mort", target="surv"),
            Edge(id="e3", source="in", target="ben"),
            Edge(id="e4", source="ben", target="cf"),
            Edge(id="e5", source="surv", target="cf"),
            Edge(id="e6", source="cf", target="out")
        ]
    )
    # Should pass without raising
    BlueprintValidator.validate(bp)
