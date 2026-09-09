"""
Tests for MortalityTable: CSV loading, life table computation, and survival probabilities.
"""

import numpy as np
import pytest

from actuary_engine.domain.tables.mortality_table import MortalityTable


class TestMortalityTableLoading:
    """Test loading and parsing of mortality tables."""

    def test_soa_ilt_loads(self, soa_table: MortalityTable) -> None:
        """SOA ILT loads without error and has expected dimensions."""
        assert soa_table.min_age == 0
        assert soa_table.max_age == 110
        assert soa_table.num_ages == 111
        assert soa_table.name == "SOA Illustrative Life Table"

    def test_soa_ilt_qx_bounds(self, soa_table: MortalityTable) -> None:
        """All qx values are in [0, 1]."""
        assert np.all(soa_table.qx >= 0.0)
        assert np.all(soa_table.qx <= 1.0)

    def test_soa_ilt_terminal_qx(self, soa_table: MortalityTable) -> None:
        """qx at omega (age 110) must be 1.0."""
        assert soa_table.get_qx(110) == 1.0

    def test_from_qx_array(self) -> None:
        """Create table from raw qx array."""
        qx = [0.01, 0.02, 0.05, 0.10, 1.00]
        table = MortalityTable.from_qx_array(qx, start_age=60, name="test")
        assert table.min_age == 60
        assert table.max_age == 64
        assert table.num_ages == 5
        assert table.get_qx(60) == pytest.approx(0.01)

    def test_missing_limiting_age_raises(self) -> None:
        """Table ending with qx < 1.0 violates limiting age closure invariant and raises ValueError."""
        qx = [0.01, 0.02, 0.05, 0.10, 0.40]  # qx[max_age] = 0.40 != 1.0
        with pytest.raises(ValueError, match="Limiting age must have qx = 1.0"):
            MortalityTable.from_qx_array(qx, start_age=60)

    def test_premature_limiting_age_raises(self) -> None:
        """qx = 1.0 before the final limiting age violates pre-omega survivorship invariant."""
        qx = [0.01, 1.0, 0.05, 1.0]
        with pytest.raises(ValueError, match="prior to the limiting age omega"):
            MortalityTable.from_qx_array(qx, start_age=40)

    def test_negative_min_age_raises(self) -> None:
        """Negative starting age raises ValueError."""
        with pytest.raises(ValueError, match="non-negative"):
            MortalityTable.from_qx_array([0.1, 1.0], start_age=-5)

    def test_non_contiguous_ages_raises(self) -> None:
        """Gaps in ages array raise ValueError."""
        with pytest.raises(ValueError, match="contiguous integers"):
            MortalityTable(ages=np.array([0, 1, 3]), qx=np.array([0.1, 0.2, 1.0]))

    def test_invalid_radix_raises(self) -> None:
        """Zero or negative radix raises ValueError."""
        with pytest.raises(ValueError, match="positive integer"):
            MortalityTable.from_qx_array([0.1, 1.0], radix=0)

    def test_nan_qx_raises(self) -> None:
        """NaN or Inf in qx raises ValueError."""
        with pytest.raises(ValueError, match="NaN or Inf"):
            MortalityTable.from_qx_array([0.1, np.nan, 1.0])

    def test_invalid_qx_raises(self) -> None:
        """qx values outside [0, 1] raise ValueError."""
        with pytest.raises(ValueError, match="All qx values must be in"):
            MortalityTable.from_qx_array([0.5, -0.1, 1.0])

    def test_mismatched_lengths_raises(self) -> None:
        """Mismatched age/qx arrays raise ValueError."""
        with pytest.raises(ValueError, match="same length"):
            MortalityTable(
                ages=np.array([0, 1, 2]),
                qx=np.array([0.1, 0.2]),
            )


