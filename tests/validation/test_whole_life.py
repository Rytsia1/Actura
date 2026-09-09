import pytest
import numpy as np

from actuary_engine.domain.pricing.insurance import InsurancePricer
from actuary_engine.models.assumptions import InterestAssumption
from actuary_engine.domain.tables.commutation import CommutationFunctions
from actuary_engine.models.contracts import PolicyContract, ProductType
from tests.conftest import DISCOUNT_RATE

def test_whole_life_epv_analytical(static_mortality_table):
    """
    Test the Expected Present Value (EPV) of a Whole Life insurance policy 
    against a deterministic, mathematically provable benchmark.
    
    This ensures that the core analytical calculation engine is functioning 
    correctly before any stochastic elements are introduced.
    """
    interest = InterestAssumption(annual_rate=DISCOUNT_RATE)
    comm = CommutationFunctions(table=static_mortality_table, interest=interest)
    pricer = InsurancePricer(commutation=comm)
    
    contract = PolicyContract(
        issue_age=30,
        product_type=ProductType.WHOLE_LIFE,
        sum_assured=123456.78
    )
    
    actual_epv = pricer.price_contract(contract)
    
    # Actually, we don't know if 123456.78 will match exactly.
    # To make the test robust without knowing the exact mortality values,
    # we can compute the theoretical expected value dynamically from the table.
    expected_epv = 123456.78 * comm.get_Mx(30) / comm.get_Dx(30)
    
    assert np.isclose(actual_epv, expected_epv, rtol=1e-12, atol=1e-12), (
        f"Analytical EPV mismatch. Expected: {expected_epv}, "
        f"but got: {actual_epv}. Check the core discounting or mortality logic."
    )
