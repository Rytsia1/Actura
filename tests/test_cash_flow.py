"""
Tests for CashFlowProjector: expected cash flows and equivalence validation.
"""

import pytest
import pandas as pd

from actuary_engine.models.contracts import PolicyContract, ProductType
from actuary_engine.projections.cash_flow import CashFlowProjector
from actuary_engine.domain.pricing.premium import LevelPremiumCalculator
from actuary_engine.domain.tables.commutation import CommutationFunctions


class TestCashFlowProjection:
    """Test cash flow projection mechanics."""

    def test_term_projection_shape(
        self,
        cf_projector: CashFlowProjector,
        premium_calculator: LevelPremiumCalculator,
    ) -> None:
        """Term insurance projection has correct number of rows."""
        contract = PolicyContract(
            product_type=ProductType.TERM, issue_age=30, term=20, sum_assured=1_000_000
        )
        result = premium_calculator.annual_premium_term(30, 20, face=1_000_000)
        df = cf_projector.project(contract, result.annual_premium)
        assert len(df) == 20
        assert list(df.columns[:4]) == ["year", "age", "survivors", "deaths"]

    def test_survivors_start_at_one(
        self,
        cf_projector: CashFlowProjector,
        premium_calculator: LevelPremiumCalculator,
    ) -> None:
        """Survivors at year 0 = 1.0 (normalized)."""
        contract = PolicyContract(
            product_type=ProductType.TERM, issue_age=30, term=20, sum_assured=1.0
        )
        result = premium_calculator.annual_premium_term(30, 20, face=1.0)
        df = cf_projector.project(contract, result.annual_premium)
        assert df["survivors"].iloc[0] == pytest.approx(1.0)

    def test_deaths_positive(
        self,
        cf_projector: CashFlowProjector,
        premium_calculator: LevelPremiumCalculator,
    ) -> None:
        """All death values must be positive."""
        contract = PolicyContract(
            product_type=ProductType.TERM, issue_age=30, term=20, sum_assured=1.0
        )
        result = premium_calculator.annual_premium_term(30, 20, face=1.0)
        df = cf_projector.project(contract, result.annual_premium)
        assert (df["deaths"] > 0).all()

    def test_no_maturity_for_term(
        self,
        cf_projector: CashFlowProjector,
        premium_calculator: LevelPremiumCalculator,
    ) -> None:
        """Term insurance has zero maturity benefit."""
        contract = PolicyContract(
            product_type=ProductType.TERM, issue_age=30, term=20, sum_assured=1_000_000
        )
        result = premium_calculator.annual_premium_term(30, 20, face=1_000_000)
        df = cf_projector.project(contract, result.annual_premium)
        assert (df["maturity_benefit"] == 0).all()

    def test_endowment_has_maturity(
        self,
        cf_projector: CashFlowProjector,
        premium_calculator: LevelPremiumCalculator,
    ) -> None:
        """Endowment insurance has positive maturity benefit in last year."""
        contract = PolicyContract(
            product_type=ProductType.ENDOWMENT, issue_age=30, term=20, sum_assured=1_000_000
        )
        result = premium_calculator.annual_premium_endowment(30, 20, face=1_000_000)
        df = cf_projector.project(contract, result.annual_premium)
        assert df["maturity_benefit"].iloc[-1] > 0
        assert (df["maturity_benefit"].iloc[:-1] == 0).all()


class TestEquivalenceValidation:
    """Test that PV(net CFs) ≈ 0 for correctly priced policies."""

    def test_term_equivalence(
        self,
        cf_projector: CashFlowProjector,
        premium_calculator: LevelPremiumCalculator,
    ) -> None:
        """PV of net CFs ≈ 0 for correctly priced term insurance."""
        contract = PolicyContract(
            product_type=ProductType.TERM, issue_age=30, term=20, sum_assured=1_000_000
        )
        result = premium_calculator.annual_premium_term(30, 20, face=1_000_000)
        is_valid, pv_sum = cf_projector.validate_equivalence(
            contract, result.annual_premium, tolerance=1.0
        )
        assert is_valid, f"Equivalence failed: PV sum = {pv_sum:.6f}"

    def test_endowment_equivalence(
        self,
        cf_projector: CashFlowProjector,
        premium_calculator: LevelPremiumCalculator,
    ) -> None:
        """PV of net CFs ≈ 0 for correctly priced endowment insurance."""
        contract = PolicyContract(
            product_type=ProductType.ENDOWMENT, issue_age=30, term=20, sum_assured=1_000_000
        )
        result = premium_calculator.annual_premium_endowment(30, 20, face=1_000_000)
        is_valid, pv_sum = cf_projector.validate_equivalence(
            contract, result.annual_premium, tolerance=1.0
        )
        assert is_valid, f"Equivalence failed: PV sum = {pv_sum:.6f}"

    def test_whole_life_equivalence(
        self,
        cf_projector: CashFlowProjector,
        premium_calculator: LevelPremiumCalculator,
    ) -> None:
        """PV of net CFs ≈ 0 for correctly priced whole life insurance."""
        contract = PolicyContract(
            product_type=ProductType.WHOLE_LIFE, issue_age=30, sum_assured=1_000_000
        )
        result = premium_calculator.annual_premium_whole_life(30, face=1_000_000)
        is_valid, pv_sum = cf_projector.validate_equivalence(
            contract, result.annual_premium, tolerance=1.0
        )
        assert is_valid, f"Equivalence failed: PV sum = {pv_sum:.6f}"

    def test_pure_endowment_equivalence(
        self,
        cf_projector: CashFlowProjector,
        premium_calculator: LevelPremiumCalculator,
    ) -> None:
        """PV of net CFs ≈ 0 for correctly priced pure endowment."""
        contract = PolicyContract(
            product_type=ProductType.PURE_ENDOWMENT, issue_age=30, term=20, sum_assured=1_000_000
        )
        result = premium_calculator.annual_premium_pure_endowment(30, 20, face=1_000_000)
        is_valid, pv_sum = cf_projector.validate_equivalence(
            contract, result.annual_premium, tolerance=1.0
        )
        assert is_valid, f"Equivalence failed: PV sum = {pv_sum:.6f}"

    def test_wrong_premium_fails(
        self,
        cf_projector: CashFlowProjector,
    ) -> None:
        """Wrong premium should NOT satisfy equivalence."""
        contract = PolicyContract(
            product_type=ProductType.TERM, issue_age=30, term=20, sum_assured=1_000_000
        )
        # Use an obviously wrong premium
        is_valid, _ = cf_projector.validate_equivalence(
            contract, annual_premium=1.0, tolerance=1.0
        )
        assert not is_valid, "Wrong premium should fail equivalence"