class TestLifeTableComputation:
    """Test lx, dx, px derivation from qx."""

    def test_lx_starts_at_radix(self, soa_table: MortalityTable) -> None:
        """lx at min_age equals the radix."""
        assert soa_table.get_lx(0) == 10_000_000

    def test_lx_monotonically_decreasing(self, soa_table: MortalityTable) -> None:
        """lx must be monotonically non-increasing."""
        assert np.all(np.diff(soa_table.lx) <= 0)

    def test_lx_terminal(self, soa_table: MortalityTable) -> None:
        """lx at omega + 1 should be 0 (entire cohort dies at omega)."""
        assert soa_table.get_lx(111) == pytest.approx(0.0, abs=1e-6)

    def test_dx_equals_lx_times_qx(self, soa_table: MortalityTable) -> None:
        """dx[x] = lx[x] * qx[x] for all ages."""
        for age in [0, 30, 65, 100, 110]:
            expected = soa_table.get_lx(age) * soa_table.get_qx(age)
            assert soa_table.get_dx(age) == pytest.approx(expected, rel=1e-10)

    def test_dx_sums_to_radix(self, soa_table: MortalityTable) -> None:
        """Total deaths must equal the initial radix."""
        assert np.sum(soa_table.dx) == pytest.approx(10_000_000, rel=1e-8)

    def test_px_complement(self, soa_table: MortalityTable) -> None:
        """px = 1 - qx for all ages."""
        np.testing.assert_allclose(soa_table.px, 1.0 - soa_table.qx)

    def test_tiny_table_lx(self, tiny_table: MortalityTable) -> None:
        """Hand-verify lx for the tiny test table.

        qx = [0.1, 0.2, 0.3, 0.5, 1.0], radix = 1000
        lx[0] = 1000
        lx[1] = 1000 * 0.9 = 900
        lx[2] = 900 * 0.8 = 720
        lx[3] = 720 * 0.7 = 504
        lx[4] = 504 * 0.5 = 252
        lx[5] = 252 * 0.0 = 0
        """
        expected_lx = [1000, 900, 720, 504, 252, 0]
        for i, expected in enumerate(expected_lx):
            assert tiny_table.get_lx(i) == pytest.approx(expected, rel=1e-10)


class TestSurvivalProbabilities:
    """Test tpx and tqx computations."""

    def test_0px_is_one(self, soa_table: MortalityTable) -> None:
        """₀pₓ = 1 for any age."""
        for x in [0, 30, 65, 100]:
            assert soa_table.get_tpx(x, 0) == 1.0

    def test_1px_equals_px(self, soa_table: MortalityTable) -> None:
        """₁pₓ = 1 - qx."""
        for x in [0, 30, 65, 100]:
            assert soa_table.get_tpx(x, 1) == pytest.approx(1.0 - soa_table.get_qx(x))

    def test_tpx_product_rule(self, soa_table: MortalityTable) -> None:
        """ₛ₊ₜpₓ = ₛpₓ · ₜpₓ₊ₛ (Chapman-Kolmogorov)."""
        x, s, t = 30, 10, 20
        lhs = soa_table.get_tpx(x, s + t)
        rhs = soa_table.get_tpx(x, s) * soa_table.get_tpx(x + s, t)
        assert lhs == pytest.approx(rhs, rel=1e-10)

    def test_tqx_complement(self, soa_table: MortalityTable) -> None:
        """ₜqₓ = 1 - ₜpₓ."""
        assert soa_table.get_tqx(30, 20) == pytest.approx(
            1.0 - soa_table.get_tpx(30, 20)
        )

    def test_tpx_vector_matches_scalar(self, soa_table: MortalityTable) -> None:
        """Vectorized tpx matches scalar computation."""
        x = 40
        vec = soa_table.tpx_vector(x, 30)
        for t in range(0, 31):
            assert vec[t] == pytest.approx(soa_table.get_tpx(x, t), rel=1e-10)

    def test_deferred_qx(self, soa_table: MortalityTable) -> None:
        """u|1_qx = upx · qx+u."""
        x, u = 30, 10
        expected = soa_table.get_tpx(x, u) * soa_table.get_qx(x + u)
        assert soa_table.get_deferred_qx(x, u, 1) == pytest.approx(expected, rel=1e-10)

    def test_negative_t_raises(self, soa_table: MortalityTable) -> None:
        """Negative t in tpx raises ValueError."""
        with pytest.raises(ValueError, match="non-negative"):
            soa_table.get_tpx(30, -1)

    def test_out_of_bounds_raises(self, soa_table: MortalityTable) -> None:
        """Age exceeding table raises ValueError."""
        with pytest.raises(ValueError):
            soa_table.get_qx(111)
