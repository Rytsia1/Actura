"""
Test suite for Stress Testing & Tornado Sensitivity Analysis Engine.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from actuary_engine.main import app
from actuary_engine.models.assumptions import (
    ExpenseAssumption,
    InterestAssumption,
    LapseAssumption,
)
from actuary_engine.models.contracts import PolicyContract, ProductType
from actuary_engine.domain.tables.registry import table_registry
from actuary_engine.valuation.sensitivity import (
    CombinedScenarioResult,
    SensitivityBaselineMetrics,
    SensitivityEngine,
    SensitivityReport,
    TornadoItem,
)


@pytest.fixture(scope="session")
def sensitivity_setup() -> tuple[SensitivityEngine, PolicyContract]:
    table = table_registry.get_table("soa_ilt")
    interest = InterestAssumption(annual_rate=0.05)
    expense = ExpenseAssumption(
        percent_of_premium_first=0.30,
        percent_of_premium_renewal=0.05,
        per_policy_first=150.0,
        per_policy_renewal=15.0,
    )
    lapse = LapseAssumption(
        duration_rates=[0.08, 0.05, 0.04, 0.03],
        flat_annual_rate=0.02,
    )
    engine = SensitivityEngine(table, interest, expense, lapse)
    contract = PolicyContract(
        product_type=ProductType.ENDOWMENT,
        issue_age=35,
        term=20,
        sum_assured=1_000_000,
    )
    return engine, contract


class TestSensitivityBaselines:
    """Test duration, convexity, DV01, and direction of single-factor shocks."""

    def test_interest_rate_sensitivity_direction(
        self, sensitivity_setup: tuple[SensitivityEngine, PolicyContract]
    ) -> None:
        engine, contract = sensitivity_setup

        base_res = engine.evaluate_point(contract)
        res_plus_100 = engine.evaluate_point(contract, interest_shift=0.01)
        res_minus_100 = engine.evaluate_point(contract, interest_shift=-0.01)

        # Higher interest rate discounts benefit outgo more heavily -> lower PV of benefits
        assert res_plus_100["pvfb"] < base_res["pvfb"]
        assert res_minus_100["pvfb"] > base_res["pvfb"]

    def test_mortality_shock_increases_term_liability(self) -> None:
        table = table_registry.get_table("soa_ilt")
        interest = InterestAssumption(annual_rate=0.05)
        engine = SensitivityEngine(table, interest)

        term_contract = PolicyContract(
            product_type=ProductType.TERM,
            issue_age=40,
            term=20,
            sum_assured=500_000,
        )

        base_res = engine.evaluate_point(term_contract)
        shocked_res = engine.evaluate_point(term_contract, mortality_mult=1.20)

        # +20% mortality increases claim outgo for pure term insurance
        assert shocked_res["pvfb"] > base_res["pvfb"]

    def test_baseline_duration_and_dv01(
        self, sensitivity_setup: tuple[SensitivityEngine, PolicyContract]
    ) -> None:
        engine, contract = sensitivity_setup
        report = engine.run_tornado_analysis(contract)

        assert report.baseline.effective_duration > 0.0
        assert report.baseline.dv01 > 0.0
        assert isinstance(report.baseline.effective_convexity, float)


class TestTornadoAnalysis:
    """Test Tornado chart risk factor ranking and swing calculations."""

    def test_tornado_items_sorted_by_swing(
        self, sensitivity_setup: tuple[SensitivityEngine, PolicyContract]
    ) -> None:
        engine, contract = sensitivity_setup
        report = engine.run_tornado_analysis(contract)

        assert len(report.tornado_items) >= 6

        # Invariant: Tornado items must be sorted in strictly descending order of absolute swing
        swings = [item.swing for item in report.tornado_items]
        assert swings == sorted(swings, reverse=True)

    def test_mass_surrender_shock_execution(
        self, sensitivity_setup: tuple[SensitivityEngine, PolicyContract]
    ) -> None:
        engine, contract = sensitivity_setup
        report = engine.run_tornado_analysis(contract)

        mass_lapse_items = [i for i in report.tornado_items if "Mass Surrender" in i.risk_factor]
        assert len(mass_lapse_items) == 1
        assert mass_lapse_items[0].category == "CATASTROPHE"


class TestCombinedScenarios:
    """Test compound multi-factor stress scenario packages."""

    def test_compound_scenarios_execution(
        self, sensitivity_setup: tuple[SensitivityEngine, PolicyContract]
    ) -> None:
        engine, contract = sensitivity_setup
        scenarios = engine.run_combined_scenarios(contract)

        assert len(scenarios) == 5
        scenario_ids = [s.scenario_id for s in scenarios]
        assert "stagflation_crisis" in scenario_ids
        assert "pandemic_surge" in scenario_ids
        assert "regulator_standard_stress" in scenario_ids
        assert "economic_boom" in scenario_ids


class TestSensitivityAPI:
    """Test FastAPI /api/v1/valuation/sensitivity/tornado endpoint."""

    def test_tornado_endpoint_success(self) -> None:
        client = TestClient(app)
        payload = {
            "product_type": "endowment",
            "issue_age": 30,
            "term": 20,
            "sum_assured": 1000000.0,
            "interest_rate": 0.05,
            "table_id": "soa_ilt",
        }

        response = client.post("/api/v1/valuation/sensitivity/tornado", json=payload)
        assert response.status_code == 200
        data = response.json()

        assert data["table_id"] == "soa_ilt"
        assert "effective_duration" in data["baseline"]
        assert len(data["tornado_items"]) >= 6
        assert len(data["combined_scenarios"]) == 5

    def test_tornado_endpoint_not_found_table(self) -> None:
        client = TestClient(app)
        payload = {
            "table_id": "non_existent_table_12345",
            "product_type": "endowment",
            "issue_age": 30,
            "term": 20,
            "sum_assured": 1000000.0,
        }
        response = client.post("/api/v1/valuation/sensitivity/tornado", json=payload)
        assert response.status_code == 404

    def test_stress_test_sliders_endpoint(self) -> None:
        """Test the real-time stress testing sliders endpoint."""
        client = TestClient(app)
        payload = {
            "product_type": "endowment",
            "issue_age": 30,
            "term": 20,
            "sum_assured": 1_000_000.0,
            "interest_rate": 0.05,
            "table_id": "soa_ilt",
            "shocks": {
                "interest_rate_bps": -100.0,
                "mortality_multiplier": 1.20,
                "lapse_multiplier": 1.50,
                "expense_inflation_pct": 5.0,
            },
        }

        response = client.post("/api/v1/valuation/stress-test", json=payload)
        assert response.status_code == 200
        data = response.json()

        assert "baseline_reserve" in data
        assert "stressed_reserve" in data
        assert "delta_reserve" in data
        assert "reserve_trajectory" in data
        assert len(data["reserve_trajectory"]) == 21  # t=0..20 (21 points)
        assert len(data["tornado_data"]) == 4  # 4 slider risk factors
        assert data["shocks_applied"]["interest_rate_bps"] == -100.0
        assert data["shocks_applied"]["mortality_multiplier"] == 1.20

    def test_stress_test_sliders_with_base_assumptions(self) -> None:
        """Test stress testing endpoint with base_assumptions dict."""
        client = TestClient(app)
        payload = {
            "contract_id": "POL-1001",
            "base_assumptions": {
                "product_type": "term",
                "issue_age": 35,
                "term": 15,
                "sum_assured": 500_000.0,
                "interest_rate": 0.045,
                "table_id": "soa_ilt",
            },
            "shocks": {
                "interest_rate_bps": 50.0,
                "mortality_multiplier": 1.0,
                "lapse_multiplier": 1.0,
                "expense_inflation_pct": 0.0,
            },
        }

        response = client.post("/api/v1/valuation/stress-test", json=payload)
        assert response.status_code == 200
        data = response.json()

        assert data["product_type"] == "term"
        assert len(data["reserve_trajectory"]) == 16  # t=0..15 (16 points)

    def test_invalid_shocks_payload_returns_422(self) -> None:
        """Test that invalid non-dict shocks payloads are rejected by Pydantic validation."""
        client = TestClient(app)
        payload = {
            "product_type": "term",
            "issue_age": 35,
            "shocks": "invalid_string_instead_of_dict",
        }
        response = client.post("/api/v1/valuation/sensitivity/tornado", json=payload)
        assert response.status_code == 422

    def test_valid_custom_shocks_in_sensitivity_request(self) -> None:
        """Test that valid dictionary shocks are parsed and accepted."""
        client = TestClient(app)
        payload = {
            "product_type": "endowment",
            "issue_age": 30,
            "term": 20,
            "sum_assured": 1_000_000.0,
            "shocks": {"interest_shift": -0.01, "mortality_mult": 1.10},
        }
        response = client.post("/api/v1/valuation/sensitivity/tornado", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "tornado_items" in data
        assert "combined_scenarios" in data
