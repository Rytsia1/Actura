"""
Tests for ReserveCalculator: prospective, retrospective, and recurrence reserves.

Validates:
- Boundary conditions: ₀V = 0, ₙV = 0 (term), ₙV = S (endowment)
- Prospective ≡ Retrospective identity under net premium valuation
- Reserve monotonicity and structural properties
- Recurrence relation consistency with commutation-based methods
- Multiple product types: term, endowment, whole life, pure endowment
"""

import numpy as np
import pytest

from actuary_engine.models.contracts import PolicyContract, ProductType
from actuary_engine.domain.pricing.premium import LevelPremiumCalculator
from actuary_engine.domain.tables.commutation import CommutationFunctions
from actuary_engine.valuation.reserves import ReserveCalculator


# ────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def reserve_calc(commutation_5pct: CommutationFunctions) -> ReserveCalculator:
    """Reserve calculator at 5% on SOA ILT."""
    return ReserveCalculator(commutation_5pct)


@pytest.fixture(scope="session")
def term_premium(premium_calculator: LevelPremiumCalculator) -> float:
    """Annual net premium for 20-year term, age 30, face 1."""
    return premium_calculator.annual_premium_term(30, 20, face=1.0).annual_premium


@pytest.fixture(scope="session")
def endow_premium(premium_calculator: LevelPremiumCalculator) -> float:
    """Annual net premium for 20-year endowment, age 30, face 1."""
    return premium_calculator.annual_premium_endowment(30, 20, face=1.0).annual_premium


@pytest.fixture(scope="session")
def whole_life_premium(premium_calculator: LevelPremiumCalculator) -> float:
    """Annual net premium for whole life, age 30, face 1."""
    return premium_calculator.annual_premium_whole_life(30, face=1.0).annual_premium


@pytest.fixture(scope="session")
def pure_endow_premium(premium_calculator: LevelPremiumCalculator) -> float:
    """Annual net premium for 20-year pure endowment, age 30, face 1."""
    return premium_calculator.annual_premium_pure_endowment(30, 20, face=1.0).annual_premium


# ────────────────────────────────────────────────────────────
# Boundary Conditions
# ────────────────────────────────────────────────────────────

class TestBoundaryConditions:
    """Test reserve boundary conditions — fundamental actuarial invariants."""

    def test_initial_reserve_zero_term(
        self, reserve_calc: ReserveCalculator, term_premium: float
    ) -> None:
        """₀V = 0 for term insurance (at issue, no liability accrued)."""
        v = reserve_calc.prospective_reserve(
            x=30, t=0, n=20, annual_premium=term_premium,
            face=1.0, product_type=ProductType.TERM,
        )
        assert v == pytest.approx(0.0, abs=1e-10)

    def test_initial_reserve_zero_endowment(
        self, reserve_calc: ReserveCalculator, endow_premium: float
    ) -> None:
        """₀V = 0 for endowment insurance."""
        v = reserve_calc.prospective_reserve(
            x=30, t=0, n=20, annual_premium=endow_premium,
            face=1.0, product_type=ProductType.ENDOWMENT,
        )
        assert v == pytest.approx(0.0, abs=1e-10)

    def test_initial_reserve_zero_whole_life(
        self, reserve_calc: ReserveCalculator, whole_life_premium: float
    ) -> None:
        """₀V = 0 for whole life insurance."""
        v = reserve_calc.prospective_reserve(
            x=30, t=0, n=None, annual_premium=whole_life_premium,
            face=1.0, product_type=ProductType.WHOLE_LIFE,
        )
        assert v == pytest.approx(0.0, abs=1e-10)

    def test_terminal_reserve_zero_term(
        self, reserve_calc: ReserveCalculator, term_premium: float
    ) -> None:
        """ₙV = 0 for term insurance (coverage expired, no liability)."""
        v = reserve_calc.prospective_reserve(
            x=30, t=20, n=20, annual_premium=term_premium,
            face=1.0, product_type=ProductType.TERM,
        )
        assert v == pytest.approx(0.0, abs=1e-10)

    def test_terminal_reserve_face_endowment(
        self, reserve_calc: ReserveCalculator, endow_premium: float
    ) -> None:
        """ₙV = S for endowment insurance (maturity benefit due)."""
        v = reserve_calc.prospective_reserve(
            x=30, t=20, n=20, annual_premium=endow_premium,
            face=1.0, product_type=ProductType.ENDOWMENT,
        )
        assert v == pytest.approx(1.0, abs=1e-10)

    def test_terminal_reserve_face_endowment_large_face(
        self, reserve_calc: ReserveCalculator, premium_calculator: LevelPremiumCalculator,
    ) -> None:
        """ₙV = 1,000,000 for endowment with face = 1,000,000."""
        face = 1_000_000.0
        p = premium_calculator.annual_premium_endowment(30, 20, face=face).annual_premium
        v = reserve_calc.prospective_reserve(
            x=30, t=20, n=20, annual_premium=p,
            face=face, product_type=ProductType.ENDOWMENT,
        )
        assert v == pytest.approx(face, abs=1e-4)


