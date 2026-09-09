"""
Tests for SurvivalCurve: survival probabilities, life expectancy, and curve properties.
"""

import numpy as np
import pytest

from actuary_engine.domain.curves.survival import SurvivalCurve
from actuary_engine.domain.tables.mortality_table import MortalityTable


class TestSurvivalCurveProperties:
    """Test survival curve structure and basic properties."""

    def test_tpx_starts_at_one(self, survival_age30: SurvivalCurve) -> None:
        """₀p₃₀ = 1 (certain to be alive at entry)."""
        assert survival_age30.tpx[0] == 1.0

    def test_tpx_ends_near_zero(self, survival_age30: SurvivalCurve) -> None:
        """ₜp₃₀ → 0 as t → ω - 30."""
        assert survival_age30.tpx[-1] == pytest.approx(0.0, abs=1e-6)

    def test_tpx_monotonically_decreasing(self, survival_age30: SurvivalCurve) -> None:
        """Survival function must be non-increasing."""
        assert np.all(np.diff(survival_age30.tpx) <= 0)

    def test_tqx_complement(self, survival_age30: SurvivalCurve) -> None:
        """ₜqₓ = 1 - ₜpₓ for all t."""
        np.testing.assert_allclose(
            survival_age30.tqx, 1.0 - survival_age30.tpx
        )

    def test_deferred_qx_sums_to_one(self, survival_age30: SurvivalCurve) -> None:
        """Σ ₜ|₁qₓ = 1 (everyone eventually dies)."""
        total = np.sum(survival_age30.deferred_qx)
        assert total == pytest.approx(1.0, rel=1e-6)

    def test_duration_array(self, survival_age30: SurvivalCurve) -> None:
        """Duration array should be [0, 1, 2, ..., max_duration]."""
        expected = np.arange(survival_age30.max_duration + 1)
        np.testing.assert_array_equal(survival_age30.durations, expected)


class TestLifeExpectancy:
    """Test curtate and complete life expectancy."""

    def test_curtate_expectation_positive(self, survival_age30: SurvivalCurve) -> None:
        """Curtate expectation must be positive."""
        ex = survival_age30.curtate_expectation()
        assert ex > 0

    def test_curtate_reasonable_range(self, survival_age30: SurvivalCurve) -> None:
        """Curtate expectation for age 30 should be in reasonable range (30-60 years)."""
        ex = survival_age30.curtate_expectation()
        assert 30 < ex < 60

    def test_complete_exceeds_curtate(self, survival_age30: SurvivalCurve) -> None:
        """Complete expectation ≈ curtate + 0.5 (UDD assumption)."""
        ex = survival_age30.curtate_expectation()
        ex_complete = survival_age30.complete_expectation()
        assert ex_complete == pytest.approx(ex + 0.5)

    def test_expectation_decreases_with_age(self, soa_table: MortalityTable) -> None:
        """Life expectancy decreases with entry age."""
        ages = [20, 30, 40, 50, 60, 70]
        expectations = [
            SurvivalCurve(soa_table, x).curtate_expectation() for x in ages
        ]
        assert all(a > b for a, b in zip(expectations, expectations[1:]))


class TestMedianLifetime:
    """Test median future lifetime computation."""

    def test_median_positive(self, survival_age30: SurvivalCurve) -> None:
        """Median future lifetime must be positive."""
        assert survival_age30.median_future_lifetime() > 0

    def test_median_less_than_max_duration(self, survival_age30: SurvivalCurve) -> None:
        """Median must be less than max duration."""
        assert survival_age30.median_future_lifetime() < survival_age30.max_duration


class TestCurveAccessors:
    """Test point-access methods and export."""

    def test_survival_at(self, survival_age30: SurvivalCurve) -> None:
        """survival_at(t) matches tpx array."""
        for t in [0, 5, 10, 20, 40]:
            assert survival_age30.survival_at(t) == survival_age30.tpx[t]

    def test_out_of_range_raises(self, survival_age30: SurvivalCurve) -> None:
        """Out-of-range duration raises ValueError."""
        with pytest.raises(ValueError):
            survival_age30.survival_at(survival_age30.max_duration + 1)

    def test_to_dict(self, survival_age30: SurvivalCurve) -> None:
        """to_dict returns correct structure."""
        d = survival_age30.to_dict()
        assert set(d.keys()) == {"duration", "tpx", "tqx", "deferred_qx"}
        assert len(d["duration"]) == survival_age30.max_duration + 1


class TestProjectionExceedingMortalityDataValidation:
    """Verify that requesting projections exceeding available mortality table data raises explicit ValueError."""

    def test_survival_curve_exceeding_max_duration_raises(self, soa_table: MortalityTable) -> None:
        """Age 60 on table ending at 110 has only 50 years of data. Requesting 60 years raises ValueError."""
        # 60 + 60 = 120 > 110 (omega)
        with pytest.raises(ValueError, match="exceeds available mortality table data"):
            SurvivalCurve(soa_table, entry_age=60, max_duration=60)

    def test_tpx_vector_exceeding_max_duration_raises(self, soa_table: MortalityTable) -> None:
        """tpx_vector with max_t exceeding omega raises ValueError."""
        with pytest.raises(ValueError, match="exceeds available mortality table data"):
            soa_table.tpx_vector(x=60, max_t=60)

    def test_tqx_vector_exceeding_max_duration_raises(self, soa_table: MortalityTable) -> None:
        """tqx_vector with max_t exceeding omega raises ValueError."""
        with pytest.raises(ValueError, match="exceeds available mortality table data"):
            soa_table.tqx_vector(x=60, max_t=60)

    def test_get_tpx_exceeding_table_raises(self, soa_table: MortalityTable) -> None:
        """get_tpx with t exceeding table limit raises ValueError."""
        with pytest.raises(ValueError, match="exceeds available mortality table data"):
            soa_table.get_tpx(x=60, t=60)

    def test_get_deferred_qx_exceeding_table_raises(self, soa_table: MortalityTable) -> None:
        """get_deferred_qx with u + t exceeding table limit raises ValueError."""
        with pytest.raises(ValueError, match="exceeds available mortality table data"):
            soa_table.get_deferred_qx(x=60, u=50, t=5)

