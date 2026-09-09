import pytest
import numpy as np
from pydantic import ValidationError

from actuary_engine.domain.pricing.insurance import InsurancePricer
from actuary_engine.models.assumptions import InterestAssumption
from actuary_engine.domain.tables.commutation import CommutationFunctions
from actuary_engine.models.contracts import PolicyContract, ProductType
from tests.conftest import DISCOUNT_RATE

def test_term_insurance_one_year(static_mortality_table):
    """
    Cashflow Parity: For a pure premium, EPV(Term, n=1) == v * q_x (within 1e-12)
    """
    interest = InterestAssumption(annual_rate=DISCOUNT_RATE)
    comm = CommutationFunctions(table=static_mortality_table, interest=interest)
    pricer = InsurancePricer(commutation=comm)
    
    age = 30
    contract = PolicyContract(
        issue_age=age,
        product_type=ProductType.TERM,
        term=1,
        sum_assured=1.0
    )
    
    actual_epv = pricer.price_contract(contract)
    
    # Expected: v * q_x
    v = interest.discount_factor
    qx = static_mortality_table.get_qx(age)
    expected_epv = v * qx
    
    assert np.isclose(actual_epv, expected_epv, rtol=1e-12, atol=1e-12), (
        f"1-Year Term EPV mismatch. Expected {expected_epv}, got {actual_epv}"
    )

def test_term_insurance_boundary(static_mortality_table):
    """
    Table Boundary: EPV(Term, n=omega - age + 1) == EPV(Whole Life)
    """
    interest = InterestAssumption(annual_rate=DISCOUNT_RATE)
    comm = CommutationFunctions(table=static_mortality_table, interest=interest)
    pricer = InsurancePricer(commutation=comm)
    
    age = 30
    # max_age in the table is omega. Term up to max_age means term = max_age - age
    # The codebase restricts issue_age + term <= max_age, so term = 80 for age 30, max_age 110.
    term_n = static_mortality_table.max_age - age
    
    term_contract = PolicyContract(
        issue_age=age,
        product_type=ProductType.TERM,
        term=term_n,
        sum_assured=1.0
    )
    
    wl_contract = PolicyContract(
        issue_age=age,
        product_type=ProductType.WHOLE_LIFE,
        sum_assured=1.0
    )
    
    term_epv = pricer.price_contract(term_contract)
    wl_epv = pricer.price_contract(wl_contract)
    
    # The Term policy (n=80) misses the final year of death (age 110 to 111) which Whole Life covers.
    # We mathematically add the missing final year (C_omega / D_x) to match exactly.
    missing_final_year = comm.get_Cx(static_mortality_table.max_age) / comm.get_Dx(age)
    
    assert np.isclose(term_epv + missing_final_year, wl_epv, rtol=1e-12, atol=1e-12), (
        f"Boundary mismatch. Term EPV: {term_epv}, WL EPV: {wl_epv}"
    )

def test_term_insurance_non_negativity(static_mortality_table):
    """
    Non-Negativity: EPV for Term <= EPV for Whole Life (ensures no arbitrage in code)
    """
    interest = InterestAssumption(annual_rate=DISCOUNT_RATE)
    comm = CommutationFunctions(table=static_mortality_table, interest=interest)
    pricer = InsurancePricer(commutation=comm)
    
    age = 30
    term_contract = PolicyContract(
        issue_age=age,
        product_type=ProductType.TERM,
        term=10,
        sum_assured=1.0
    )
    wl_contract = PolicyContract(
        issue_age=age,
        product_type=ProductType.WHOLE_LIFE,
        sum_assured=1.0
    )
    
    term_epv = pricer.price_contract(term_contract)
    wl_epv = pricer.price_contract(wl_contract)
    
    assert term_epv <= wl_epv, "Term EPV should not exceed Whole Life EPV."
    assert term_epv > 0, "Term EPV must be positive."

def test_term_insurance_epv_analytical_loop(static_mortality_table):
    """
    Compute the expected EPV inside the test using a pure-Python/NumPy loop that mirrors the formula.
    This provides an internal analytical benchmark independent of the engine's commutation implementation.
    """
    interest_rate = DISCOUNT_RATE
    age = 30
    term_length = 10
    benefit = 100_000.0
    v = 1.0 / (1.0 + interest_rate)
    
    expected_epv = 0.0
    tPx = 1.0
    for t in range(term_length):
        qx_t = static_mortality_table.get_qx(age + t)
        expected_epv += (v ** (t+1)) * tPx * qx_t
        tPx *= (1.0 - qx_t)
        
    expected_epv *= benefit
    
    interest = InterestAssumption(annual_rate=interest_rate)
    comm = CommutationFunctions(table=static_mortality_table, interest=interest)
    pricer = InsurancePricer(commutation=comm)
    
    contract = PolicyContract(
        issue_age=age,
        product_type=ProductType.TERM,
        term=term_length,
        sum_assured=benefit
    )
    
    actual_epv = pricer.price_contract(contract)
    
    assert np.isclose(actual_epv, expected_epv, rtol=1e-12, atol=1e-12), \
        f"Term EPV mismatch: engine={actual_epv:.6f}, analytical={expected_epv:.6f}"

def test_term_zero_error():
    """
    Term=0 should error in the contract layer due to Pydantic constraints.
    """
    with pytest.raises(ValidationError):
        PolicyContract(
            issue_age=30,
            product_type=ProductType.TERM,
            term=0,
            sum_assured=1.0
        )

def test_term_max_age(static_mortality_table):
    """
    Age=max_age should raise a ValueError when validated against the mortality table 
    because issue_age + term > omega.
    """
    age = static_mortality_table.max_age
    contract = PolicyContract(
        issue_age=age,
        product_type=ProductType.TERM,
        term=1,
        sum_assured=1.0
    )
    with pytest.raises(ValueError, match="exceeds mortality table maximum age"):
        contract.validate_against_table(static_mortality_table)
