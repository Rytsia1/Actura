"""
Test suite for Advanced ESG Models: Hull-White 1-Factor, CIR, and Market Yield Curves.
"""

from __future__ import annotations

import pytest
import numpy as np
from fastapi.testclient import TestClient

from actuary_engine.domain.curves.yield_curve import MarketYieldCurve
from actuary_engine.domain.stochastic.esg_advanced import (
    CIRModel,
    CIRParams,
    HullWhite1FModel,
    HullWhiteParams,
)
from actuary_engine.main import app


class TestMarketYieldCurve:
    """Test yield curve bootstrapping, spline interpolation, and forward rates."""

    def test_spline_interpolation_nodes(self) -> None:
        tenors = np.array([1.0, 2.0, 5.0, 10.0, 20.0, 30.0])
        rates = np.array([0.045, 0.048, 0.052, 0.056, 0.058, 0.059])
        curve = MarketYieldCurve(tenors, rates, method="spline")

        # Spot rates at exact tenors should match input rates closely
        for t, r in zip(tenors, rates):
            assert np.isclose(curve.spot_rate(t), r, atol=1e-4)

    def test_zero_prices_monotonically_decrease(self) -> None:
        curve = MarketYieldCurve.from_us_treasury()
        t_grid = np.linspace(0.0, 30.0, 31)
        zero_prices = curve.zero_price(t_grid)

        assert zero_prices[0] == 1.0
        assert np.all(np.diff(zero_prices) <= 0.0)  # Monotonically decreasing discount factors

    def test_instantaneous_forward_rate_consistency(self) -> None:
        curve = MarketYieldCurve.from_sovereign_sun()
        t_grid = np.array([1.0, 5.0, 10.0, 20.0])
        f_rates = curve.instantaneous_forward_rate(t_grid)

        # Forward rates must be positive and reasonable (e.g. 3% to 15%)
        assert np.all(f_rates > 0.02)
        assert np.all(f_rates < 0.20)

    def test_forward_rate_derivative(self) -> None:
        curve = MarketYieldCurve.from_us_treasury()
        df_dt = curve.forward_rate_derivative(5.0)
        assert isinstance(df_dt, float)


class TestHullWhite1FModel:
    """Test Hull-White 1-Factor simulation, exact calibration, and martingale properties."""

    def test_hull_white_shape_and_seed(self) -> None:
        curve = MarketYieldCurve.from_us_treasury()
        model = HullWhite1FModel(curve, a=0.10, sigma=0.015)

        n_scenarios = 500
        n_years = 20
        rates_1 = model.simulate_paths(n_years=n_years, n_scenarios=n_scenarios, dt=1.0, seed=42)
        rates_2 = model.simulate_paths(n_years=n_years, n_scenarios=n_scenarios, dt=1.0, seed=42)

        assert rates_1.shape == (n_scenarios, n_years + 1)
        np.testing.assert_array_almost_equal(rates_1, rates_2)

    def test_hull_white_exact_calibration_martingale_condition(self) -> None:
        """Verify that average simulated discount factors converge to the initial market discount curve."""
        curve = MarketYieldCurve.from_us_treasury()
        model = HullWhite1FModel(curve, a=0.08, sigma=0.012)

        n_scenarios = 5000
        n_years = 15
        dt = 0.5  # Semi-annual steps
        rate_paths = model.simulate_paths(n_years=n_years, n_scenarios=n_scenarios, dt=dt, seed=123)

        # Discount factor paths D(0, t)
        df_paths = model.discount_factor_paths(rate_paths, dt=dt)
        mean_sim_df = np.mean(df_paths, axis=0)  # shape (n_steps + 1,)

        # Market discount curve P(0, t)
        time_grid = np.linspace(0.0, n_years, rate_paths.shape[1])
        market_df = curve.zero_price(time_grid)

        # Mean Absolute Error between simulated expectation and market curve
        mae = float(np.mean(np.abs(mean_sim_df - market_df)))
        assert mae < 0.02, f"Hull-White Monte Carlo discount factors diverge from market curve: MAE={mae:.4f}"

    def test_analytical_zero_price_at_t0(self) -> None:
        curve = MarketYieldCurve.from_us_treasury()
        model = HullWhite1FModel(curve, a=0.10, sigma=0.015)

        for T in [1.0, 5.0, 10.0, 20.0]:
            p_analytical = model.analytical_zero_price(t=0.0, T=T, r_t=model.r0)
            p_market = curve.zero_price(T)
            assert np.isclose(p_analytical, p_market, atol=1e-3)


