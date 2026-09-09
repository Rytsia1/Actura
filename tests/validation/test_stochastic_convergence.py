import pytest
import numpy as np

from actuary_engine.domain.pricing.insurance import InsurancePricer
from actuary_engine.models.assumptions import InterestAssumption
from actuary_engine.domain.tables.commutation import CommutationFunctions
from actuary_engine.models.contracts import PolicyContract, ProductType

from actuary_engine.domain.stochastic.monte_carlo import StochasticValuationEngine
from actuary_engine.domain.stochastic.esg import VasicekESG, VasicekParams
from tests.conftest import DISCOUNT_RATE

@pytest.fixture
def deterministic_bel_benchmark(static_mortality_table):
    """
    Grabs the deterministic EPV from the validated Whole Life test.
    This is the "ground truth" we established in the 'Make it right' phase.
    """
    interest = InterestAssumption(annual_rate=DISCOUNT_RATE)
    comm = CommutationFunctions(table=static_mortality_table, interest=interest)
    pricer = InsurancePricer(commutation=comm)
    
    contract = PolicyContract(
        issue_age=30,
        product_type=ProductType.WHOLE_LIFE,
        sum_assured=1.0
    )
    return pricer.price_contract(contract)

def test_stochastic_bel_converges_to_deterministic(static_mortality_table, deterministic_bel_benchmark):
    """
    Test: The average BEL across 10,000 stochastic paths (with different seeds)
    must converge to the deterministic analytical EPV within Monte Carlo standard error bounds.
    """
    params = VasicekParams(
        r0=DISCOUNT_RATE,
        kappa=0.001,
        theta=DISCOUNT_RATE,
        sigma=0.0
    )
    esg = VasicekESG(params=params)
    
    contract = PolicyContract(
        issue_age=30,
        product_type=ProductType.WHOLE_LIFE,
        sum_assured=1.0
    )
    
    engine = StochasticValuationEngine(table=static_mortality_table, esg=esg)
    
    # Run with Seed A
    res_a = engine.run_simulation(contract, 0.0, n_scenarios=10000, seed=42, compounding="discrete")
    bel_a = res_a.mean_bel
    
    # Run with Seed B
    res_b = engine.run_simulation(contract, 0.0, n_scenarios=10000, seed=123, compounding="discrete")
    bel_b = res_b.mean_bel
    
    # Run with Seed C
    res_c = engine.run_simulation(contract, 0.0, n_scenarios=10000, seed=999, compounding="discrete")
    bel_c = res_c.mean_bel
    
    expected = deterministic_bel_benchmark
    
    assert np.isclose(bel_a, expected, rtol=2e-2), \
        f"Seed 42: BEL ({bel_a}) failed to converge to deterministic ({expected})."
    
    assert np.isclose(bel_b, expected, rtol=2e-2), \
        f"Seed 123: BEL ({bel_b}) failed to converge to deterministic ({expected})."
    
    assert np.isclose(bel_c, expected, rtol=2e-2), \
        f"Seed 999: BEL ({bel_c}) failed to converge to deterministic ({expected})."
