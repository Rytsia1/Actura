"""
Tests for LevelPremiumCalculator: annual net premiums via equivalence principle.
"""

import pytest

from actuary_engine.models.contracts import PolicyContract, ProductType
from actuary_engine.domain.pricing.premium import LevelPremiumCalculator, PremiumResult


class TestEquivalencePrinciple:
    """Verify that P · ä = NSP (the equivalence principle) holds."""

    def test_term_equivalence(self, premium_calculator: LevelPremiumCalculator) -> None:
        """P · äₓ:n̅| = NSP for term insurance."""
        result = premium_calculator.annual_premium_term(30, 20, face=1.0)
        assert result.annual_premium * result.annuity_factor == pytest.approx(
            result.nsp, rel=1e-10
        )

    def test_whole_life_equivalence(self, premium_calculator: LevelPremiumCalculator) -> None:
        """P · äx = NSP for whole life insurance."""
        result = premium_calculator.annual_premium_whole_life(30, face=1.0)
        assert result.annual_premium * result.annuity_factor == pytest.approx(
            result.nsp, rel=1e-10
        )

    def test_endowment_equivalence(self, premium_calculator: LevelPremiumCalculator) -> None:
        """P · äₓ:n̅| = NSP for endowment insurance."""
        result = premium_calculator.annual_premium_endowment(30, 20, face=1.0)
        assert result.annual_premium * result.annuity_factor == pytest.approx(
            result.nsp, rel=1e-10
        )

    def test_pure_endowment_equivalence(self, premium_calculator: LevelPremiumCalculator) -> None:
        """P · äₓ:n̅| = NSP for pure endowment."""
        result = premium_calculator.annual_premium_pure_endowment(30, 20, face=1.0)
        assert result.annual_premium * result.annuity_factor == pytest.approx(
            result.nsp, rel=1e-10
        )


class TestPremiumOrdering:
    """Test that premium relationships are actuarially correct."""

    def test_term_less_than_endowment(self, premium_calculator: LevelPremiumCalculator) -> None:
        """Term premium < endowment premium (endowment has survival benefit)."""
        term = premium_calculator.annual_premium_term(30, 20, face=1.0)
        endow = premium_calculator.annual_premium_endowment(30, 20, face=1.0)
        assert term.annual_premium < endow.annual_premium

    def test_premium_increases_with_age(self, premium_calculator: LevelPremiumCalculator) -> None:
        """Term premium increases with issue age."""
        premiums = [
            premium_calculator.annual_premium_term(x, 20, face=1.0).annual_premium
            for x in [25, 30, 35, 40, 45]
        ]
        assert all(a < b for a, b in zip(premiums, premiums[1:]))

    def test_premium_scales_with_face(self, premium_calculator: LevelPremiumCalculator) -> None:
        """Premium is proportional to face amount."""
        p1 = premium_calculator.annual_premium_term(30, 20, face=1.0).annual_premium
        p1m = premium_calculator.annual_premium_term(30, 20, face=1_000_000).annual_premium
        assert p1m == pytest.approx(p1 * 1_000_000, rel=1e-10)


class TestLimitedPay:
    """Test limited-pay premium structures."""

    def test_limited_pay_higher(self, premium_calculator: LevelPremiumCalculator) -> None:
        """Limited-pay premium > ordinary premium (fewer payment years)."""
        ordinary = premium_calculator.annual_premium_endowment(30, 20, face=1.0)
        limited = premium_calculator.annual_premium_endowment(30, 20, face=1.0, premium_term=10)
        assert limited.annual_premium > ordinary.annual_premium

    def test_limited_pay_same_nsp(self, premium_calculator: LevelPremiumCalculator) -> None:
        """Limited-pay and ordinary have same NSP (same benefit)."""
        ordinary = premium_calculator.annual_premium_endowment(30, 20, face=1.0)
        limited = premium_calculator.annual_premium_endowment(30, 20, face=1.0, premium_term=10)
        assert limited.nsp == pytest.approx(ordinary.nsp, rel=1e-10)

    def test_limited_pay_equivalence(self, premium_calculator: LevelPremiumCalculator) -> None:
        """P · äₓ:h̅| = NSP for limited-pay."""
        result = premium_calculator.annual_premium_endowment(30, 20, face=1.0, premium_term=10)
        assert result.annual_premium * result.annuity_factor == pytest.approx(
            result.nsp, rel=1e-10
        )

    def test_invalid_premium_term_raises(self, premium_calculator: LevelPremiumCalculator) -> None:
        """Premium term > coverage term raises ValueError."""
        with pytest.raises(ValueError, match="cannot exceed"):
            premium_calculator.annual_premium_term(30, 20, face=1.0, premium_term=25)


class TestContractPricing:
    """Test pricing via PolicyContract dispatch."""

    def test_price_term_contract(self, premium_calculator: LevelPremiumCalculator) -> None:
        """Price a term contract via contract dispatch."""
        contract = PolicyContract(
            product_type=ProductType.TERM,
            issue_age=30,
            term=20,
            sum_assured=1_000_000,
        )
        result = premium_calculator.price_contract(contract)
        assert isinstance(result, PremiumResult)
        assert result.annual_premium > 0
        assert result.product_type == ProductType.TERM

    def test_price_whole_life_contract(self, premium_calculator: LevelPremiumCalculator) -> None:
        """Price a whole life contract."""
        contract = PolicyContract(
            product_type=ProductType.WHOLE_LIFE,
            issue_age=35,
            sum_assured=500_000,
        )
        result = premium_calculator.price_contract(contract)
        assert result.annual_premium > 0
        assert result.term is None

    def test_premium_result_frozen(self, premium_calculator: LevelPremiumCalculator) -> None:
        """PremiumResult should be immutable (frozen model)."""
        result = premium_calculator.annual_premium_term(30, 20, face=1.0)
        with pytest.raises(Exception):
            result.annual_premium = 999.0  # type: ignore[misc]
