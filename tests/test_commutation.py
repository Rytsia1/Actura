"""
Tests for CommutationFunctions: Dx, Nx, Cx, Mx and derived present values.
"""

import numpy as np
import pytest

from actuary_engine.models.assumptions import InterestAssumption
from actuary_engine.domain.tables.commutation import CommutationFunctions
from actuary_engine.domain.tables.mortality_table import MortalityTable


class TestCommutationIdentities:
    """Test fundamental commutation function identities."""

    def test_nx_identity(self, commutation_5pct: CommutationFunctions) -> None:
        """Nx[x] - Nx[x+1] = Dx[x] for all valid x.

        This is the fundamental identity: N is the reverse cumsum of D.
        """
        for x in range(0, 110):
            lhs = commutation_5pct.get_Nx(x) - commutation_5pct.get_Nx(x + 1)
            rhs = commutation_5pct.get_Dx(x)
            assert lhs == pytest.approx(rhs, rel=1e-10), f"Failed at age {x}"

    def test_mx_identity(self, commutation_5pct: CommutationFunctions) -> None:
        """Mx[x] - Mx[x+1] = Cx[x] for all valid x.

        Fundamental identity: M is the reverse cumsum of C.
        """
        for x in range(0, 110):
            lhs = commutation_5pct.get_Mx(x) - commutation_5pct.get_Mx(x + 1)
            rhs = commutation_5pct.get_Cx(x)
            assert lhs == pytest.approx(rhs, rel=1e-10), f"Failed at age {x}"

    def test_dx_formula(self, commutation_5pct: CommutationFunctions) -> None:
        """Dx = v^x · lx for sample ages."""
        v = commutation_5pct.interest.discount_factor
        table = commutation_5pct.table
        for x in [0, 30, 65, 100]:
            expected = (v ** x) * table.get_lx(x)
            assert commutation_5pct.get_Dx(x) == pytest.approx(expected, rel=1e-10)

    def test_cx_formula(self, commutation_5pct: CommutationFunctions) -> None:
        """Cx = v^(x+1) · dx for sample ages."""
        v = commutation_5pct.interest.discount_factor
        table = commutation_5pct.table
        for x in [0, 30, 65, 100]:
            expected = (v ** (x + 1)) * table.get_dx(x)
            assert commutation_5pct.get_Cx(x) == pytest.approx(expected, rel=1e-10)

    def test_dx_positive(self, commutation_5pct: CommutationFunctions) -> None:
        """All Dx values must be positive (lx > 0 for valid ages)."""
        assert np.all(commutation_5pct.Dx > 0)

    def test_nx_monotonically_decreasing(self, commutation_5pct: CommutationFunctions) -> None:
        """Nx must be monotonically decreasing (since Dx > 0)."""
        assert np.all(np.diff(commutation_5pct.Nx) < 0)


class TestTinyTableCommutation:
    """Hand-verify commutation functions on the tiny test table."""

    def test_dx_values(self, tiny_commutation: CommutationFunctions) -> None:
        """Verify Dx for tiny table: ages 0-4, i=10%, radix=1000.

        v = 1/1.1
        D0 = v^0 · l0 = 1 · 1000 = 1000
        D1 = v^1 · l1 = (1/1.1) · 900 = 818.1818...
        D2 = v^2 · l2 = (1/1.1)^2 · 720 = 595.0413...
        """
        v = 1.0 / 1.1
        assert tiny_commutation.get_Dx(0) == pytest.approx(1000.0, rel=1e-10)
        assert tiny_commutation.get_Dx(1) == pytest.approx(900 * v, rel=1e-10)
        assert tiny_commutation.get_Dx(2) == pytest.approx(720 * v**2, rel=1e-10)

    def test_nx_terminal(self, tiny_commutation: CommutationFunctions) -> None:
        """Nx at omega equals Dx at omega (only one term in the sum)."""
        omega = tiny_commutation.table.max_age
        assert tiny_commutation.get_Nx(omega) == pytest.approx(
            tiny_commutation.get_Dx(omega), rel=1e-10
        )


