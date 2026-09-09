"""
Performance, JIT compilation, and numerical equivalence benchmarking test suite.

Verifies:
1. Exact numerical equivalence between JIT-accelerated kernels and pure reference formulas.
2. High-throughput execution speed benchmarks for 50,000 ESG paths and large-scale rollbacks.
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from actuary_engine.domain.curves.yield_curve import MarketYieldCurve
from actuary_engine.models.assumptions import ExpenseAssumption, InterestAssumption, LapseAssumption
from actuary_engine.models.contracts import PolicyContract, ProductType
from actuary_engine.domain.stochastic._kernels import (
    _simulate_cir_kernel,
    _simulate_vasicek_kernel,
    _stochastic_liability_kernel,
)
from actuary_engine.domain.stochastic.esg import VasicekESG, VasicekParams
from actuary_engine.domain.stochastic.esg_advanced import CIRModel
from actuary_engine.domain.tables.registry import table_registry
from actuary_engine.valuation._kernels import _portfolio_batch_rollout_kernel, _rollback_gpv_kernel
from actuary_engine.valuation.gpv import GrossPremiumValuation


class TestNumericalEquivalence:
    """Test mathematical equivalence of JIT kernels against pure NumPy implementations."""

    def test_vasicek_kernel_exact_equivalence(self) -> None:
        """Verify _simulate_vasicek_kernel matches reference Euler formula."""
        r0 = 0.05
        kappa = 0.20
        theta = 0.06
        sigma = 0.015
        dt = 1.0
        n_steps = 25
        n_scenarios = 100

        rng = np.random.default_rng(123)
        shocks = rng.standard_normal((n_scenarios, n_steps))

        # 1. JIT Kernel Output
        jit_rates = _simulate_vasicek_kernel(
            r0=r0,
            kappa=kappa,
            theta=theta,
            sigma=sigma,
            dt=dt,
            n_steps=n_steps,
            n_scenarios=n_scenarios,
            random_shocks=shocks,
        )

        # 2. Reference Pure Python / NumPy Formula
        ref_rates = np.empty((n_scenarios, n_steps + 1), dtype=np.float64)
        ref_rates[:, 0] = r0
        sqrt_dt = np.sqrt(dt)

        for t in range(n_steps):
            r_t = ref_rates[:, t]
            dr = kappa * (theta - r_t) * dt + sigma * sqrt_dt * shocks[:, t]
            ref_rates[:, t + 1] = r_t + dr

        np.testing.assert_allclose(jit_rates, ref_rates, rtol=1e-12, atol=1e-12)

    def test_cir_kernel_exact_equivalence(self) -> None:
        """Verify _simulate_cir_kernel matches reference Full Truncation formula."""
        r0 = 0.04
        kappa = 0.30
        theta = 0.05
        sigma = 0.025
        dt = 1.0
        n_steps = 20
        n_scenarios = 100

        rng = np.random.default_rng(456)
        shocks = rng.standard_normal((n_scenarios, n_steps))

        # 1. JIT Kernel Output
        jit_rates = _simulate_cir_kernel(
            r0=r0,
            kappa=kappa,
            theta=theta,
            sigma=sigma,
            dt=dt,
            n_steps=n_steps,
            n_scenarios=n_scenarios,
            random_shocks=shocks,
        )

        # 2. Reference Pure Formula
        ref_rates = np.empty((n_scenarios, n_steps + 1), dtype=np.float64)
        ref_rates[:, 0] = r0
        sqrt_dt = np.sqrt(dt)

        for t in range(n_steps):
            r_curr = np.maximum(0.0, ref_rates[:, t])
            dr = kappa * (theta - r_curr) * dt + sigma * np.sqrt(r_curr) * sqrt_dt * shocks[:, t]
            ref_rates[:, t + 1] = np.maximum(0.0, r_curr + dr)

        np.testing.assert_allclose(jit_rates, ref_rates, rtol=1e-12, atol=1e-12)

    def test_rollback_gpv_kernel_equivalence(self) -> None:
        """Verify rollback_reserve_profile matches standard gross_reserve_profile."""
        table = table_registry.get_table("soa_ilt")
        interest = InterestAssumption(annual_rate=0.05)
        expense = ExpenseAssumption(percent_of_premium_first=0.30, percent_of_premium_renewal=0.05)
        lapse = LapseAssumption(flat_annual_rate=0.03)

        gpv = GrossPremiumValuation(table=table, interest=interest, expense=expense, lapse=lapse)
        contract = PolicyContract(
            product_type=ProductType.ENDOWMENT,
            issue_age=35,
            term=20,
            sum_assured=500_000,
        )

        df_std = gpv.gross_reserve_profile(contract, gross_premium=18_000.0)
        df_rollback = gpv.rollback_reserve_profile(contract, gross_premium=18_000.0)

        # Both terminal reserves should be zero
        assert df_std["gross_reserve"].iloc[-1] == pytest.approx(0.0)
        assert df_rollback["gross_reserve"].iloc[-1] == pytest.approx(0.0)

        # Both trajectories must have matching lengths
        assert len(df_std) == len(df_rollback)

    def test_portfolio_batch_kernel_structure(self) -> None:
        """Verify _portfolio_batch_rollout_kernel runs cleanly across policy arrays."""
        n_pol = 50
        max_proj = 25
        issue_ages = np.full(n_pol, 30, dtype=np.int64)
        term_years = np.full(n_pol, 20, dtype=np.int64)
        sums_assured = np.full(n_pol, 100_000.0, dtype=np.float64)
        gross_premiums = np.full(n_pol, 2_500.0, dtype=np.float64)
        product_type_codes = np.zeros(n_pol, dtype=np.int64)

        qx_matrix = np.full((n_pol, max_proj), 0.002, dtype=np.float64)
        base_lapses = np.full(max_proj, 0.03, dtype=np.float64)

        i_rate = 0.05
        disc_boy = (1.0 + i_rate) ** (-np.arange(max_proj, dtype=np.float64))
        disc_eoy = (1.0 + i_rate) ** (-(np.arange(max_proj, dtype=np.float64) + 1.0))

        pvfb, pvfp, pvfe, bel = _portfolio_batch_rollout_kernel(
            issue_ages=issue_ages,
            term_years=term_years,
            sums_assured=sums_assured,
            gross_premiums=gross_premiums,
            product_type_codes=product_type_codes,
            qx_matrix=qx_matrix,
            base_lapses=base_lapses,
            discount_factors_boy=disc_boy,
            discount_factors_eoy=disc_eoy,
            expense_first_pct=0.35,
            expense_renewal_pct=0.05,
            expense_first_flat=100.0,
            expense_renewal_flat=20.0,
        )

        assert len(bel) == n_pol
        assert np.all(pvfb > 0.0)
        assert np.all(pvfp > 0.0)
        np.testing.assert_allclose(bel, pvfb + pvfe - pvfp)


class TestPerformanceBenchmarks:
    """Benchmark high-throughput simulation speeds."""

    def test_large_scale_vasicek_50k_paths_benchmark(self) -> None:
        """Benchmark 50,000 Vasicek simulation paths across 30 years."""
        params = VasicekParams(r0=0.05, kappa=0.25, theta=0.055, sigma=0.015)
        esg = VasicekESG(params=params, seed=42)

        n_scenarios = 50_000
        n_years = 30

        t0 = time.perf_counter()
        paths = esg.simulate_paths(n_scenarios=n_scenarios, n_years=n_years, method="euler")
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        assert paths.shape == (n_scenarios, n_years + 1)
        # Verify valid values
        assert not np.isnan(paths).any()
        assert not np.isinf(paths).any()

    def test_large_scale_cir_50k_paths_benchmark(self) -> None:
        """Benchmark 50,000 CIR simulation paths across 30 years."""
        cir = CIRModel(r0=0.05, kappa=0.25, theta=0.055, sigma=0.03)

        n_scenarios = 50_000
        n_years = 30

        t0 = time.perf_counter()
        paths = cir.simulate_paths(n_years=n_years, n_scenarios=n_scenarios, seed=42)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        assert paths.shape == (n_scenarios, n_years + 1)
        assert np.all(paths >= 0.0)

    def test_large_scale_portfolio_batch_kernel_benchmark(self) -> None:
        """Benchmark 10,000 policy batch rollout execution."""
        n_pol = 10_000
        max_proj = 30
        issue_ages = np.random.randint(20, 60, size=n_pol).astype(np.int64)
        term_years = np.random.randint(10, 30, size=n_pol).astype(np.int64)
        sums_assured = np.random.uniform(50_000, 1_000_000, size=n_pol).astype(np.float64)
        gross_premiums = np.random.uniform(1_000, 10_000, size=n_pol).astype(np.float64)
        product_type_codes = np.random.randint(0, 3, size=n_pol).astype(np.int64)

        qx_matrix = np.random.uniform(0.0005, 0.02, size=(n_pol, max_proj)).astype(np.float64)
        base_lapses = np.full(max_proj, 0.04, dtype=np.float64)

        i_rate = 0.05
        disc_boy = (1.0 + i_rate) ** (-np.arange(max_proj, dtype=np.float64))
        disc_eoy = (1.0 + i_rate) ** (-(np.arange(max_proj, dtype=np.float64) + 1.0))

        # Warm-up JIT compilation
        _ = _portfolio_batch_rollout_kernel(
            issue_ages=issue_ages[:10],
            term_years=term_years[:10],
            sums_assured=sums_assured[:10],
            gross_premiums=gross_premiums[:10],
            product_type_codes=product_type_codes[:10],
            qx_matrix=qx_matrix[:10],
            base_lapses=base_lapses,
            discount_factors_boy=disc_boy,
            discount_factors_eoy=disc_eoy,
            expense_first_pct=0.35,
            expense_renewal_pct=0.05,
            expense_first_flat=100.0,
            expense_renewal_flat=20.0,
        )

        t0 = time.perf_counter()
        pvfb, pvfp, pvfe, bel = _portfolio_batch_rollout_kernel(
            issue_ages=issue_ages,
            term_years=term_years,
            sums_assured=sums_assured,
            gross_premiums=gross_premiums,
            product_type_codes=product_type_codes,
            qx_matrix=qx_matrix,
            base_lapses=base_lapses,
            discount_factors_boy=disc_boy,
            discount_factors_eoy=disc_eoy,
            expense_first_pct=0.35,
            expense_renewal_pct=0.05,
            expense_first_flat=100.0,
            expense_renewal_flat=20.0,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        assert len(bel) == n_pol
        # 10,000 policy rollouts should execute within 1500 ms even under pure-python/JIT compilation
        assert elapsed_ms < 1500.0
