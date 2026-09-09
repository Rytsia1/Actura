"""
Tests verifying that the MortalityTable is the sole source of truth for maximum age and term boundaries.

Ensures that contracts are dynamically validated against the active MortalityTable (omega, min_age, max_age)
across all pricing calculators, reserve engines, stochastic simulations, IFRS 17, sensitivity analysis,
portfolio batch valuation, and FastAPI endpoints.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from actuary_engine.main import app
from actuary_engine.models.assumptions import InterestAssumption
from actuary_engine.models.contracts import PolicyContract, ProductType
from actuary_engine.domain.pricing.insurance import InsurancePricer
from actuary_engine.domain.pricing.premium import LevelPremiumCalculator
from actuary_engine.projections.cash_flow import CashFlowProjector
from actuary_engine.domain.stochastic.esg import VasicekESG, VasicekParams
from actuary_engine.domain.stochastic.monte_carlo import StochasticValuationEngine
from actuary_engine.domain.tables.commutation import CommutationFunctions
from actuary_engine.domain.tables.mortality_table import MortalityTable
from actuary_engine.domain.tables.registry import table_registry
from actuary_engine.valuation.gpv import GrossPremiumValuation
from actuary_engine.valuation.ifrs17 import IFRS17Engine
from actuary_engine.valuation.portfolio import PortfolioValuationEngine
from actuary_engine.valuation.reserves import ReserveCalculator
from actuary_engine.valuation.sensitivity import SensitivityEngine

client = TestClient(app)


@pytest.fixture
def soa_table() -> MortalityTable:
    return table_registry.get_table("soa_ilt")


@pytest.fixture
def custom_short_table() -> MortalityTable:
    """A mortality table that ends at age 90 (omega=90)."""
    ages = np.arange(20, 91, dtype=np.int64)
    qx = np.linspace(0.001, 1.0, len(ages))
    qx[-1] = 1.0
    return MortalityTable(ages=ages, qx=qx, name="ShortTable90")


@pytest.fixture
def custom_super_table() -> MortalityTable:
    """A mortality table that extends to age 125 (omega=125)."""
    ages = np.arange(0, 126, dtype=np.int64)
    qx = np.linspace(0.0005, 1.0, len(ages))
    qx[-1] = 1.0
    return MortalityTable(ages=ages, qx=qx, name="SuperTable125")


# ────────────────────────────────────────────────────────────
# 1. Contract vs Mortality Table Direct Boundary Validation
# ────────────────────────────────────────────────────────────

class TestContractMortalityTableValidation:
    """Tests for PolicyContract.validate_against_table and MortalityTable.validate_contract."""

    def test_term_exceeding_table_omega_raises(self, soa_table: MortalityTable) -> None:
        """SOA ILT max_age is 110. Issue age 100 + term 20 = 120 > 110 must raise ValueError."""
        contract = PolicyContract(
            product_type=ProductType.TERM,
            issue_age=100,
            term=20,
            sum_assured=100_000,
        )
        with pytest.raises(ValueError, match="exceeds mortality table maximum age"):
            contract.validate_against_table(soa_table)

    def test_term_within_table_omega_passes(self, soa_table: MortalityTable) -> None:
        """Issue age 100 + term 10 = 110 == max_age must pass."""
        contract = PolicyContract(
            product_type=ProductType.TERM,
            issue_age=100,
            term=10,
            sum_assured=100_000,
        )
        contract.validate_against_table(soa_table)
        soa_table.validate_contract(contract)

    def test_issue_age_exceeding_table_max_raises(self, soa_table: MortalityTable) -> None:
        """Issue age 115 > 110 must raise ValueError."""
        contract = PolicyContract(
            product_type=ProductType.WHOLE_LIFE,
            issue_age=115,
            sum_assured=100_000,
        )
        with pytest.raises(ValueError, match="exceeds the mortality table maximum age"):
            contract.validate_against_table(soa_table)

    def test_custom_short_table_boundary(self, custom_short_table: MortalityTable) -> None:
        """Short table ends at 90. Issue age 80 + term 15 = 95 must fail; term 10 = 90 must pass."""
        contract_invalid = PolicyContract(
            product_type=ProductType.ENDOWMENT,
            issue_age=80,
            term=15,
            sum_assured=50_000,
        )
        with pytest.raises(ValueError, match="exceeds mortality table maximum age"):
            contract_invalid.validate_against_table(custom_short_table)

        contract_valid = PolicyContract(
            product_type=ProductType.ENDOWMENT,
            issue_age=80,
            term=10,
            sum_assured=50_000,
        )
        contract_valid.validate_against_table(custom_short_table)

    def test_custom_super_table_allows_centenarians(self, custom_super_table: MortalityTable) -> None:
        """Super table goes to 125. Issue age 110 + term 10 = 120 must pass."""
        contract = PolicyContract(
            product_type=ProductType.TERM,
            issue_age=110,
            term=10,
            sum_assured=50_000,
        )
        contract.validate_against_table(custom_super_table)

    def test_premium_term_exceeding_table_horizon_raises(self, soa_table: MortalityTable) -> None:
        """For whole life at age 105, premium paying term of 10 years exceeds max_age (105+10 = 115 > 110)."""
        contract = PolicyContract(
            product_type=ProductType.WHOLE_LIFE,
            issue_age=105,
            premium_paying_term=10,
            sum_assured=100_000,
        )
        with pytest.raises(ValueError, match="exceeds maximum allowable duration"):
            contract.validate_against_table(soa_table)


# ────────────────────────────────────────────────────────────
# 2. Valuation & Pricing Engine Boundary Enforcement
# ────────────────────────────────────────────────────────────

class TestEnginesEnforceTableLimits:
    """Verify that all computation engines reject contracts exceeding table limits."""

    def test_insurance_pricer_rejects_exceeding_term(self, soa_table: MortalityTable) -> None:
        comm = CommutationFunctions(soa_table, InterestAssumption(annual_rate=0.05))
        pricer = InsurancePricer(comm)
        contract = PolicyContract(
            product_type=ProductType.TERM,
            issue_age=100,
            term=20,
            sum_assured=100_000,
        )
        with pytest.raises(ValueError, match="exceeds mortality table maximum age"):
            pricer.price_contract(contract)

    def test_level_premium_calculator_rejects_exceeding_term(self, soa_table: MortalityTable) -> None:
        comm = CommutationFunctions(soa_table, InterestAssumption(annual_rate=0.05))
        calc = LevelPremiumCalculator(comm)
        contract = PolicyContract(
            product_type=ProductType.ENDOWMENT,
            issue_age=95,
            term=25,
            sum_assured=100_000,
        )
        with pytest.raises(ValueError, match="exceeds mortality table maximum age"):
            calc.price_contract(contract)

    def test_reserve_calculator_rejects_exceeding_term(self, soa_table: MortalityTable) -> None:
        comm = CommutationFunctions(soa_table, InterestAssumption(annual_rate=0.05))
        res_calc = ReserveCalculator(comm)
        contract = PolicyContract(
            product_type=ProductType.TERM,
            issue_age=100,
            term=20,
            sum_assured=100_000,
        )
        with pytest.raises(ValueError, match="exceeds mortality table maximum age"):
            res_calc.reserve_profile(contract, annual_premium=5000.0)

    def test_gpv_engine_rejects_exceeding_term(self, soa_table: MortalityTable) -> None:
        gpv = GrossPremiumValuation(
            table=soa_table,
            interest=InterestAssumption(annual_rate=0.05),
        )
        contract = PolicyContract(
            product_type=ProductType.TERM,
            issue_age=105,
            term=15,
            sum_assured=100_000,
        )
        with pytest.raises(ValueError, match="exceeds mortality table maximum age"):
            gpv.project(contract, gross_premium=6000.0)

    def test_cash_flow_projector_rejects_exceeding_horizon(self, soa_table: MortalityTable) -> None:
        proj = CashFlowProjector(soa_table, InterestAssumption(annual_rate=0.05))
        contract = PolicyContract(
            product_type=ProductType.WHOLE_LIFE,
            issue_age=100,
            sum_assured=100_000,
        )
        # Attempting to project 20 years from age 100 on table with omega=110
        with pytest.raises(ValueError, match="exceeds mortality table maximum age"):
            proj.project(contract, annual_premium=5000.0, projection_years=20)

    def test_stochastic_engine_rejects_exceeding_term(self, soa_table: MortalityTable) -> None:
        esg = VasicekESG(VasicekParams(r0=0.05, kappa=0.2, theta=0.05, sigma=0.015))
        stoch = StochasticValuationEngine(table=soa_table, esg=esg)
        contract = PolicyContract(
            product_type=ProductType.TERM,
            issue_age=100,
            term=25,
            sum_assured=100_000,
        )
        with pytest.raises(ValueError, match="exceeds mortality table maximum age"):
            stoch.run_simulation(contract, gross_premium=5000.0, n_scenarios=50)

    def test_ifrs17_engine_rejects_exceeding_term(self, soa_table: MortalityTable) -> None:
        engine = IFRS17Engine(table=soa_table, interest=InterestAssumption(annual_rate=0.05))
        contract = PolicyContract(
            product_type=ProductType.ENDOWMENT,
            issue_age=100,
            term=20,
            sum_assured=100_000,
        )
        with pytest.raises(ValueError, match="exceeds mortality table maximum age"):
            engine.evaluate(contract)

    def test_sensitivity_engine_rejects_exceeding_term(self, soa_table: MortalityTable) -> None:
        engine = SensitivityEngine(table=soa_table, interest=InterestAssumption(annual_rate=0.05))
        contract = PolicyContract(
            product_type=ProductType.TERM,
            issue_age=102,
            term=15,
            sum_assured=100_000,
        )
        with pytest.raises(ValueError, match="exceeds mortality table maximum age"):
            engine.run_tornado_analysis(contract)

    def test_portfolio_engine_rejects_violating_row(self, soa_table: MortalityTable) -> None:
        engine = PortfolioValuationEngine(table=soa_table)
        csv_data = (
            "policy_id,issue_age,term_years,sum_assured,gross_premium,product_type,policy_duration_years\n"
            "P1,30,20,500000,1200,term,0\n"
            "P2,105,15,500000,1200,term,0\n"  # 105 + 15 = 120 > 110
        )
        with pytest.raises(ValueError, match="Policy 'P2'.*exceeds mortality table maximum age"):
            engine.load_portfolio_df(csv_data)


# ────────────────────────────────────────────────────────────
# 3. API Endpoints Return 400 Bad Request
# ────────────────────────────────────────────────────────────

class TestAPIEndpointsRejectTableViolations:
    """Verify HTTP 400 response from all valuation endpoints when table limits are exceeded."""

    def test_deterministic_api_rejects_invalid_age(self) -> None:
        payload = {
            "product_type": "term",
            "issue_age": 100,
            "term": 25,  # 100 + 25 = 125 > 110
            "sum_assured": 1_000_000,
            "table_id": "soa_ilt",
        }
        res = client.post("/api/v1/valuation/deterministic", json=payload)
        assert res.status_code == 400
        assert "exceeds mortality table maximum age" in res.json()["detail"]

    def test_stochastic_async_api_rejects_invalid_age(self) -> None:
        payload = {
            "product_type": "endowment",
            "issue_age": 100,
            "term": 20,  # 100 + 20 = 120 > 110
            "sum_assured": 500_000,
            "table_id": "soa_ilt",
        }
        res = client.post("/api/v1/valuation/stochastic/async", json=payload)
        assert res.status_code == 400
        assert "exceeds mortality table maximum age" in res.json()["detail"]

    def test_ifrs17_api_rejects_invalid_age(self) -> None:
        payload = {
            "product_type": "endowment",
            "issue_age": 95,
            "term": 30,  # 95 + 30 = 125 > 110
            "sum_assured": 500_000,
            "table_id": "soa_ilt",
        }
        res = client.post("/api/v1/valuation/ifrs17", json=payload)
        assert res.status_code == 400
        assert "exceeds mortality table maximum age" in res.json()["detail"]

    def test_tornado_api_rejects_invalid_age(self) -> None:
        payload = {
            "product_type": "term",
            "issue_age": 102,
            "term": 15,  # 102 + 15 = 117 > 110
            "sum_assured": 500_000,
            "table_id": "soa_ilt",
        }
        res = client.post("/api/v1/valuation/sensitivity/tornado", json=payload)
        assert res.status_code == 400
        assert "exceeds mortality table maximum age" in res.json()["detail"]

    def test_stress_test_sliders_api_rejects_invalid_age(self) -> None:
        payload = {
            "product_type": "term",
            "issue_age": 105,
            "term": 10,  # 105 + 10 = 115 > 110
            "sum_assured": 500_000,
            "table_id": "soa_ilt",
        }
        res = client.post("/api/v1/valuation/stress-test", json=payload)
        assert res.status_code == 400
        assert "exceeds mortality table maximum age" in res.json()["detail"]

    def test_portfolio_json_api_rejects_invalid_row(self) -> None:
        payload = {
            "policies": [
                {
                    "policy_id": "OK-1",
                    "issue_age": 30,
                    "term_years": 20,
                    "sum_assured": 100_000,
                    "gross_premium": 500,
                    "product_type": "term",
                },
                {
                    "policy_id": "BAD-1",
                    "issue_age": 100,
                    "term_years": 20,  # 100 + 20 = 120 > 110
                    "sum_assured": 100_000,
                    "gross_premium": 5000,
                    "product_type": "term",
                },
            ],
            "table_id": "soa_ilt",
        }
        res = client.post("/api/v1/valuation/portfolio", json=payload)
        assert res.status_code == 400
        assert "BAD-1" in res.json()["detail"]

    def test_whole_life_limited_pay_boundary_exceeded_raises(self, soa_table: MortalityTable) -> None:
        """Issue age 100 with premium_paying_term=40 on table ending at 110 (10 years available) must be rejected."""
        contract = PolicyContract(
            product_type=ProductType.WHOLE_LIFE,
            issue_age=100,
            premium_paying_term=40,
            sum_assured=100_000,
        )
        with pytest.raises(ValueError, match="Premium paying term \\(40\\) exceeds maximum allowable duration \\(10\\)"):
            contract.validate_against_table(soa_table)

        # Commutation / Pricing level
        comm = CommutationFunctions(soa_table, InterestAssumption(annual_rate=0.05))
        calc = LevelPremiumCalculator(comm)
        with pytest.raises(ValueError, match="Age x \\+ n = 140 exceeds table maximum 110"):
            calc.annual_premium_whole_life(x=100, face=100_000, premium_term=40)

    def test_whole_life_limited_pay_boundary_exact_passes(self, soa_table: MortalityTable) -> None:
        """Issue age 100 with premium_paying_term=10 reaches exact limiting age 110 and calculates valid premium."""
        contract = PolicyContract(
            product_type=ProductType.WHOLE_LIFE,
            issue_age=100,
            premium_paying_term=10,
            sum_assured=100_000,
        )
        contract.validate_against_table(soa_table)

        comm = CommutationFunctions(soa_table, InterestAssumption(annual_rate=0.05))
        calc = LevelPremiumCalculator(comm)
        res = calc.annual_premium_whole_life(x=100, face=100_000, premium_term=10)
        assert res.annual_premium > 0
        assert res.premium_paying_term == 10
        assert res.term is None