class TestCIRModel:
    """Test Cox-Ingersoll-Ross model, Feller condition, and non-negativity."""

    def test_feller_condition_calculation(self) -> None:
        params_feller_ok = CIRParams(r0=0.05, kappa=0.30, theta=0.05, sigma=0.05)
        # 2*0.30*0.05 = 0.03 > 0.05^2 = 0.0025 -> ratio = 12.0
        assert params_feller_ok.is_feller_satisfied
        assert params_feller_ok.feller_ratio > 1.0

        params_feller_violated = CIRParams(r0=0.05, kappa=0.05, theta=0.02, sigma=0.10)
        # 2*0.05*0.02 = 0.002 < 0.10^2 = 0.010 -> ratio = 0.2
        assert not params_feller_violated.is_feller_satisfied

    def test_cir_non_negativity_preservation(self) -> None:
        model = CIRModel(r0=0.04, kappa=0.25, theta=0.05, sigma=0.06)
        rates = model.simulate_paths(n_years=30, n_scenarios=1000, dt=0.5, seed=99)

        assert rates.shape == (1000, 61)
        # Strict non-negativity test
        assert np.all(rates >= 0.0), "CIR rates breached zero floor!"

    def test_cir_analytical_zero_price(self) -> None:
        model = CIRModel(r0=0.05, kappa=0.20, theta=0.05, sigma=0.03)

        p0 = model.analytical_zero_price(0.0)
        p5 = model.analytical_zero_price(5.0)
        p10 = model.analytical_zero_price(10.0)

        assert np.isclose(p0, 1.0)
        assert 0.0 < p10 < p5 < 1.0


class TestESGSimulationAPI:
    """Test FastAPI /api/v1/esg/simulate endpoint."""

    def test_simulate_hull_white_endpoint(self) -> None:
        client = TestClient(app)
        payload = {
            "model_type": "HULL_WHITE_1F",
            "benchmark_curve": "US_TREASURY",
            "a": 0.10,
            "sigma": 0.015,
            "n_years": 15,
            "n_scenarios": 300,
            "dt": 1.0,
            "seed": 42,
        }

        response = client.post("/api/v1/esg/simulate", json=payload)
        assert response.status_code == 200
        data = response.json()

        assert data["model_type"] == "HULL_WHITE_1F"
        assert len(data["fan_chart_rates"]) == 16  # 0..15
        assert len(data["sample_paths"]) == 10
        assert data["pricing_error_mae"] < 0.05

    def test_simulate_cir_endpoint(self) -> None:
        client = TestClient(app)
        payload = {
            "model_type": "CIR",
            "r0": 0.05,
            "kappa": 0.20,
            "theta": 0.05,
            "sigma": 0.03,
            "n_years": 10,
            "n_scenarios": 200,
            "dt": 1.0,
        }

        response = client.post("/api/v1/esg/simulate", json=payload)
        assert response.status_code == 200
        data = response.json()

        assert data["model_type"] == "CIR"
        assert len(data["fan_chart_rates"]) == 11
        assert data["feller_condition_satisfied"] is True

    def test_simulate_vasicek_endpoint(self) -> None:
        client = TestClient(app)
        payload = {
            "model_type": "VASICEK",
            "r0": 0.05,
            "a": 0.20,
            "theta": 0.05,
            "sigma": 0.015,
            "n_years": 10,
            "n_scenarios": 200,
            "dt": 1.0,
            "seed": 42,
        }

        response = client.post("/api/v1/esg/simulate", json=payload)
        assert response.status_code == 200
        data = response.json()

        assert data["model_type"] == "VASICEK"
        assert len(data["fan_chart_rates"]) == 11
        assert len(data["sample_paths"]) == 10
        assert "simulated_discount_factors" in data
