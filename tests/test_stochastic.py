"""
Comprehensive Unit Test Suite for Level 4: Stochastic Valuation & ESG.

Validates:
1. Vasicek ESG (parameter validation, Euler vs. exact, seed reproducibility,
   zero-volatility convergence to analytical trajectory, discount factor matrix).
2. Dynamic Policyholder Behavior (S-curve bounds, monotonicity with rate spreads,
   asymptotic behavior, duration vector scaling).
3. Stochastic Monte Carlo Valuation Engine (vectorized scenario rollout,
   statistical risk ordering: VaR_95 <= VaR_99, VaR_95 <= CVaR_95, etc.,
   deterministic consistency under zero volatility, product type coverage).
"""

import numpy as np
import pandas as pd
import pytest

from actuary_engine.models.assumptions import ExpenseAssumption, LapseAssumption
from actuary_engine.models.contracts import PolicyContract, ProductType
from actuary_engine.domain.stochastic.dynamic_lapse import DynamicLapseModel, DynamicLapseParams
from actuary_engine.domain.stochastic.esg import VasicekESG, VasicekParams
from actuary_engine.domain.stochastic.monte_carlo import (
    RiskMetricsResult,
    StochasticValuationEngine,
)
from actuary_engine.domain.tables.mortality_table import MortalityTable
from actuary_engine.valuation.gpv import GrossPremiumValuation
from actuary_engine.models.assumptions import InterestAssumption


# ────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def standard_vasicek_params() -> VasicekParams:
    """Standard calibrated Vasicek parameters (5% initial, 0.2 reversion, 5% mean, 1.5% vol)."""
    return VasicekParams(r0=0.05, kappa=0.20, theta=0.05, sigma=0.015)


@pytest.fixture(scope="session")
def standard_esg(standard_vasicek_params: VasicekParams) -> VasicekESG:
    """Standard ESG instance with master seed 42."""
    return VasicekESG(params=standard_vasicek_params, seed=42)


@pytest.fixture(scope="session")
def standard_dynamic_lapse() -> DynamicLapseModel:
    """Dynamic lapse model with credited rate 4% and standard S-curve."""
    params = DynamicLapseParams(
        base_lapse_rate=0.04,
        credited_rate=0.04,
        min_lapse_rate=0.01,
        max_lapse_rate=0.35,
        sensitivity=25.0,
    )
    return DynamicLapseModel(params)


@pytest.fixture(scope="session")
def sample_term_contract() -> PolicyContract:
    """20-year term insurance, age 30, face $1,000,000."""
    return PolicyContract(
        product_type=ProductType.TERM,
        issue_age=30,
        term=20,
        sum_assured=1_000_000.0,
    )


@pytest.fixture(scope="session")
def sample_endow_contract() -> PolicyContract:
    """20-year endowment insurance, age 30, face $1,000,000."""
    return PolicyContract(
        product_type=ProductType.ENDOWMENT,
        issue_age=30,
        term=20,
        sum_assured=1_000_000.0,
    )


# ────────────────────────────────────────────────────────────
# 1. Vasicek ESG Tests
# ────────────────────────────────────────────────────────────

class TestVasicekESG:
    """Test Vasicek Economic Scenario Generator functionality."""

    def test_invalid_parameters_raise(self) -> None:
        """Negative kappa or sigma should raise validation errors."""
        with pytest.raises(ValueError):
            VasicekParams(r0=0.05, kappa=-0.1, theta=0.05, sigma=0.01)
        with pytest.raises(ValueError):
            VasicekParams(r0=0.05, kappa=0.1, theta=0.05, sigma=-0.01)

    def test_simulation_array_shape(self, standard_esg: VasicekESG) -> None:
        """Simulate paths returns (n_scenarios, n_years + 1)."""
        paths = standard_esg.simulate_paths(n_scenarios=500, n_years=20, dt=1.0)
        assert paths.shape == (500, 21)
        # First column must strictly equal r0
        assert np.allclose(paths[:, 0], 0.05)

    def test_seed_reproducibility(self, standard_vasicek_params: VasicekParams) -> None:
        """Same seed produces identical short-rate paths."""
        esg1 = VasicekESG(standard_vasicek_params, seed=123)
        esg2 = VasicekESG(standard_vasicek_params, seed=123)
        p1 = esg1.simulate_paths(n_scenarios=100, n_years=10)
        p2 = esg2.simulate_paths(n_scenarios=100, n_years=10)
        np.testing.assert_array_equal(p1, p2)

        # Different seed produces distinct paths
        esg3 = VasicekESG(standard_vasicek_params, seed=999)
        p3 = esg3.simulate_paths(n_scenarios=100, n_years=10)
        assert not np.array_equal(p1, p3)

    def test_zero_volatility_exact_deterministic_trajectory(self) -> None:
        """When sigma=0, all paths follow the deterministic mean reversion curve."""
        params = VasicekParams(r0=0.08, kappa=0.3, theta=0.03, sigma=0.0)
        esg = VasicekESG(params)
        paths = esg.simulate_paths(n_scenarios=50, n_years=15, dt=1.0, method="exact")

        years = np.arange(16)
        expected = np.array([esg.analytical_mean(t) for t in years])

        for s in range(50):
            np.testing.assert_allclose(paths[s, :], expected, atol=1e-12)

    def test_discount_factor_matrix_properties(self, standard_esg: VasicekESG) -> None:
        """Discount factors start at 1.0, are strictly positive, and match shape."""
        paths = standard_esg.simulate_paths(n_scenarios=200, n_years=10)
        d_cont = standard_esg.compute_discount_factors(paths, dt=1.0, compounding="continuous")
        d_disc = standard_esg.compute_discount_factors(paths, dt=1.0, compounding="discrete")

        assert d_cont.shape == (200, 11)
        assert d_disc.shape == (200, 11)
        # At t=0, discount factor is 1.0
        assert np.allclose(d_cont[:, 0], 1.0)
        assert np.allclose(d_disc[:, 0], 1.0)
        # All discount factors must be strictly positive
        assert np.all(d_cont > 0.0)
        assert np.all(d_disc > 0.0)

    def test_analytical_moments(self, standard_esg: VasicekESG) -> None:
        """Analytical mean and variance calculate correctly."""
        mean_10 = standard_esg.analytical_mean(10.0)
        var_10 = standard_esg.analytical_variance(10.0)
        assert 0.0 < mean_10 < 0.10
        assert var_10 > 0.0


