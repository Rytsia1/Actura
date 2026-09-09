"""
Tests for GrossPremiumValuation: multi-decrement projections, BEL, and gross reserves.

Validates:
- No-expense/no-lapse GPV matches net premium valuation
- Expense loading increases BEL (insurer liability rises)
- Lapse rates reduce in-force population correctly
- Multi-decrement dependent rates (UDD approximation)
- Gross reserve profile structure
- BEL sign conventions and magnitudes
"""

import numpy as np
import pytest

from actuary_engine.models.assumptions import (
    ExpenseAssumption,
    InterestAssumption,
    LapseAssumption,
)
from actuary_engine.models.contracts import PolicyContract, ProductType
from actuary_engine.domain.pricing.premium import LevelPremiumCalculator
from actuary_engine.domain.tables.commutation import CommutationFunctions
from actuary_engine.domain.tables.mortality_table import MortalityTable
from actuary_engine.valuation.gpv import GrossPremiumValuation


# ────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def gpv_no_expense(
    soa_table: MortalityTable, interest_5pct: InterestAssumption
) -> GrossPremiumValuation:
    """GPV engine with no expenses and no lapses (should match net premium)."""
    return GrossPremiumValuation(soa_table, interest_5pct)


@pytest.fixture(scope="session")
def gpv_with_expense(
    soa_table: MortalityTable, interest_5pct: InterestAssumption
) -> GrossPremiumValuation:
    """GPV engine with realistic expense assumptions."""
    expense = ExpenseAssumption(
        percent_of_premium_first=0.50,    # 50% first-year acquisition
        percent_of_premium_renewal=0.10,  # 10% renewal maintenance
        per_policy_first=500.0,           # $500 first-year flat
        per_policy_renewal=50.0,          # $50 renewal flat
    )
    return GrossPremiumValuation(soa_table, interest_5pct, expense=expense)


@pytest.fixture(scope="session")
def gpv_with_lapse(
    soa_table: MortalityTable, interest_5pct: InterestAssumption
) -> GrossPremiumValuation:
    """GPV engine with lapse rates."""
    lapse = LapseAssumption(
        duration_rates=[0.10, 0.08, 0.06, 0.05, 0.04],  # Higher early lapses
        flat_annual_rate=0.03,  # Flat rate after year 5
    )
    return GrossPremiumValuation(soa_table, interest_5pct, lapse=lapse)


@pytest.fixture(scope="session")
def gpv_full(
    soa_table: MortalityTable, interest_5pct: InterestAssumption
) -> GrossPremiumValuation:
    """GPV engine with both expenses and lapses."""
    expense = ExpenseAssumption(
        percent_of_premium_first=0.40,
        percent_of_premium_renewal=0.08,
        per_policy_first=300.0,
        per_policy_renewal=30.0,
    )
    lapse = LapseAssumption(
        duration_rates=[0.08, 0.06, 0.04, 0.03],
        flat_annual_rate=0.02,
    )
    return GrossPremiumValuation(soa_table, interest_5pct, expense=expense, lapse=lapse)


@pytest.fixture(scope="session")
def term_net_premium(premium_calculator: LevelPremiumCalculator) -> float:
    """Net premium for 20-year term, age 30, face 1M."""
    return premium_calculator.annual_premium_term(30, 20, face=1_000_000).annual_premium


# ────────────────────────────────────────────────────────────
# No-Expense/No-Lapse: GPV Should Match Net Premium Results
# ────────────────────────────────────────────────────────────