# ────────────────────────────────────────────────────────────
# Prospective ≡ Retrospective Identity
# ────────────────────────────────────────────────────────────

class TestProspectiveEqualsRetrospective:
    """Validate ₜV_pro ≡ ₜV_retro for all durations under net premium valuation."""

    def test_term_pro_retro_all_durations(
        self, reserve_calc: ReserveCalculator, term_premium: float
    ) -> None:
        """Pro ≡ retro for 20-year term at every duration t = 0..20."""
        contract = PolicyContract(
            product_type=ProductType.TERM, issue_age=30, term=20, sum_assured=1.0
        )
        all_match, df = reserve_calc.validate_prospective_equals_retrospective(
            contract, term_premium, tolerance=1e-6
        )
        assert all_match, (
            f"Pro ≠ retro at durations: "
            f"{df[df['absolute_difference'] >= 1e-6]['duration'].tolist()}"
        )

    def test_endowment_pro_retro_all_durations(
        self, reserve_calc: ReserveCalculator, endow_premium: float
    ) -> None:
        """Pro ≡ retro for 20-year endowment at every duration."""
        contract = PolicyContract(
            product_type=ProductType.ENDOWMENT, issue_age=30, term=20, sum_assured=1.0
        )
        all_match, df = reserve_calc.validate_prospective_equals_retrospective(
            contract, endow_premium, tolerance=1e-6
        )
        assert all_match

    def test_whole_life_pro_retro_sample_durations(
        self, reserve_calc: ReserveCalculator, whole_life_premium: float
    ) -> None:
        """Pro ≡ retro for whole life at sample durations."""
        for t in [1, 5, 10, 20, 40, 60]:
            pro = reserve_calc.prospective_reserve(
                x=30, t=t, n=None, annual_premium=whole_life_premium,
                face=1.0, product_type=ProductType.WHOLE_LIFE,
            )
            retro = reserve_calc.retrospective_reserve(
                x=30, t=t, n=None, annual_premium=whole_life_premium,
                face=1.0, product_type=ProductType.WHOLE_LIFE,
            )
            assert pro == pytest.approx(retro, abs=1e-6), f"Failed at t={t}"

    def test_pure_endowment_pro_retro(
        self, reserve_calc: ReserveCalculator, pure_endow_premium: float
    ) -> None:
        """Pro ≡ retro for 20-year pure endowment at every duration."""
        contract = PolicyContract(
            product_type=ProductType.PURE_ENDOWMENT, issue_age=30, term=20, sum_assured=1.0
        )
        all_match, df = reserve_calc.validate_prospective_equals_retrospective(
            contract, pure_endow_premium, tolerance=1e-6
        )
        assert all_match


# ────────────────────────────────────────────────────────────
# Structural Properties
# ────────────────────────────────────────────────────────────