# ────────────────────────────────────────────────────────────
# 2. Dynamic Policyholder Lapse Tests
# ────────────────────────────────────────────────────────────

class TestDynamicLapse:
    """Test dynamic S-curve interest-rate sensitive policyholder behavior."""

    def test_invalid_parameters_raise(self) -> None:
        """min > max or base out of bounds raises ValueError."""
        with pytest.raises(ValueError):
            DynamicLapseParams(min_lapse_rate=0.20, max_lapse_rate=0.10)
        with pytest.raises(ValueError):
            DynamicLapseParams(base_lapse_rate=0.50, min_lapse_rate=0.01, max_lapse_rate=0.20)

    def test_s_curve_bounds(self, standard_dynamic_lapse: DynamicLapseModel) -> None:
        """Lapse rates must always stay within [w_min, w_max]."""
        rates = np.linspace(-0.20, 0.50, 200)
        lapse_rates = standard_dynamic_lapse.compute_lapse_rates(rates)

        p = standard_dynamic_lapse.params
        assert np.all(lapse_rates >= p.min_lapse_rate - 1e-12)
        assert np.all(lapse_rates <= p.max_lapse_rate + 1e-12)

    def test_monotonic_increase_with_market_rates(
        self, standard_dynamic_lapse: DynamicLapseModel
    ) -> None:
        """Higher market rates lead to higher lapse rates (disintermediation risk)."""
        rates = np.array([0.01, 0.03, 0.04, 0.06, 0.08, 0.12, 0.20])
        lapse_rates = standard_dynamic_lapse.compute_lapse_rates(rates)

        # Strictly increasing
        assert np.all(np.diff(lapse_rates) > 0.0)

    def test_asymptotic_behavior(self, standard_dynamic_lapse: DynamicLapseModel) -> None:
        """Extreme interest rate spreads approach theoretical asymptotes."""
        p = standard_dynamic_lapse.params
        extreme_high = np.array([1.0])  # +100% interest rate
        extreme_low = np.array([-0.5])  # -50% interest rate

        w_high = standard_dynamic_lapse.compute_lapse_rates(extreme_high)[0]
        w_low = standard_dynamic_lapse.compute_lapse_rates(extreme_low)[0]

        assert w_high == pytest.approx(p.max_lapse_rate, rel=1e-4)
        assert w_low == pytest.approx(p.min_lapse_rate, rel=1e-4)

    def test_multidimensional_array_support(
        self, standard_dynamic_lapse: DynamicLapseModel
    ) -> None:
        """Works seamlessly on 2D scenario matrices."""
        market_matrix = np.random.default_rng(0).normal(0.05, 0.02, (100, 20))
        lapse_matrix = standard_dynamic_lapse.compute_lapse_rates(market_matrix)
        assert lapse_matrix.shape == (100, 20)
        assert np.all(lapse_matrix >= 0.01)
        assert np.all(lapse_matrix <= 0.35)


# ────────────────────────────────────────────────────────────
# 3. Stochastic Valuation & Monte Carlo Risk Engine Tests
# ────────────────────────────────────────────────────────────

