"""
Tests for InsurancePricer: NSP calculations for all product types.
"""

import pytest

from actuary_engine.models.contracts import PolicyContract, ProductType
from actuary_engine.domain.pricing.insurance import InsurancePricer


class TestInsurancePricing:
    """Test NSP calculations for standard products."""

    def test_nsp_term_positive(self, insurance_pricer: InsurancePricer) -> None:
        """Term insurance NSP must be positive."""
        nsp = insurance_pricer.nsp_term(30, 20, face=1_000_000)
        assert nsp > 0

    def test_nsp_whole_life_positive(self, insurance_pricer: InsurancePricer) -> None:
        """Whole life NSP must be positive."""
        nsp = insurance_pricer.nsp_whole_life(30, face=1_000_000)
        assert nsp > 0

    def test_nsp_endowment_positive(self, insurance_pricer: InsurancePricer) -> None:
        """Endowment insurance NSP must be positive."""
        nsp = insurance_pricer.nsp_endowment(30, 20, face=1_000_000)
        assert nsp > 0

    def test_nsp_pure_endowment_positive(self, insurance_pricer: InsurancePricer) -> None:
        """Pure endowment NSP must be positive."""
        nsp = insurance_pricer.nsp_pure_endowment(30, 20, face=1_000_000)
        assert nsp > 0

    def test_nsp_ordering(self, insurance_pricer: InsurancePricer) -> None:
        """For same age/term: term < endowment, pure endowment < endowment."""
        x, n, face = 30, 20, 1_000_000
        term = insurance_pricer.nsp_term(x, n, face)
        endow = insurance_pricer.nsp_endowment(x, n, face)
        pure = insurance_pricer.nsp_pure_endowment(x, n, face)
        whole = insurance_pricer.nsp_whole_life(x, face)

        assert term < endow
        assert pure < endow
        assert term < whole  # Term covers fewer years

    def test_nsp_scales_linearly_with_face(self, insurance_pricer: InsurancePricer) -> None:
        """NSP is proportional to face amount."""
        nsp_1 = insurance_pricer.nsp_term(30, 20, face=1.0)
        nsp_1m = insurance_pricer.nsp_term(30, 20, face=1_000_000)
        assert nsp_1m == pytest.approx(nsp_1 * 1_000_000, rel=1e-10)

    def test_nsp_increases_with_age(self, insurance_pricer: InsurancePricer) -> None:
        """Term NSP increases with issue age (higher mortality risk)."""
        nsps = [insurance_pricer.nsp_term(x, 20, 1.0) for x in [25, 30, 35, 40, 45]]
        assert all(a < b for a, b in zip(nsps, nsps[1:]))

    def test_endowment_decomposition(self, insurance_pricer: InsurancePricer) -> None:
        """Endowment = term + pure endowment."""
        x, n, face = 40, 15, 1.0
        endow = insurance_pricer.nsp_endowment(x, n, face)
        term = insurance_pricer.nsp_term(x, n, face)
        pure = insurance_pricer.nsp_pure_endowment(x, n, face)
        assert endow == pytest.approx(term + pure, rel=1e-10)


class TestContractPricing:
    """Test pricing via PolicyContract objects."""

    def test_price_term_contract(self, insurance_pricer: InsurancePricer) -> None:
        """Price a term contract via contract dispatch."""
        contract = PolicyContract(
            product_type=ProductType.TERM,
            issue_age=30,
            term=20,
            sum_assured=1_000_000,
        )
        nsp = insurance_pricer.price_contract(contract)
        expected = insurance_pricer.nsp_term(30, 20, 1_000_000)
        assert nsp == pytest.approx(expected)

    def test_price_whole_life_contract(self, insurance_pricer: InsurancePricer) -> None:
        """Price a whole life contract via contract dispatch."""
        contract = PolicyContract(
            product_type=ProductType.WHOLE_LIFE,
            issue_age=35,
            sum_assured=500_000,
        )
        nsp = insurance_pricer.price_contract(contract)
        expected = insurance_pricer.nsp_whole_life(35, 500_000)
        assert nsp == pytest.approx(expected)

    def test_price_endowment_contract(self, insurance_pricer: InsurancePricer) -> None:
        """Price an endowment contract via contract dispatch."""
        contract = PolicyContract(
            product_type=ProductType.ENDOWMENT,
            issue_age=25,
            term=30,
            sum_assured=2_000_000,
        )
        nsp = insurance_pricer.price_contract(contract)
        expected = insurance_pricer.nsp_endowment(25, 30, 2_000_000)
        assert nsp == pytest.approx(expected)
