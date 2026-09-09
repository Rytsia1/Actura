"""
Tests for AnnuityPricer: annuity-due and annuity-immediate present values.
"""

import pytest

from actuary_engine.domain.pricing.annuity import AnnuityPricer


class TestAnnuityDue:
    """Test annuity-due calculations."""

    def test_whole_life_due_positive(self, annuity_pricer: AnnuityPricer) -> None:
        """Whole life annuity-due must be positive."""
        for x in [20, 40, 65]:
            assert annuity_pricer.whole_life_due(x) > 0

    def test_whole_life_due_upper_bound(self, annuity_pricer: AnnuityPricer) -> None:
        """äx < 1/d where d = effective discount rate.

        Theoretical upper bound: certain annuity-due for life.
        """
        d = annuity_pricer.commutation.interest.effective_discount_rate
        for x in [20, 40, 65]:
            assert annuity_pricer.whole_life_due(x) < 1.0 / d

    def test_temporary_due_bounded_by_n(self, annuity_pricer: AnnuityPricer) -> None:
        """äₓ:n̅| ≤ n (can't exceed n certain payments)."""
        x, n = 30, 20
        assert annuity_pricer.temporary_due(x, n) <= n

    def test_temporary_due_bounded_by_whole(self, annuity_pricer: AnnuityPricer) -> None:
        """äₓ:n̅| < äx for finite n."""
        x, n = 30, 20
        assert annuity_pricer.temporary_due(x, n) < annuity_pricer.whole_life_due(x)

    def test_temporary_due_increases_with_n(self, annuity_pricer: AnnuityPricer) -> None:
        """Longer temporary annuity has higher PV."""
        x = 30
        vals = [annuity_pricer.temporary_due(x, n) for n in [5, 10, 15, 20, 30]]
        assert all(a < b for a, b in zip(vals, vals[1:]))


class TestAnnuityImmediate:
    """Test annuity-immediate calculations."""

    def test_whole_life_immediate_relation(self, annuity_pricer: AnnuityPricer) -> None:
        """ax = äx - 1."""
        x = 40
        assert annuity_pricer.whole_life_immediate(x) == pytest.approx(
            annuity_pricer.whole_life_due(x) - 1.0, rel=1e-10
        )

    def test_temporary_immediate_positive(self, annuity_pricer: AnnuityPricer) -> None:
        """Temporary annuity-immediate must be positive."""
        assert annuity_pricer.temporary_immediate(30, 20) > 0


class TestDeferredAnnuities:
    """Test deferred annuity calculations."""

    def test_deferred_less_than_whole(self, annuity_pricer: AnnuityPricer) -> None:
        """Deferred whole life annuity-due < whole life annuity-due."""
        x = 30
        deferred = annuity_pricer.deferred_whole_life_due(x, u=10)
        whole = annuity_pricer.whole_life_due(x)
        assert deferred < whole

    def test_deferred_decomposition(self, annuity_pricer: AnnuityPricer) -> None:
        """äx = äₓ:u̅| + u|äx (split at deferral point u).

        The whole life annuity equals the temporary for u years
        plus the u-year deferred whole life annuity.
        """
        x, u = 30, 15
        whole = annuity_pricer.whole_life_due(x)
        temp_u = annuity_pricer.temporary_due(x, u)
        deferred_u = annuity_pricer.deferred_whole_life_due(x, u)
        assert whole == pytest.approx(temp_u + deferred_u, rel=1e-10)

    def test_deferred_temporary(self, annuity_pricer: AnnuityPricer) -> None:
        """Deferred temporary annuity is positive."""
        val = annuity_pricer.deferred_temporary_due(30, u=5, n=10)
        assert val > 0