class TestGPVNoExpenseNoLapse:
    """GPV with zero expenses and zero lapses should match net premium valuation."""

    def test_bel_zero_at_net_premium(
        self, gpv_no_expense: GrossPremiumValuation, term_net_premium: float
    ) -> None:
        """BEL ≈ 0 when using the net premium (equivalence principle holds)."""
        contract = PolicyContract(
            product_type=ProductType.TERM, issue_age=30, term=20, sum_assured=1_000_000
        )
        bel = gpv_no_expense.best_estimate_liability(contract, term_net_premium)
        assert abs(bel) < 1.0, f"BEL should be ≈ 0 at net premium, got {bel:.4f}"

    def test_projection_shape(
        self, gpv_no_expense: GrossPremiumValuation, term_net_premium: float
    ) -> None:
        """Projection has correct number of rows."""
        contract = PolicyContract(
            product_type=ProductType.TERM, issue_age=30, term=20, sum_assured=1_000_000
        )
        df = gpv_no_expense.project(contract, term_net_premium)
        assert len(df) == 20

    def test_no_lapse_column_zero(
        self, gpv_no_expense: GrossPremiumValuation, term_net_premium: float
    ) -> None:
        """With no lapse assumption, lapses should be zero."""
        contract = PolicyContract(
            product_type=ProductType.TERM, issue_age=30, term=20, sum_assured=1_000_000
        )
        df = gpv_no_expense.project(contract, term_net_premium)
        assert (df["lapses"] == 0).all()
        assert (df["lapse_payouts"] == 0).all()

    def test_no_expense_columns_zero(
        self, gpv_no_expense: GrossPremiumValuation, term_net_premium: float
    ) -> None:
        """With no expense assumption, expenses should be zero."""
        contract = PolicyContract(
            product_type=ProductType.TERM, issue_age=30, term=20, sum_assured=1_000_000
        )
        df = gpv_no_expense.project(contract, term_net_premium)
        assert (df["pct_expense"] == 0).all()
        assert (df["per_policy_expense"] == 0).all()

    def test_inforce_starts_at_one(
        self, gpv_no_expense: GrossPremiumValuation, term_net_premium: float
    ) -> None:
        """In-force at BOY year 0 = 1.0."""
        contract = PolicyContract(
            product_type=ProductType.TERM, issue_age=30, term=20, sum_assured=1_000_000
        )
        df = gpv_no_expense.project(contract, term_net_premium)
        assert df["inforce_boy"].iloc[0] == pytest.approx(1.0)


# ────────────────────────────────────────────────────────────
# Expense Impact
# ────────────────────────────────────────────────────────────

class TestExpenseImpact:
    """Test that expenses increase the insurer's liability."""

    def test_bel_increases_with_expenses(
        self,
        gpv_no_expense: GrossPremiumValuation,
        gpv_with_expense: GrossPremiumValuation,
        term_net_premium: float,
    ) -> None:
        """BEL with expenses > BEL without expenses (at same premium)."""
        contract = PolicyContract(
            product_type=ProductType.TERM, issue_age=30, term=20, sum_assured=1_000_000
        )
        bel_no_exp = gpv_no_expense.best_estimate_liability(contract, term_net_premium)
        bel_with_exp = gpv_with_expense.best_estimate_liability(contract, term_net_premium)
        assert bel_with_exp > bel_no_exp

    def test_first_year_expense_higher(
        self, gpv_with_expense: GrossPremiumValuation, term_net_premium: float
    ) -> None:
        """First-year total expense > renewal year expense."""
        contract = PolicyContract(
            product_type=ProductType.TERM, issue_age=30, term=20, sum_assured=1_000_000
        )
        df = gpv_with_expense.project(contract, term_net_premium)
        assert df["total_expense"].iloc[0] > df["total_expense"].iloc[1]

    def test_pct_expense_proportional_to_premium(
        self, gpv_with_expense: GrossPremiumValuation,
    ) -> None:
        """Percentage expense scales with premium amount."""
        contract = PolicyContract(
            product_type=ProductType.TERM, issue_age=30, term=20, sum_assured=1_000_000
        )
        df_low = gpv_with_expense.project(contract, 1_000.0)
        df_high = gpv_with_expense.project(contract, 10_000.0)
        # First-year pct expense should be 10x higher for 10x premium
        ratio = df_high["pct_expense"].iloc[0] / df_low["pct_expense"].iloc[0]
        assert ratio == pytest.approx(10.0, rel=1e-10)


# ────────────────────────────────────────────────────────────
# Lapse Impact
# ────────────────────────────────────────────────────────────

