import pytest
import numpy as np
from actuary_engine.domain.blueprint.models import Blueprint, Node, Edge, NodeType
from actuary_engine.domain.blueprint.executor import BlueprintExecutor
from actuary_engine.domain.blueprint.validator import BlueprintValidator
from actuary_engine.domain.tables.mortality_table import MortalityTable
from actuary_engine.domain.tables.commutation import CommutationFunctions
from actuary_engine.models.assumptions import InterestAssumption
from actuary_engine.domain.pricing.insurance import InsurancePricer

def test_blueprint_execution_matches_deterministic_pricer():
    """
    Integration test proving the DAG compilation yields the mathematically identical
    Net Single Premium as the hardcoded WholeLife pricer class.
    """
    age = 35
    benefit_amount = 250000.0
    discount_rate = 0.05
    
    # 1. Deterministic baseline (Source of Truth)
    table = MortalityTable.from_soa_ilt()
    interest = InterestAssumption(annual_rate=discount_rate)
    comm = CommutationFunctions(table, interest)
    pricer = InsurancePricer(comm)
    
    expected_nsp = pricer.nsp_whole_life(age, benefit_amount)
    
    # 2. Visual Blueprint Engine Execution
    bp = Blueprint(
        nodes=[
            Node(id="in", type=NodeType.INPUT, config={"age": age, "benefit_amount": benefit_amount, "discount_rate": discount_rate}),
            Node(id="mort", type=NodeType.MORTALITY, config={"table_name": "soa_ilt"}),
            Node(id="surv", type=NodeType.SURVIVAL),
            Node(id="ben", type=NodeType.BENEFIT),
            Node(id="disc", type=NodeType.DISCOUNT),
            Node(id="cf", type=NodeType.CASHFLOW),
            Node(id="out", type=NodeType.OUTPUT)
        ],
        edges=[
            Edge(id="e1", source="in", target="mort"),
            Edge(id="e2", source="in", target="ben"),
            Edge(id="e3", source="in", target="disc"),
            Edge(id="e4", source="mort", target="surv"),
            Edge(id="e5", source="in", target="surv"), # Pass age
            Edge(id="e6", source="surv", target="cf"),
            Edge(id="e7", source="ben", target="cf"),
            Edge(id="e8", source="cf", target="out"),
            Edge(id="e9", source="disc", target="out"),
            Edge(id="e10", source="surv", target="disc") # to determine vector length based on tpx_vector length
        ]
    )
    
    BlueprintValidator.validate(bp)
    
    executor = BlueprintExecutor(bp)
    result = executor.run()
    
    assert "bel" in result, "Output context should contain 'bel'."
    assert "npv" in result, "Output context should contain 'npv'."
    
    blueprint_nsp = result["bel"]
    
    # Should match to a very high degree of precision (1e-10)
    assert np.isclose(blueprint_nsp, expected_nsp, rtol=1e-10), f"Blueprint: {blueprint_nsp} != Deterministic: {expected_nsp}"