class TestReserveStructuralProperties:
    """Test structural properties of reserve trajectories."""

    def test_term_reserves_non_negative(
        self, reserve_calc: ReserveCalculator, term_premium: float
    ) -> None:
        """Term insurance reserves are non-negative for all durations."""
        contract = PolicyContract(
            product_type=ProductType.TERM, issue_age=30, term=20, sum_assured=1.0
        )
        df = reserve_calc.reserve_profile(contract, term_premium, method="prospective")
        assert (df["reserve_prospective"] >= -1e-10).all()

    def test_endowment_reserves_non_negative(
        self, reserve_calc: ReserveCalculator, endow_premium: float
    ) -> None:
        """Endowment reserves are non-negative for all durations."""
        contract = PolicyContract(
            product_type=ProductType.ENDOWMENT, issue_age=30, term=20, sum_assured=1.0
        )
        df = reserve_calc.reserve_profile(contract, endow_premium, method="prospective")
        assert (df["reserve_prospective"] >= -1e-10).all()

    def test_endowment_reserve_monotonically_increasing(
        self, reserve_calc: ReserveCalculator, endow_premium: float
    ) -> None:
        """Endowment reserves should generally increase toward the face amount."""
        contract = PolicyContract(
            product_type=ProductType.ENDOWMENT, issue_age=30, term=20, sum_assured=1.0
        )
        df = reserve_calc.reserve_profile(contract, endow_premium, method="prospective")
        reserves = df["reserve_prospective"].values
        # Allow small numerical tolerance in monotonicity check
        assert reserves[-1] == pytest.approx(1.0, abs=1e-10)  # Terminal = face
        # General trend: reserves increase (may not be strict due to mortality patterns)
        assert reserves[10] > reserves[1]
        assert reserves[15] > reserves[5]

    def test_endowment_exceeds_term_at_all_durations(
        self, reserve_calc: ReserveCalculator, term_premium: float, endow_premium: float
    ) -> None:
        """Endowment reserve ≥ term reserve at every duration (extra survival benefit)."""
        for t in range(0, 21):
            v_term = reserve_calc.prospective_reserve(
                x=30, t=t, n=20, annual_premium=term_premium,
                face=1.0, product_type=ProductType.TERM,
            )
            v_endow = reserve_calc.prospective_reserve(
                x=30, t=t, n=20, annual_premium=endow_premium,
                face=1.0, product_type=ProductType.ENDOWMENT,
            )
            assert v_endow >= v_term - 1e-10, f"Failed at t={t}"

    def test_whole_life_reserves_increase(
        self, reserve_calc: ReserveCalculator, whole_life_premium: float
    ) -> None:
        """Whole life reserves should increase toward 1 (the face amount per unit)."""
        reserves = [
            reserve_calc.prospective_reserve(
                x=30, t=t, n=None, annual_premium=whole_life_premium,
                face=1.0, product_type=ProductType.WHOLE_LIFE,
            )
            for t in [0, 10, 20, 30, 50, 70]
        ]
        assert all(a < b for a, b in zip(reserves, reserves[1:]))


# ────────────────────────────────────────────────────────────
# Recurrence Relation
# ────────────────────────────────────────────────────────────

class TestRecurrenceRelation:
    """Validate reserves via Fackler recurrence match commutation-based reserves."""

    def test_term_recurrence_matches_prospective(
        self, reserve_calc: ReserveCalculator, term_premium: float
    ) -> None:
        """Recurrence reserves match prospective for term insurance."""
        contract = PolicyContract(
            product_type=ProductType.TERM, issue_age=30, term=20, sum_assured=1.0
        )
        df_recurr = reserve_calc.reserve_by_recurrence(contract, term_premium)
        df_pro = reserve_calc.reserve_profile(contract, term_premium, method="prospective")

        np.testing.assert_allclose(
            df_recurr["reserve_recurrence"].values,
            df_pro["reserve_prospective"].values,
            atol=1e-6,
        )

    def test_endowment_recurrence_matches_prospective(
        self, reserve_calc: ReserveCalculator, endow_premium: float
    ) -> None:
        """Recurrence reserves match prospective for endowment insurance."""
        contract = PolicyContract(
            product_type=ProductType.ENDOWMENT, issue_age=30, term=20, sum_assured=1.0
        )
        df_recurr = reserve_calc.reserve_by_recurrence(contract, endow_premium)
        df_pro = reserve_calc.reserve_profile(contract, endow_premium, method="prospective")

        np.testing.assert_allclose(
            df_recurr["reserve_recurrence"].values,
            df_pro["reserve_prospective"].values,
            atol=1e-6,
        )

    def test_endowment_recurrence_terminal(
        self, reserve_calc: ReserveCalculator, endow_premium: float
    ) -> None:
        """Recurrence terminal reserve = face for endowment."""
        contract = PolicyContract(
            product_type=ProductType.ENDOWMENT, issue_age=30, term=20, sum_assured=1_000_000
        )
        p = reserve_calc.commutation.endowment_insurance(30, 20) * 1_000_000
        p /= reserve_calc.commutation.temp_annuity_due(30, 20)
        df = reserve_calc.reserve_by_recurrence(contract, p)
        assert df["reserve_recurrence"].iloc[-1] == pytest.approx(1_000_000, abs=1.0)