class TestInsurancePresentValues:
    """Test insurance APVs computed from commutation functions."""

    def test_whole_life_bounds(self, commutation_5pct: CommutationFunctions) -> None:
        """Ax must be in (0, 1) for reasonable ages."""
        for x in [0, 30, 50, 65]:
            ax = commutation_5pct.whole_life_insurance(x)
            assert 0 < ax < 1, f"A_{x} = {ax} out of bounds"

    def test_whole_life_increases_with_age(self, commutation_5pct: CommutationFunctions) -> None:
        """Ax increases with age (higher mortality → higher insurance cost)."""
        ages = [20, 30, 40, 50, 60, 70, 80]
        vals = [commutation_5pct.whole_life_insurance(x) for x in ages]
        assert all(a < b for a, b in zip(vals, vals[1:]))

    def test_term_less_than_whole_life(self, commutation_5pct: CommutationFunctions) -> None:
        """Term insurance NSP < whole life NSP (fewer covered years)."""
        x = 30
        term_20 = commutation_5pct.term_insurance(x, 20)
        whole = commutation_5pct.whole_life_insurance(x)
        assert term_20 < whole

    def test_endowment_equals_term_plus_pure(self, commutation_5pct: CommutationFunctions) -> None:
        """Aₓ:n̅| = A¹ₓ:n̅| + ₙEx (endowment = term + pure endowment)."""
        x, n = 30, 20
        endow = commutation_5pct.endowment_insurance(x, n)
        term = commutation_5pct.term_insurance(x, n)
        pure = commutation_5pct.pure_endowment(x, n)
        assert endow == pytest.approx(term + pure, rel=1e-10)

    def test_pure_endowment_bounds(self, commutation_5pct: CommutationFunctions) -> None:
        """ₙEx must be in (0, 1)."""
        for x, n in [(30, 20), (40, 10), (50, 30)]:
            ne = commutation_5pct.pure_endowment(x, n)
            assert 0 < ne < 1, f"nEx({x},{n}) = {ne}"

    def test_invalid_term_raises(self, commutation_5pct: CommutationFunctions) -> None:
        """Term of 0 or negative raises ValueError."""
        with pytest.raises(ValueError, match="positive"):
            commutation_5pct.term_insurance(30, 0)


class TestAnnuityPresentValues:
    """Test annuity APVs computed from commutation functions."""

    def test_whole_life_annuity_due_positive(self, commutation_5pct: CommutationFunctions) -> None:
        """äx must be positive."""
        for x in [20, 40, 65]:
            assert commutation_5pct.whole_life_annuity_due(x) > 0

    def test_annuity_due_decreases_with_age(self, commutation_5pct: CommutationFunctions) -> None:
        """äx decreases with age (shorter expected lifetime)."""
        ages = [20, 30, 40, 50, 60, 70, 80]
        vals = [commutation_5pct.whole_life_annuity_due(x) for x in ages]
        assert all(a > b for a, b in zip(vals, vals[1:]))

    def test_temp_annuity_less_than_whole(self, commutation_5pct: CommutationFunctions) -> None:
        """äₓ:n̅| < äx for finite n."""
        x = 30
        temp = commutation_5pct.temp_annuity_due(x, 20)
        whole = commutation_5pct.whole_life_annuity_due(x)
        assert temp < whole

    def test_annuity_immediate_relation(self, commutation_5pct: CommutationFunctions) -> None:
        """ax = äx - 1."""
        x = 40
        a_due = commutation_5pct.whole_life_annuity_due(x)
        a_imm = commutation_5pct.whole_life_annuity_immediate(x)
        assert a_imm == pytest.approx(a_due - 1.0, rel=1e-10)

    def test_insurance_annuity_relation(self, commutation_5pct: CommutationFunctions) -> None:
        """Ax = 1 - d·äx where d = i/(1+i).

        This is a fundamental identity linking insurance and annuity values.
        """
        x = 30
        ax = commutation_5pct.whole_life_insurance(x)
        adx = commutation_5pct.whole_life_annuity_due(x)
        d = commutation_5pct.interest.effective_discount_rate
        assert ax == pytest.approx(1.0 - d * adx, rel=1e-10)


class TestZeroInterestRate:
    """Test 0% interest rate behavior (v=1, i=0)."""

    def test_zero_interest_assumption_properties(self) -> None:
        """InterestAssumption with i=0% has v=1, delta=0, d=0."""
        interest = InterestAssumption(annual_rate=0.0)
        assert interest.annual_rate == 0.0
        assert interest.discount_factor == 1.0
        assert interest.force_of_interest == 0.0
        assert interest.effective_discount_rate == 0.0

    def test_negative_interest_rate_raises(self) -> None:
        """Negative interest rate is rejected by Pydantic validation."""
        with pytest.raises(Exception):
            InterestAssumption(annual_rate=-0.01)

    def test_commutation_at_zero_interest(self, soa_table: MortalityTable) -> None:
        """At 0% interest: Dx = lx, Cx = dx, Mx = lx, and Ax = 1.0."""
        interest_0 = InterestAssumption(annual_rate=0.0)
        comm_0 = CommutationFunctions(soa_table, interest_0)

        for x in [0, 30, 65, 100]:
            # Dx = lx
            assert comm_0.get_Dx(x) == pytest.approx(soa_table.get_lx(x), rel=1e-10)
            # Cx = dx
            assert comm_0.get_Cx(x) == pytest.approx(soa_table.get_dx(x), rel=1e-10)
            # Mx = sum_{k=x}^omega dx = lx
            assert comm_0.get_Mx(x) == pytest.approx(soa_table.get_lx(x), rel=1e-10)
            # Whole life Ax = Mx / Dx = lx / lx = 1.0
            assert comm_0.whole_life_insurance(x) == pytest.approx(1.0, rel=1e-10)

        # Relation Ax = 1 - d * äx holds trivially (1 = 1 - 0 * äx = 1)
        for x in [20, 50]:
            ax = comm_0.whole_life_insurance(x)
            assert ax == pytest.approx(1.0, rel=1e-10)
            adx = comm_0.whole_life_annuity_due(x)
            assert ax == pytest.approx(1.0 - comm_0.interest.effective_discount_rate * adx, rel=1e-10)

