"""
Test suite for Lee-Carter Stochastic Mortality Improvement Model.
"""

from __future__ import annotations

import pytest
import numpy as np

from actuary_engine.domain.stochastic.lee_carter import (
    LeeCarterFitResult,
    LeeCarterForecastSummary,
    LeeCarterModel,
)
from actuary_engine.domain.tables.mortality_table import MortalityTable


@pytest.fixture(scope="session")
def sample_mortality_data() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Generate a realistic synthetic historical mortality surface matrix."""
    ages = np.arange(20, 91, dtype=np.int64)  # 71 ages
    years = np.arange(1990, 2024, dtype=np.int64)  # 34 years
    matrix = LeeCarterModel.generate_synthetic_historical_matrix(
        ages=ages,
        years=years,
        annual_improvement=0.012,
        seed=42,
    )
    return matrix, ages, years


class TestLeeCarterEstimation:
    """Test SVD decomposition, constraints, and parameter estimation."""

    def test_fit_returns_valid_result(
        self, sample_mortality_data: tuple[np.ndarray, np.ndarray, np.ndarray]
    ) -> None:
        m_mat, ages, years = sample_mortality_data
        model = LeeCarterModel()
        result = model.fit(m_mat, ages, years)

        assert isinstance(result, LeeCarterFitResult)
        assert len(result.alpha) == len(ages)
        assert len(result.beta) == len(ages)
        assert len(result.kappa) == len(years)
        assert result.variance_explained > 0.85  # 1st SVD component explains >85% variance
        assert result.drift < 0.0  # Mortality is improving (downward drift)

    def test_normalization_constraints(
        self, sample_mortality_data: tuple[np.ndarray, np.ndarray, np.ndarray]
    ) -> None:
        m_mat, ages, years = sample_mortality_data
        model = LeeCarterModel()
        model.fit(m_mat, ages, years)

        # Sum of beta_x must equal exactly 1.0
        assert np.isclose(np.sum(model.beta), 1.0, atol=1e-6)

        # Sum of kappa_t must be approximately 0.0 (mean-centered)
        assert np.isclose(np.sum(model.kappa), 0.0, atol=1e-4)

    def test_svd_rank1_reconstruction(
        self, sample_mortality_data: tuple[np.ndarray, np.ndarray, np.ndarray]
    ) -> None:
        m_mat, ages, years = sample_mortality_data
        model = LeeCarterModel()
        model.fit(m_mat, ages, years)

        # Reconstruct centered log rates: Z_hat = beta * kappa^T
        z_hat = model.beta[:, np.newaxis] @ model.kappa[np.newaxis, :]
        z_actual = np.log(m_mat) - model.alpha[:, np.newaxis]

        # Mean squared error of rank-1 SVD approximation
        mse = np.mean((z_actual - z_hat) ** 2)
        assert mse < 0.005, f"Rank-1 SVD MSE too large: {mse:.6f}"


class TestLeeCarterForecasting:
    """Test deterministic expected forecasts and stochastic simulations."""

    def test_forecast_expected_bounds(
        self, sample_mortality_data: tuple[np.ndarray, np.ndarray, np.ndarray]
    ) -> None:
        m_mat, ages, years = sample_mortality_data
        model = LeeCarterModel()
        model.fit(m_mat, ages, years)

        n_ahead = 30
        q_future = model.forecast_expected(n_ahead=n_ahead)

        assert q_future.shape == (len(ages), n_ahead)
        assert np.all(q_future >= 0.0)
        assert np.all(q_future <= 1.0)
        # Terminal age qx is 1.0
        assert np.all(q_future[-1, :] == 1.0)

        # As time progresses, mortality rates at adult ages should decline under negative drift
        mid_age_idx = 40  # Age 60
        assert q_future[mid_age_idx, -1] < q_future[mid_age_idx, 0]

    def test_stochastic_simulation_tensor(
        self, sample_mortality_data: tuple[np.ndarray, np.ndarray, np.ndarray]
    ) -> None:
        m_mat, ages, years = sample_mortality_data
        model = LeeCarterModel()
        model.fit(m_mat, ages, years)

        n_scenarios = 250
        n_ahead = 20
        q_tensor = model.simulate_stochastic_tables(
            n_ahead=n_ahead, n_scenarios=n_scenarios, seed=123
        )

        assert q_tensor.shape == (n_scenarios, len(ages), n_ahead)
        assert np.all(q_tensor >= 0.0)
        assert np.all(q_tensor <= 1.0)

        # Reproducibility with seed
        q_tensor_2 = model.simulate_stochastic_tables(
            n_ahead=n_ahead, n_scenarios=n_scenarios, seed=123
        )
        np.testing.assert_array_almost_equal(q_tensor, q_tensor_2)

    def test_dynamic_cohort_survival_exceeds_static(
        self, sample_mortality_data: tuple[np.ndarray, np.ndarray, np.ndarray]
    ) -> None:
        m_mat, ages, years = sample_mortality_data
        model = LeeCarterModel()
        model.fit(m_mat, ages, years)

        issue_age = 40
        horizon = 35
        durations, tpx_dynamic = model.to_dynamic_survival_curve(
            issue_age=issue_age, n_years=horizon
        )

        assert len(durations) == horizon + 1
        assert tpx_dynamic[0] == 1.0
        assert np.all(np.diff(tpx_dynamic) <= 0.0)  # Monotonically decreasing

        # Static survival curve using base year mortality rates
        min_age = int(ages[0])
        base_qx = 1.0 - np.exp(-m_mat[:, -1])  # most recent historical year
        static_px = 1.0 - base_qx[(issue_age - min_age) : (issue_age - min_age + horizon)]
        tpx_static = np.empty(horizon + 1, dtype=np.float64)
        tpx_static[0] = 1.0
        tpx_static[1:] = np.cumprod(static_px)

        # Dynamic survival should be greater than static survival due to mortality improvement
        assert tpx_dynamic[-1] > tpx_static[-1]


class TestLeeCarterErrors:
    """Test validation errors and edge cases."""

    def test_forecast_before_fit_raises_runtime_error(self) -> None:
        model = LeeCarterModel()
        with pytest.raises(RuntimeError, match="not been fitted"):
            model.forecast_expected(10)

    def test_mismatched_dimensions_raise_value_error(self) -> None:
        model = LeeCarterModel()
        bad_mat = np.ones((10, 5))
        ages = np.arange(10)
        years = np.arange(2000, 2004)  # 4 years vs 5 cols
        with pytest.raises(ValueError, match="does not match"):
            model.fit(bad_mat, ages, years)

    def test_non_positive_mortality_rates_raise_value_error(self) -> None:
        model = LeeCarterModel()
        bad_mat = np.zeros((10, 5))  # non-positive
        ages = np.arange(10)
        years = np.arange(2000, 2005)
        with pytest.raises(ValueError, match="strictly positive"):
            model.fit(bad_mat, ages, years)


class TestLeeCarterAPI:
    """Test FastAPI endpoint for Lee-Carter mortality forecasting."""

    def test_lee_carter_forecast_endpoint(self) -> None:
        from fastapi.testclient import TestClient
        from actuary_engine.main import app

        client = TestClient(app)
        payload = {
            "table_id": "soa_ilt",
            "n_ahead": 25,
            "n_scenarios": 300,
            "base_year": 2024,
            "annual_improvement": 0.015,
            "seed": 42,
        }

        response = client.post("/api/v1/mortality/lee-carter/forecast", json=payload)
        assert response.status_code == 200
        data = response.json()

        assert data["table_id"] == "soa_ilt"
        assert "fit" in data
        assert "forecast" in data

        fit = data["fit"]
        assert len(fit["alpha"]) > 0
        assert len(fit["beta"]) > 0
        assert fit["variance_explained"] > 0.80

        forecast = data["forecast"]
        assert len(forecast["forecast_years"]) == 25
        assert len(forecast["kappa_forecast_mean"]) == 25
        assert "sample_mortality_trajectories" in forecast
        assert len(forecast["life_expectancy_gains"]) > 0

    def test_lee_carter_nonexistent_table_returns_404(self) -> None:
        from fastapi.testclient import TestClient
        from actuary_engine.main import app

        client = TestClient(app)
        payload = {
            "table_id": "non_existent_table_xyz",
            "n_ahead": 20,
        }
        response = client.post("/api/v1/mortality/lee-carter/forecast", json=payload)
        assert response.status_code == 404

