"""
Test suite for IFRS 17 / PSAK 117 General Measurement Model (BBA) Valuation Engine.
"""

from __future__ import annotations

import pytest
import numpy as np
from fastapi.testclient import TestClient

from actuary_engine.models.assumptions import (
    ExpenseAssumption,
    InterestAssumption,
    LapseAssumption,
)
from actuary_engine.models.contracts import PolicyContract, ProductType
from actuary_engine.domain.tables.registry import table_registry
from actuary_engine.valuation.ifrs17 import (
    IFRS17CohortClassification,
    IFRS17Engine,
    IFRS17InitialBalance,
    IFRS17ValuationResult,
)
from actuary_engine.main import app


@pytest.fixture(scope="session")
def standard_setup() -> tuple[IFRS17Engine, PolicyContract]:
    table = table_registry.get_table("soa_ilt")
    interest = InterestAssumption(annual_rate=0.05)
    expense = ExpenseAssumption(
        percent_of_premium_first=0.25,
        percent_of_premium_renewal=0.05,
        per_policy_first=100.0,
        per_policy_renewal=15.0,
    )
    lapse = LapseAssumption(flat_annual_rate=0.03)
    engine = IFRS17Engine(table, interest, expense, lapse, ra_ratio=0.06)

    contract = PolicyContract(
        product_type=ProductType.ENDOWMENT,
        issue_age=35,
        term=20,
        sum_assured=500_000,
    )
    return engine, contract


class TestIFRS17InitialRecognition:
    """Test initial recognition fulfillment cash flows and profitability grouping."""

    def test_profitable_contract_initial_recognition(
        self, standard_setup: tuple[IFRS17Engine, PolicyContract]
    ) -> None:
        engine, contract = standard_setup
        # Adequate gross premium -> Profitable
        init = engine.evaluate_initial_recognition(contract, gross_premium=18_000.0)

        assert isinstance(init, IFRS17InitialBalance)
        assert init.classification in (
            IFRS17CohortClassification.PROFITABLE,
            IFRS17CohortClassification.NO_SIGNIFICANT_RISK_OF_BECOMING_ONEROUS,
        )
        assert init.csm_0 > 0.0
        assert init.loss_component_0 == 0.0
        assert init.fcf_0 < 0.0
        # LRC at Day 1 equals 0.0 (BEL + RA + CSM = 0)
        assert np.isclose(init.initial_lrc, 0.0, atol=1e-2)

    def test_onerous_contract_initial_recognition(
        self, standard_setup: tuple[IFRS17Engine, PolicyContract]
    ) -> None:
        engine, contract = standard_setup
        # Severely underpriced gross premium -> Onerous
        init = engine.evaluate_initial_recognition(contract, gross_premium=5_000.0)

        assert init.classification == IFRS17CohortClassification.ONEROUS
        assert init.csm_0 == 0.0
        assert init.loss_component_0 > 0.0
        assert init.fcf_0 > 0.0
        assert init.initial_lrc > 0.0  # Equal to loss component


class TestIFRS17RollForward:
    """Test multi-period CSM amortization and balance sheet roll-forward."""

    def test_csm_amortizes_to_zero_at_maturity(
        self, standard_setup: tuple[IFRS17Engine, PolicyContract]
    ) -> None:
        engine, contract = standard_setup
        result = engine.evaluate(contract, gross_premium=18_000.0)

        bs = result.balance_sheet_schedule
        assert len(bs) == 21  # t=0..20

        # CSM starts positive and reaches strictly 0.0 at maturity (t=20)
        assert bs[0]["csm"] > 0.0
        assert bs[-1]["csm"] == 0.0

        # Loss component is zero throughout for profitable contract
        assert all(row["loss_component"] == 0.0 for row in bs)

    def test_balance_sheet_lrc_decomposition(
        self, standard_setup: tuple[IFRS17Engine, PolicyContract]
    ) -> None:
        engine, contract = standard_setup
        result = engine.evaluate(contract, gross_premium=18_000.0)

        for row in result.balance_sheet_schedule:
            # LRC = BEL + RA + CSM
            expected_lrc = round(row["bel"] + row["risk_adjustment"] + row["csm"], 2)
            assert np.isclose(row["total_lrc"], expected_lrc, atol=0.05)

    def test_income_statement_service_result(
        self, standard_setup: tuple[IFRS17Engine, PolicyContract]
    ) -> None:
        engine, contract = standard_setup
        result = engine.evaluate(contract, gross_premium=18_000.0)

        pnl = result.income_statement_schedule
        assert len(pnl) == 20  # 20 projection years

        for row in pnl:
            expected_result = round(
                row["insurance_revenue"] - row["insurance_service_expenses"], 2
            )
            assert np.isclose(row["insurance_service_result"], expected_result, atol=0.05)

        # Cumulative CSM amortized is positive
        assert result.total_csm_released > 0.0
        assert result.total_insurance_revenue > 0.0


class TestIFRS17API:
    """Test FastAPI /api/v1/valuation/ifrs17 endpoint."""

    def test_ifrs17_valuation_endpoint(self) -> None:
        client = TestClient(app)
        payload = {
            "product_type": "endowment",
            "issue_age": 35,
            "term": 20,
            "sum_assured": 500_000,
            "interest_rate": 0.05,
            "gross_premium": 18_000,
            "table_id": "soa_ilt",
            "ra_ratio": 0.06,
        }

        response = client.post("/api/v1/valuation/ifrs17", json=payload)
        assert response.status_code == 200
        data = response.json()

        assert "initial_balance" in data
        assert "balance_sheet_schedule" in data
        assert "income_statement_schedule" in data
        assert data["initial_balance"]["csm_0"] > 0
        assert data["initial_balance"]["classification"] in ("PROFITABLE", "NO_SIGNIFICANT_RISK_OF_BECOMING_ONEROUS")
        assert len(data["balance_sheet_schedule"]) == 21

    def test_ifrs17_onerous_contract_endpoint(self) -> None:
        client = TestClient(app)
        payload = {
            "product_type": "term",
            "issue_age": 45,
            "term": 15,
            "sum_assured": 1_000_000,
            "interest_rate": 0.04,
            "gross_premium": 500,  # underpriced
            "table_id": "soa_ilt",
        }

        response = client.post("/api/v1/valuation/ifrs17", json=payload)
        assert response.status_code == 200
        data = response.json()

        assert data["initial_balance"]["classification"] == "ONEROUS"
        assert data["initial_balance"]["csm_0"] == 0.0
        assert data["initial_balance"]["loss_component_0"] > 0.0

    def test_ifrs17_endpoint_without_gross_premium(self) -> None:
        """Test endpoint when gross_premium is None (frontend default)."""
        client = TestClient(app)
        payload = {
            "product_type": "endowment",
            "issue_age": 30,
            "term": 20,
            "sum_assured": 1_000_000,
            "interest_rate": 0.05,
            "gross_premium": None,
            "table_id": "soa_ilt",
            "ra_ratio": 0.06,
        }

        response = client.post("/api/v1/valuation/ifrs17", json=payload)
        assert response.status_code == 200
        data = response.json()

        assert "initial_balance" in data
        assert "balance_sheet_schedule" in data
        assert "income_statement_schedule" in data
        assert len(data["balance_sheet_schedule"]) == 21
        assert data["initial_balance"]["bel_0"] is not None