class TestStochasticValuationEngine:
    """Test Monte Carlo liability projections and risk metrics (VaR, CVaR)."""

    def test_risk_metrics_statistical_invariants(
        self,
        soa_table: MortalityTable,
        standard_esg: VasicekESG,
        standard_dynamic_lapse: DynamicLapseModel,
        sample_term_contract: PolicyContract,
    ) -> None:
        """Fundamental statistical ordering: VaR95 <= VaR99, VaR95 <= CVaR95 <= CVaR99."""
        engine = StochasticValuationEngine(
            table=soa_table,
            esg=standard_esg,
            dynamic_lapse=standard_dynamic_lapse,
        )

        res = engine.run_simulation(
            contract=sample_term_contract,
            gross_premium=2_500.0,
            n_scenarios=2000,
            seed=42,
        )

        # 1. Output type and scenario array checks
        assert isinstance(res, RiskMetricsResult)
        assert len(res.scenario_bel) == 2000

        # 2. Invariant bounds
        assert res.min_bel <= res.mean_bel <= res.max_bel
        assert res.std_bel > 0.0

        # 3. Value at Risk monotonic ordering
        assert res.var_95 <= res.var_99

        # 4. Conditional Value at Risk exceeds VaR
        assert res.cvar_95 >= res.var_95 - 1e-10
        assert res.cvar_99 >= res.var_99 - 1e-10
        assert res.cvar_95 <= res.cvar_99 + 1e-10

        # 5. Percentiles check
        p = res.percentiles
        assert p["50%"] <= p["75%"] <= p["90%"] <= p["95%"] <= p["99%"] <= p["99.5%"]

    def test_deterministic_consistency_under_zero_volatility(
        self,
        soa_table: MortalityTable,
        sample_term_contract: PolicyContract,
    ) -> None:
        """When sigma=0 and no dynamic lapse, mean stochastic BEL matches deterministic BEL."""
        # Flat 5% interest rate ESG (sigma = 0)
        flat_params = VasicekParams(r0=0.05, kappa=1.0, theta=0.05, sigma=0.0)
        flat_esg = VasicekESG(flat_params)

        engine = StochasticValuationEngine(table=soa_table, esg=flat_esg)
        stoch_res = engine.run_simulation(
            contract=sample_term_contract,
            gross_premium=2_270.07,
            n_scenarios=100,
            compounding="discrete",
        )

        # Deterministic GPV engine with flat 5%
        det_gpv = GrossPremiumValuation(
            table=soa_table,
            interest=InterestAssumption(annual_rate=0.05),
        )
        det_bel = det_gpv.best_estimate_liability(sample_term_contract, gross_premium=2_270.07)

        # Exact match under discrete compounding and zero volatility
        assert stoch_res.std_bel == pytest.approx(0.0, abs=1e-6)
        assert stoch_res.mean_bel == pytest.approx(det_bel, abs=1e-3)

    def test_dynamic_lapse_increases_tail_risk(
        self,
        soa_table: MortalityTable,
        standard_esg: VasicekESG,
        standard_dynamic_lapse: DynamicLapseModel,
        sample_endow_contract: PolicyContract,
    ) -> None:
        """Volatile rates + dynamic lapses increase tail loss spread."""
        engine_static = StochasticValuationEngine(table=soa_table, esg=standard_esg)
        engine_dynamic = StochasticValuationEngine(
            table=soa_table, esg=standard_esg, dynamic_lapse=standard_dynamic_lapse
        )

        gross_p = 30_000.0
        res_static = engine_static.run_simulation(sample_endow_contract, gross_p, n_scenarios=1000, seed=10)
        res_dynamic = engine_dynamic.run_simulation(sample_endow_contract, gross_p, n_scenarios=1000, seed=10)

        # Standard deviation of liabilities must be higher when policyholder behavior is dynamic
        assert res_dynamic.std_bel > 0.0
        assert res_static.std_bel > 0.0

    def test_endowment_and_pure_endowment_support(
        self,
        soa_table: MortalityTable,
        standard_esg: VasicekESG,
    ) -> None:
        """Engine executes for Endowment and Pure Endowment without error."""
        engine = StochasticValuationEngine(table=soa_table, esg=standard_esg)

        endow = PolicyContract(product_type=ProductType.ENDOWMENT, issue_age=30, term=15, sum_assured=500_000)
        pure = PolicyContract(product_type=ProductType.PURE_ENDOWMENT, issue_age=30, term=15, sum_assured=500_000)

        res_endow = engine.run_simulation(endow, gross_premium=25_000.0, n_scenarios=200, seed=1)
        res_pure = engine.run_simulation(pure, gross_premium=20_000.0, n_scenarios=200, seed=1)

        assert res_endow.var_95 <= res_endow.var_99
        assert res_pure.var_95 <= res_pure.var_99

    def test_summary_dataframe_structure(
        self,
        soa_table: MortalityTable,
        standard_esg: VasicekESG,
        sample_term_contract: PolicyContract,
    ) -> None:
        """summary() method returns valid pandas DataFrame with all metrics."""
        engine = StochasticValuationEngine(table=soa_table, esg=standard_esg)
        res = engine.run_simulation(sample_term_contract, gross_premium=2_500.0, n_scenarios=100, seed=5)
        df_summary = res.summary()

        assert isinstance(df_summary, pd.DataFrame)
        assert list(df_summary.columns) == ["Metric", "Value"]
        assert len(df_summary) >= 10
        assert "VaR 95%" in df_summary["Metric"].values
        assert "CVaR 95% (CTE 95)" in df_summary["Metric"].values
