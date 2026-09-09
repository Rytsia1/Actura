"""
Lee-Carter Stochastic Mortality Model.

Implements matrix singular value decomposition (SVD) and random walk with drift (RWD)
time-series forecasting to project long-term mortality improvements and longevity risk.

Mathematical formulation:
    ln(m_{x,t}) = alpha_x + beta_x * kappa_t + epsilon_{x,t}
    kappa_t = kappa_{t-1} + d + e_t,  e_t ~ N(0, sigma_e^2)
    q_{x,t} = 1 - exp(-m_{x,t})
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Union

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from actuary_engine.domain.tables.mortality_table import MortalityTable


class LeeCarterFitResult(BaseModel):
    """Fitted parameters and goodness-of-fit metrics from Lee-Carter SVD decomposition."""

    ages: list[int] = Field(..., description="Fitted age vector.")
    years: list[int] = Field(..., description="Fitted historical calendar year vector.")
    alpha: list[float] = Field(..., description="Baseline age-specific mortality schedule (alpha_x).")
    beta: list[float] = Field(..., description="Age-specific sensitivity to mortality trend (beta_x).")
    kappa: list[float] = Field(..., description="Historical time-varying mortality index (kappa_t).")
    drift: float = Field(..., description="Annual drift parameter d of kappa_t.")
    sigma_e: float = Field(..., description="Standard deviation of innovation error e_t.")
    variance_explained: float = Field(..., description="Proportion of variance explained by 1st SVD component (R^2).")


class LeeCarterForecastSummary(BaseModel):
    """Statistical summary of projected mortality indices and rates."""

    forecast_years: list[int] = Field(..., description="Projected future calendar years.")
    kappa_forecast_mean: list[float] = Field(..., description="Expected projected kappa_t.")
    kappa_forecast_p5: list[float] = Field(..., description="5th percentile projected kappa_t.")
    kappa_forecast_p50: list[float] = Field(..., description="Median projected kappa_t.")
    kappa_forecast_p95: list[float] = Field(..., description="95th percentile projected kappa_t.")
    sample_mortality_trajectories: dict[str, list[dict[str, Any]]] = Field(
        ..., description="Mortality rate quantiles for representative age cohorts (e.g. 30, 50, 65, 80)."
    )
    life_expectancy_gains: list[dict[str, Any]] = Field(
        ..., description="Projected remaining life expectancy gains over calendar years."
    )


class LeeCarterModel:
    """Lee-Carter Stochastic Mortality Modeling and Forecasting Engine.

    Attributes:
        ages: Array of fitted ages.
        years: Array of fitted historical calendar years.
        alpha: Fitted alpha_x baseline mortality array.
        beta: Fitted beta_x sensitivity array (normalized sum = 1).
        kappa: Fitted historical kappa_t index (centered sum = 0).
        drift: Estimated annual drift d of kappa_t.
        sigma_e: Estimated innovation standard deviation.
        variance_explained: R^2 of first principal component.
        is_fitted: Boolean flag indicating if model has been fitted.
    """

    __slots__ = (
        "ages",
        "years",
        "alpha",
        "beta",
        "kappa",
        "drift",
        "sigma_e",
        "variance_explained",
        "is_fitted",
    )

    def __init__(self) -> None:
        self.ages: np.ndarray = np.array([], dtype=np.int64)
        self.years: np.ndarray = np.array([], dtype=np.int64)
        self.alpha: np.ndarray = np.array([], dtype=np.float64)
        self.beta: np.ndarray = np.array([], dtype=np.float64)
        self.kappa: np.ndarray = np.array([], dtype=np.float64)
        self.drift: float = 0.0
        self.sigma_e: float = 0.0
        self.variance_explained: float = 0.0
        self.is_fitted: bool = False

    def fit(
        self,
        mortality_matrix: np.ndarray,
        ages: np.ndarray,
        years: np.ndarray,
    ) -> LeeCarterFitResult:
        """Fit the Lee-Carter model via Singular Value Decomposition (SVD).

        Args:
            mortality_matrix: 2D array of central death rates m_{x,t} of shape (n_ages, n_years).
                Values must be strictly positive.
            ages: 1D array of ages of length n_ages.
            years: 1D array of historical calendar years of length n_years.

        Returns:
            LeeCarterFitResult with fitted parameters and goodness of fit metrics.

        Raises:
            ValueError: If input dimensions are inconsistent or contain non-positive rates.
        """
        m_mat = np.asarray(mortality_matrix, dtype=np.float64)
        ages_arr = np.asarray(ages, dtype=np.int64)
        years_arr = np.asarray(years, dtype=np.int64)

        if m_mat.ndim != 2:
            raise ValueError(f"mortality_matrix must be 2D. Got shape {m_mat.shape}.")
        if len(ages_arr) != m_mat.shape[0]:
            raise ValueError(f"ages length ({len(ages_arr)}) does not match rows ({m_mat.shape[0]}).")
        if len(years_arr) != m_mat.shape[1]:
            raise ValueError(f"years length ({len(years_arr)}) does not match columns ({m_mat.shape[1]}).")
        if len(years_arr) < 3:
            raise ValueError(f"Must have at least 3 historical years for time-series fitting. Got {len(years_arr)}.")
        if np.any(m_mat <= 0.0):
            raise ValueError("All central death rates m_{x,t} must be strictly positive for log transformation.")

        self.ages = ages_arr
        self.years = years_arr
        n_ages, n_years = m_mat.shape

        # 1. Log-transform central mortality rates: Y = ln(m_{x,t})
        log_m = np.log(m_mat)

        # 2. Baseline mortality schedule: alpha_x = (1/T) * sum_t ln(m_{x,t})
        self.alpha = np.mean(log_m, axis=1)  # (N,)

        # 3. Mean-centered matrix: Z_{x,t} = ln(m_{x,t}) - alpha_x
        z_mat = log_m - self.alpha[:, np.newaxis]  # (N, T)

        # 4. Singular Value Decomposition: Z = U * Sigma * V^T
        u, s, vt = np.linalg.svd(z_mat, full_matrices=False)

        # First principal component
        u1 = u[:, 0]
        s1 = s[0]
        v1 = vt[0, :]

        # Enforce positive sensitivity sum convention
        sum_u1 = np.sum(u1)
        if sum_u1 < 0:
            u1 = -u1
            v1 = -v1
            sum_u1 = -sum_u1

        # Normalization constraints: sum(beta_x) = 1.0, sum(kappa_t) = 0.0
        self.beta = u1 / sum_u1  # sum(beta) == 1.0
        self.kappa = v1 * s1 * sum_u1  # beta * kappa == u1 * s1 * v1^T

        # Goodness of fit (R^2 variance explained by 1st component)
        total_variance = np.sum(s ** 2)
        self.variance_explained = float((s1 ** 2) / total_variance) if total_variance > 0 else 1.0

        # 5. Time-Series Estimation for kappa_t (Random Walk with Drift)
        # kappa_t = kappa_{t-1} + d + e_t
        delta_kappa = np.diff(self.kappa)
        self.drift = float(np.mean(delta_kappa))  # (kappa_T - kappa_1) / (T - 1)
        if len(delta_kappa) > 1:
            self.sigma_e = float(np.std(delta_kappa, ddof=1))
        else:
            self.sigma_e = 0.001

        self.is_fitted = True

        return LeeCarterFitResult(
            ages=self.ages.tolist(),
            years=self.years.tolist(),
            alpha=self.alpha.round(6).tolist(),
            beta=self.beta.round(6).tolist(),
            kappa=self.kappa.round(4).tolist(),
            drift=round(self.drift, 6),
            sigma_e=round(self.sigma_e, 6),
            variance_explained=round(self.variance_explained, 4),
        )

    def forecast_expected(self, n_ahead: int) -> np.ndarray:
        """Produce deterministic expected mortality probability matrix q_{x, T+h}.

        Args:
            n_ahead: Number of future calendar years to project.

        Returns:
            2D array of shape (n_ages, n_ahead) with projected annual mortality rates q_{x, T+h}.
        """
        self._check_fitted()
        if n_ahead <= 0:
            raise ValueError(f"n_ahead must be positive. Got {n_ahead}.")

        h_steps = np.arange(1, n_ahead + 1, dtype=np.float64)
        last_kappa = self.kappa[-1]

        # Projected kappa: kappa_{T+h} = kappa_T + d * h
        kappa_future = last_kappa + self.drift * h_steps  # (n_ahead,)

        # Projected central mortality: ln(m_{x, T+h}) = alpha_x + beta_x * kappa_{T+h}
        log_m_future = self.alpha[:, np.newaxis] + self.beta[:, np.newaxis] * kappa_future[np.newaxis, :]
        m_future = np.exp(log_m_future)

        # Convert to mortality probability: q_{x,t} = 1 - exp(-m_{x,t})
        q_future = 1.0 - np.exp(-m_future)
        q_future = np.clip(q_future, 0.0, 1.0)
        # Terminal age condition
        q_future[-1, :] = 1.0

        return q_future

    def simulate_stochastic_tables(
        self,
        n_ahead: int,
        n_scenarios: int = 1000,
        seed: Optional[int] = 42,
    ) -> np.ndarray:
        """Simulate stochastic Monte Carlo mortality tables.

        Args:
            n_ahead: Projection horizon in years.
            n_scenarios: Number of Monte Carlo scenario paths.
            seed: Random seed for reproducibility.

        Returns:
            3D tensor of shape (n_scenarios, n_ages, n_ahead) with projected mortality rates q_{x, T+h}^{(s)}.
        """
        self._check_fitted()
        if n_ahead <= 0 or n_scenarios <= 0:
            raise ValueError("n_ahead and n_scenarios must be positive.")

        rng = np.random.default_rng(seed)
        last_kappa = self.kappa[-1]

        # Generate Gaussian innovation increments: delta_kappa ~ N(d, sigma_e^2)
        innovations = rng.normal(
            loc=self.drift,
            scale=self.sigma_e,
            size=(n_scenarios, n_ahead),
        )  # (S, n_ahead)

        # Cumulative kappa paths starting from last_kappa
        kappa_paths = last_kappa + np.cumsum(innovations, axis=1)  # (S, n_ahead)

        # Expand tensor: (S, 1, n_ahead) * (1, N, 1) + (1, N, 1) -> (S, N, n_ahead)
        log_m_tensor = (
            self.alpha[np.newaxis, :, np.newaxis]
            + self.beta[np.newaxis, :, np.newaxis] * kappa_paths[:, np.newaxis, :]
        )
        m_tensor = np.exp(log_m_tensor)

        # Convert to mortality rates: q = 1 - exp(-m)
        q_tensor = 1.0 - np.exp(-m_tensor)
        q_tensor = np.clip(q_tensor, 0.0, 1.0)
        # Terminal age condition
        q_tensor[:, -1, :] = 1.0

        return q_tensor

    def to_dynamic_survival_curve(
        self,
        issue_age: int,
        n_years: Optional[int] = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Compute cohort dynamic survival curve _t p_x incorporating mortality improvement over time.

        Diagonal extraction across age-year matrix: policyholder aged (issue_age + t) at year (T + t).

        Args:
            issue_age: Age at policy issuance.
            n_years: Projection horizon. Defaults to (max_age - issue_age).

        Returns:
            Tuple of (durations, tpx_array).
        """
        self._check_fitted()
        min_age = int(self.ages[0])
        max_age = int(self.ages[-1])

        if issue_age < min_age or issue_age >= max_age:
            raise ValueError(f"issue_age {issue_age} outside fitted range [{min_age}, {max_age}].")

        if n_years is not None:
            if n_years <= 0:
                raise ValueError(f"n_years must be positive. Got {n_years}.")
            if issue_age + n_years > max_age:
                raise ValueError(
                    f"Requested projection horizon {issue_age} + {n_years} = {issue_age + n_years} "
                    f"exceeds fitted model maximum age {max_age}."
                )
            horizon = n_years
        else:
            horizon = max_age - issue_age

        # Forecast required future years
        q_future = self.forecast_expected(n_ahead=horizon)  # (N, horizon)

        # Diagonal cohort lookup: at duration t, age is (issue_age + t), year is t
        t_indices = np.arange(horizon)
        age_indices = (issue_age - min_age) + t_indices

        cohort_qx = q_future[age_indices, t_indices]
        cohort_px = np.clip(1.0 - cohort_qx, 0.0, 1.0)

        # Cumulative survival probability: _0 p_x = 1.0, _t p_x = prod_{k=0}^{t-1} p_{x+k}
        tpx = np.empty(horizon + 1, dtype=np.float64)
        tpx[0] = 1.0
        if horizon > 0:
            tpx[1:] = np.cumprod(cohort_px)

        durations = np.arange(horizon + 1, dtype=np.int64)
        return durations, tpx

    def forecast_summary(
        self,
        n_ahead: int = 30,
        n_scenarios: int = 1000,
        seed: Optional[int] = 42,
    ) -> LeeCarterForecastSummary:
        """Generate structured forecast summary for API and dashboard visualizers."""
        self._check_fitted()
        future_years = [int(self.years[-1] + h) for h in range(1, n_ahead + 1)]

        # 1. Simulate kappa paths
        rng = np.random.default_rng(seed)
        last_kappa = self.kappa[-1]
        innovations = rng.normal(loc=self.drift, scale=self.sigma_e, size=(n_scenarios, n_ahead))
        kappa_paths = last_kappa + np.cumsum(innovations, axis=1)

        mean_kappa = np.mean(kappa_paths, axis=0).round(4).tolist()
        p5_kappa = np.percentile(kappa_paths, 5, axis=0).round(4).tolist()
        p50_kappa = np.percentile(kappa_paths, 50, axis=0).round(4).tolist()
        p95_kappa = np.percentile(kappa_paths, 95, axis=0).round(4).tolist()

        # 2. Representative age mortality rate forecasts
        q_tensor = self.simulate_stochastic_tables(n_ahead=n_ahead, n_scenarios=n_scenarios, seed=seed)
        min_age = int(self.ages[0])
        rep_ages = [30, 50, 65, 80]
        sample_trajectories = {}

        for rep_age in rep_ages:
            if self.ages[0] <= rep_age <= self.ages[-1]:
                idx = rep_age - min_age
                rates_matrix = q_tensor[:, idx, :]  # (S, n_ahead)
                records = []
                for h_idx, yr in enumerate(future_years):
                    col = rates_matrix[:, h_idx]
                    records.append({
                        "year": yr,
                        "mean_qx": round(float(np.mean(col)), 6),
                        "p5_qx": round(float(np.percentile(col, 5)), 6),
                        "p50_qx": round(float(np.percentile(col, 50)), 6),
                        "p95_qx": round(float(np.percentile(col, 95)), 6),
                    })
                sample_trajectories[f"age_{rep_age}"] = records

        # 3. Life expectancy progression at age 65 (e_65)
        life_exp_records = []
        for step in [0, 5, 10, 20, n_ahead]:
            if step == 0:
                yr = int(self.years[-1])
                # Base static table expectation
                base_qx = 1.0 - np.exp(-np.exp(self.alpha))
                px = 1.0 - base_qx
                if 65 - min_age < len(px):
                    px_65 = px[65 - min_age:]
                    tpx_65 = np.cumprod(px_65)
                    e65 = float(np.sum(tpx_65) + 0.5)
                else:
                    e65 = 15.0
            else:
                yr = int(self.years[-1] + step)
                # Future cross-sectional table expectation
                future_kappa = last_kappa + self.drift * step
                future_qx = 1.0 - np.exp(-np.exp(self.alpha + self.beta * future_kappa))
                px = 1.0 - future_qx
                if 65 - min_age < len(px):
                    px_65 = px[65 - min_age:]
                    tpx_65 = np.cumprod(px_65)
                    e65 = float(np.sum(tpx_65) + 0.5)
                else:
                    e65 = 15.0

            life_exp_records.append({
                "year": yr,
                "period": f"+{step} yrs" if step > 0 else "Base Year",
                "life_expectancy_at_65": round(e65, 2),
            })

        return LeeCarterForecastSummary(
            forecast_years=future_years,
            kappa_forecast_mean=mean_kappa,
            kappa_forecast_p5=p5_kappa,
            kappa_forecast_p50=p50_kappa,
            kappa_forecast_p95=p95_kappa,
            sample_mortality_trajectories=sample_trajectories,
            life_expectancy_gains=life_exp_records,
        )

    def _check_fitted(self) -> None:
        if not self.is_fitted:
            raise RuntimeError("LeeCarterModel has not been fitted. Call fit() first.")

    @staticmethod
    def generate_synthetic_historical_matrix(
        ages: np.ndarray,
        years: np.ndarray,
        base_table: Optional[MortalityTable] = None,
        annual_improvement: float = 0.015,
        seed: int = 42,
    ) -> np.ndarray:
        """Generate realistic synthetic historical mortality surface matrix for testing and demonstration."""
        rng = np.random.default_rng(seed)
        n_ages = len(ages)
        n_years = len(years)

        if base_table is not None:
            # Use base table mortality rates
            min_a = base_table.min_age
            qx_base = np.array([base_table.get_tqx(int(a), 1) for a in ages], dtype=np.float64)
        else:
            # Gompertz-Makeham curve: m_x = A + B * c^x
            qx_base = np.clip(0.0005 + 0.00008 * (1.095 ** ages), 0.0, 1.0)

        # Convert to central death rates: m = -ln(1 - q)
        m_base = -np.log(1.0 - np.clip(qx_base, 1e-6, 0.999999))

        # Year progression matrix with downward trend and random fluctuations
        year_offsets = np.arange(n_years, dtype=np.float64)
        # Mortality declines over historical years
        trend_factors = np.exp(-annual_improvement * year_offsets)  # (T,)

        # Random noise per year and age
        noise = rng.normal(0.0, 0.02, size=(n_ages, n_years))

        m_matrix = m_base[:, np.newaxis] * trend_factors[np.newaxis, :] * np.exp(noise)
        return np.maximum(1e-6, m_matrix)
