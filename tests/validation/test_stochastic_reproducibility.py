import pytest
import numpy as np

from actuary_engine.domain.stochastic.monte_carlo import StochasticValuationEngine
from actuary_engine.domain.stochastic.esg import VasicekESG, VasicekParams
from actuary_engine.models.contracts import PolicyContract, ProductType
from tests.conftest import DISCOUNT_RATE

@pytest.fixture
def stochastic_engine_setup(static_mortality_table):
    params = VasicekParams(
        r0=DISCOUNT_RATE,
        kappa=0.15,
        theta=DISCOUNT_RATE,
        sigma=0.02
    )
    esg = VasicekESG(params=params)
    contract = PolicyContract(
        issue_age=30,
        product_type=ProductType.WHOLE_LIFE,
        sum_assured=1.0
    )
    return contract, static_mortality_table, esg

def test_stochastic_reproducibility_seed_42(stochastic_engine_setup):
    """
    Test: Seed=42 must yield identical BEL, VaR(95%), and CTE(95%) across two runs.
    This validates that the random number generator, loops, and reduction logic are deterministic.
    """
    contract, mortality, esg = stochastic_engine_setup
    FIXED_SEED = 42
    
    # Run 1
    engine_1 = StochasticValuationEngine(table=mortality, esg=esg)
    result_1 = engine_1.run_simulation(contract, 0.0, n_scenarios=10000, seed=FIXED_SEED, compounding="discrete")
    
    # Run 2
    engine_2 = StochasticValuationEngine(table=mortality, esg=esg)
    result_2 = engine_2.run_simulation(contract, 0.0, n_scenarios=10000, seed=FIXED_SEED, compounding="discrete")
    
    # 1. Assert Aggregates (BEL)
    assert np.isclose(result_1.mean_bel, result_2.mean_bel, rtol=0, atol=0), \
        f"BEL differs: {result_1.mean_bel} vs {result_2.mean_bel}"
    
    # 2. Assert VaR
    assert np.isclose(result_1.var_95, result_2.var_95, rtol=0, atol=0), \
        f"VaR(95%) differs: {result_1.var_95} vs {result_2.var_95}"
    
    # 3. Assert CTE (CVaR)
    assert np.isclose(result_1.cvar_95, result_2.cvar_95, rtol=0, atol=0), \
        f"CTE(95%) differs: {result_1.cvar_95} vs {result_2.cvar_95}"
    
    # 4. Assert the full path arrays are bitwise identical
    assert np.array_equal(result_1.scenario_bel, result_2.scenario_bel), \
        "The underlying random path arrays are different."