class TestLapseImpact:
    """Test lapse decrement behavior."""

    def test_lapse_reduces_inforce(
        self,
        gpv_no_expense: GrossPremiumValuation,
        gpv_with_lapse: GrossPremiumValuation,
        term_net_premium: float,
    ) -> None:
        """In-force population decreases faster with lapses."""
        contract = PolicyContract(
            product_type=ProductType.TERM, issue_age=30, term=20, sum_assured=1_000_000
        )
        df_no_lapse = gpv_no_expense.project(contract, term_net_premium)
        df_with_lapse = gpv_with_lapse.project(contract, term_net_premium)

        # At every year > 0, in-force with lapses should be lower
        for t in range(1, 20):
            assert df_with_lapse["inforce_boy"].iloc[t] < df_no_lapse["inforce_boy"].iloc[t], \
                f"Failed at year {t}"

    def test_dependent_rates_sum_less_than_one(
        self, gpv_with_lapse: GrossPremiumValuation, term_net_premium: float
    ) -> None:
        """Dependent death + lapse rates must be < 1 (valid probability)."""
        contract = PolicyContract(
            product_type=ProductType.TERM, issue_age=30, term=20, sum_assured=1_000_000
        )
        df = gpv_with_lapse.project(contract, term_net_premium)
        total_dep_rate = df["qx_dependent"] + df["wx_dependent"]
        assert (total_dep_rate < 1.0).all()

    def test_udd_dependent_rate_adjustment(
        self, gpv_with_lapse: GrossPremiumValuation, term_net_premium: float
    ) -> None:
        """Dependent rates follow UDD: qᵈ = q·(1-w/2), wᵈ = w·(1-q/2)."""
        contract = PolicyContract(
            product_type=ProductType.TERM, issue_age=30, term=20, sum_assured=1_000_000
        )
        df = gpv_with_lapse.project(contract, term_net_premium)

        expected_qd = df["qx_independent"] * (1.0 - df["wx_independent"] / 2.0)
        expected_wd = df["wx_independent"] * (1.0 - df["qx_independent"] / 2.0)

        np.testing.assert_allclose(df["qx_dependent"].values, expected_qd.values, atol=1e-12)
        np.testing.assert_allclose(df["wx_dependent"].values, expected_wd.values, atol=1e-12)

    def test_duration_specific_lapse_rates(
        self, gpv_with_lapse: GrossPremiumValuation, term_net_premium: float
    ) -> None:
        """Duration-specific lapse rates are applied correctly."""
        contract = PolicyContract(
            product_type=ProductType.TERM, issue_age=30, term=20, sum_assured=1_000_000
        )
        df = gpv_with_lapse.project(contract, term_net_premium)

        # Year 0 (duration 1) should use 0.10
        assert df["wx_independent"].iloc[0] == pytest.approx(0.10)
        # Year 4 (duration 5) should use 0.04
        assert df["wx_independent"].iloc[4] == pytest.approx(0.04)
        # Year 5+ (beyond vector) should use flat rate 0.03
        assert df["wx_independent"].iloc[5] == pytest.approx(0.03)


# ────────────────────────────────────────────────────────────
# BEL and Gross Reserve Properties
# ────────────────────────────────────────────────────────────

class TestBELProperties:
    """Test BEL computation and gross reserve profiles."""

    def test_bel_positive_at_low_premium(
        self, gpv_with_expense: GrossPremiumValuation
    ) -> None:
        """BEL > 0 when premium is too low to cover benefits + expenses."""
        contract = PolicyContract(
            product_type=ProductType.TERM, issue_age=30, term=20, sum_assured=1_000_000
        )
        bel = gpv_with_expense.best_estimate_liability(contract, gross_premium=100.0)
        assert bel > 0, "BEL should be positive when premium is insufficient"

    def test_bel_negative_at_high_premium(
        self, gpv_no_expense: GrossPremiumValuation
    ) -> None:
        """BEL < 0 when premium greatly exceeds expected benefits (profit)."""
        contract = PolicyContract(
            product_type=ProductType.TERM, issue_age=30, term=20, sum_assured=1_000_000
        )
        bel = gpv_no_expense.best_estimate_liability(contract, gross_premium=100_000.0)
        assert bel < 0, "BEL should be negative when premium is excessive"

    def test_gross_reserve_profile_shape(
        self, gpv_full: GrossPremiumValuation
    ) -> None:
        """Gross reserve profile has n+1 rows."""
        contract = PolicyContract(
            product_type=ProductType.TERM, issue_age=30, term=20, sum_assured=1_000_000
        )
        df = gpv_full.gross_reserve_profile(contract, gross_premium=5_000.0)
        assert len(df) == 21

    def test_gross_reserve_terminal_zero(
        self, gpv_full: GrossPremiumValuation
    ) -> None:
        """Gross reserve at terminal duration = 0 (all CFs settled)."""
        contract = PolicyContract(
            product_type=ProductType.TERM, issue_age=30, term=20, sum_assured=1_000_000
        )
        df = gpv_full.gross_reserve_profile(contract, gross_premium=5_000.0)
        assert df["gross_reserve"].iloc[-1] == pytest.approx(0.0)