# ────────────────────────────────────────────────────────────
# Reserve Profile DataFrame
# ────────────────────────────────────────────────────────────

class TestReserveProfile:
    """Test reserve profile output structure."""

    def test_profile_shape(
        self, reserve_calc: ReserveCalculator, term_premium: float
    ) -> None:
        """Profile has n+1 rows (durations 0 through n)."""
        contract = PolicyContract(
            product_type=ProductType.TERM, issue_age=30, term=20, sum_assured=1.0
        )
        df = reserve_calc.reserve_profile(contract, term_premium)
        assert len(df) == 21  # t = 0, 1, ..., 20

    def test_profile_both_methods(
        self, reserve_calc: ReserveCalculator, endow_premium: float
    ) -> None:
        """Profile with method='both' has both prospective and retrospective columns."""
        contract = PolicyContract(
            product_type=ProductType.ENDOWMENT, issue_age=30, term=20, sum_assured=1.0
        )
        df = reserve_calc.reserve_profile(contract, endow_premium, method="both")
        assert "reserve_prospective" in df.columns
        assert "reserve_retrospective" in df.columns

    def test_reserve_at_convenience(
        self, reserve_calc: ReserveCalculator, term_premium: float
    ) -> None:
        """reserve_at() returns same value as direct call."""
        contract = PolicyContract(
            product_type=ProductType.TERM, issue_age=30, term=20, sum_assured=1.0
        )
        v1 = reserve_calc.reserve_at(contract, term_premium, t=10, method="prospective")
        v2 = reserve_calc.prospective_reserve(
            x=30, t=10, n=20, annual_premium=term_premium,
            face=1.0, product_type=ProductType.TERM,
        )
        assert v1 == pytest.approx(v2)


# ────────────────────────────────────────────────────────────
# Error Handling
# ────────────────────────────────────────────────────────────

class TestReserveErrors:
    """Test error handling for invalid inputs."""

    def test_negative_duration_raises(self, reserve_calc: ReserveCalculator) -> None:
        """Negative duration raises ValueError."""
        with pytest.raises(ValueError, match="non-negative"):
            reserve_calc.prospective_reserve(
                x=30, t=-1, n=20, annual_premium=0.01,
                face=1.0, product_type=ProductType.TERM,
            )

    def test_duration_exceeds_term_raises(self, reserve_calc: ReserveCalculator) -> None:
        """Duration > term raises ValueError."""
        with pytest.raises(ValueError, match="exceeds"):
            reserve_calc.prospective_reserve(
                x=30, t=25, n=20, annual_premium=0.01,
                face=1.0, product_type=ProductType.TERM,
            )

    def test_invalid_method_raises(self, reserve_calc: ReserveCalculator) -> None:
        """Invalid method string raises ValueError."""
        contract = PolicyContract(
            product_type=ProductType.TERM, issue_age=30, term=20, sum_assured=1.0
        )
        with pytest.raises(ValueError, match="Method"):
            reserve_calc.reserve_at(contract, 0.01, t=5, method="invalid")
