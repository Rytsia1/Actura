"""
Shared test fixtures for the actuarial engine test suite.

Provides pre-built instances of MortalityTable, CommutationFunctions,
and related objects at standard test parameters (SOA ILT, 5% interest)
for use across all test modules.
"""

import pytest
import numpy as np

from actuary_engine.models.assumptions import InterestAssumption
from actuary_engine.domain.tables.mortality_table import MortalityTable
from actuary_engine.domain.tables.commutation import CommutationFunctions
from actuary_engine.domain.pricing.insurance import InsurancePricer
from actuary_engine.domain.pricing.annuity import AnnuityPricer
from actuary_engine.domain.pricing.premium import LevelPremiumCalculator
from actuary_engine.domain.curves.survival import SurvivalCurve
from actuary_engine.projections.cash_flow import CashFlowProjector

# Constant for fixed discount rate (added in validation test phase)
DISCOUNT_RATE = 0.05

# Stochastic simulation configuration
STOCHASTIC_CONFIG = {
    "NUM_PATHS": 10000,
    "RANDOM_SEED": 42
}

@pytest.fixture(scope="session")
def soa_table() -> MortalityTable:
    """SOA Illustrative Life Table loaded once per test session."""
    return MortalityTable.from_soa_ilt()

@pytest.fixture(scope="session")
def static_mortality_table() -> MortalityTable:
    """
    Fixture that loads a static mortality table for deterministic testing.
    This provides a consistent, mathematically provable baseline for benchmark validation.
    """
    return MortalityTable.from_soa_ilt()

@pytest.fixture(scope="session")
def interest_5pct() -> InterestAssumption:
    """5% annual effective interest rate."""
    return InterestAssumption(annual_rate=0.05)

@pytest.fixture(scope="session")
def commutation_5pct(soa_table: MortalityTable, interest_5pct: InterestAssumption) -> CommutationFunctions:
    """Commutation functions at 5% on SOA ILT."""
    return CommutationFunctions(soa_table, interest_5pct)

@pytest.fixture(scope="session")
def insurance_pricer(commutation_5pct: CommutationFunctions) -> InsurancePricer:
    """Insurance pricer at 5% on SOA ILT."""
    return InsurancePricer(commutation_5pct)

@pytest.fixture(scope="session")
def annuity_pricer(commutation_5pct: CommutationFunctions) -> AnnuityPricer:
    """Annuity pricer at 5% on SOA ILT."""
    return AnnuityPricer(commutation_5pct)

@pytest.fixture(scope="session")
def premium_calculator(commutation_5pct: CommutationFunctions) -> LevelPremiumCalculator:
    """Level premium calculator at 5% on SOA ILT."""
    return LevelPremiumCalculator(commutation_5pct)

@pytest.fixture(scope="session")
def cf_projector(soa_table: MortalityTable, interest_5pct: InterestAssumption) -> CashFlowProjector:
    """Cash flow projector at 5% on SOA ILT."""
    return CashFlowProjector(soa_table, interest_5pct)

@pytest.fixture(scope="session")
def survival_age30(soa_table: MortalityTable) -> SurvivalCurve:
    """Survival curve for entry age 30 on SOA ILT."""
    return SurvivalCurve(soa_table, entry_age=30)

# ────────────────────────────────────────────────────────────
# Small synthetic table for unit tests (deterministic, easy to verify)
# ────────────────────────────────────────────────────────────

@pytest.fixture
def tiny_table() -> MortalityTable:
    """A tiny 5-age mortality table for deterministic unit tests.

    Ages 0-4, qx = [0.1, 0.2, 0.3, 0.5, 1.0]
    Easy to hand-verify all derived quantities.
    """
    qx = [0.1, 0.2, 0.3, 0.5, 1.0]
    return MortalityTable.from_qx_array(qx, start_age=0, name="tiny_test", radix=1000)

@pytest.fixture
def tiny_commutation(tiny_table: MortalityTable) -> CommutationFunctions:
    """Commutation functions on the tiny table at 10% interest."""
    interest = InterestAssumption(annual_rate=0.10)
    return CommutationFunctions(tiny_table, interest)

@pytest.fixture(scope="session")
def stochastic_config():
    """
    Fixture providing consistent parameters for stochastic tests.
    Ensures deterministic reproducibility across Monte Carlo simulations.
    """
    return STOCHASTIC_CONFIG

# --- Authentication Mocking ---
from actuary_engine.main import app
from actuary_engine.api.dependencies import get_current_user

def override_get_current_user():
    return {
        "id": "test-admin",
        "username": "admin",
        "role": "Admin",
        "organization_id": "default-org"
    }

app.dependency_overrides[get_current_user] = override_get_current_user

@pytest.fixture(autouse=True)
def default_auth_mock():
    if get_current_user not in app.dependency_overrides:
        app.dependency_overrides[get_current_user] = override_get_current_user
    yield