# ────────────────────────────────────────────────────────────
# Endowment / Pure Endowment with GPV
# ────────────────────────────────────────────────────────────

class TestGPVEndowment:
    """Test GPV for endowment and pure endowment products."""

    def test_endowment_maturity_benefit(
        self, gpv_no_expense: GrossPremiumValuation
    ) -> None:
        """Endowment projection has maturity benefit in last year."""
        contract = PolicyContract(
            product_type=ProductType.ENDOWMENT, issue_age=30, term=20, sum_assured=1_000_000
        )
        df = gpv_no_expense.project(contract, gross_premium=30_000.0)
        assert df["maturity_benefit"].iloc[-1] > 0
        assert (df["maturity_benefit"].iloc[:-1] == 0).all()

    def test_pure_endowment_no_death_claims(
        self, gpv_no_expense: GrossPremiumValuation
    ) -> None:
        """Pure endowment has zero death claims."""
        contract = PolicyContract(
            product_type=ProductType.PURE_ENDOWMENT, issue_age=30, term=20, sum_assured=1_000_000
        )
        df = gpv_no_expense.project(contract, gross_premium=28_000.0)
        assert (df["death_claims"] == 0).all()

    def test_endowment_with_lapses_reduced_maturity(
        self, gpv_with_lapse: GrossPremiumValuation
    ) -> None:
        """Maturity benefit is reduced by lapses (fewer survivors)."""
        contract = PolicyContract(
            product_type=ProductType.ENDOWMENT, issue_age=30, term=20, sum_assured=1_000_000
        )
        no_lapse_gpv = GrossPremiumValuation(
            gpv_with_lapse.table, gpv_with_lapse.interest
        )
        df_no_lapse = no_lapse_gpv.project(contract, 30_000.0)
        df_with_lapse = gpv_with_lapse.project(contract, 30_000.0)
        assert df_with_lapse["maturity_benefit"].iloc[-1] < \
               df_no_lapse["maturity_benefit"].iloc[-1]


class TestLapseAssumptionValidation:
    """Test validation constraints on LapseAssumption and duration_rates."""

    def test_negative_duration_rate_raises(self) -> None:
        """duration_rates containing negative rates like -0.5 must be rejected."""
        with pytest.raises(Exception, match="must be a valid probability in range"):
            LapseAssumption(duration_rates=[-0.5, 0.05])

    def test_duration_rate_exceeding_one_raises(self) -> None:
        """duration_rates containing rates > 1.0 like 2.0 must be rejected."""
        with pytest.raises(Exception, match="must be a valid probability in range"):
            LapseAssumption(duration_rates=[0.10, 2.0])

    def test_nan_duration_rate_raises(self) -> None:
        """duration_rates containing NaN or Inf must be rejected."""
        with pytest.raises(Exception, match="must be a finite number"):
            LapseAssumption(duration_rates=[0.10, float("nan")])

    def test_valid_boundary_duration_rates(self) -> None:
        """duration_rates with valid probabilities (including 0.0 and 1.0) are accepted."""
        lapse = LapseAssumption(duration_rates=[0.0, 0.05, 0.10, 1.0], flat_annual_rate=0.02)
        assert lapse.duration_rates == [0.0, 0.05, 0.10, 1.0]
        assert lapse.get_rate(1) == 0.0
        assert lapse.get_rate(4) == 1.0
        assert lapse.get_rate(5) == 0.02

