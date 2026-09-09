"""
Advanced Economic Scenario Generator (ESG) Models.

Implements:
1. Hull-White 1-Factor Short-Rate Model with exact initial yield curve calibration
2. Cox-Ingersoll-Ross (CIR) Model with Feller condition checking and non-negativity preservation
"""

from __future__ import annotations

import math
from typing import Optional, Union

import numpy as np
from pydantic import BaseModel, Field

from actuary_engine.domain.curves.yield_curve import MarketYieldCurve
from actuary_engine.domain.stochastic._kernels import _simulate_cir_kernel


class HullWhiteParams(BaseModel):
    """Parameters for Hull-White 1-Factor Model."""

    a: float = Field(default=0.10, gt=0.0, le=2.0, description="Mean reversion speed a.")
    sigma: float = Field(default=0.015, gt=0.0, le=0.20, description="Short-rate volatility sigma.")


class CIRParams(BaseModel):
    """Parameters for Cox-Ingersoll-Ross (CIR) Model."""

    r0: float = Field(default=0.05, gt=0.0, le=0.50, description="Initial short rate r0.")
    kappa: float = Field(default=0.20, gt=0.0, le=3.0, description="Mean reversion speed kappa.")
    theta: float = Field(default=0.05, gt=0.0, le=0.50, description="Long-term mean rate theta.")
    sigma: float = Field(default=0.03, gt=0.0, le=0.50, description="Volatility of rate sigma.")

    @property
    def feller_ratio(self) -> float:
        """Feller condition ratio 2*kappa*theta / sigma^2. Must be > 1 for strict positivity."""
        return (2.0 * self.kappa * self.theta) / (self.sigma ** 2)

    @property
    def is_feller_satisfied(self) -> bool:
        """Whether Feller condition 2*kappa*theta > sigma^2 holds."""
        return self.feller_ratio > 1.0


class HullWhite1FModel:
    """Hull-White 1-Factor Short-Rate Model with exact yield curve calibration.

    Model SDE:
        dr_t = [theta(t) - a * r_t] dt + sigma * dW_t
        theta(t) = df(0,t)/dt + a * f(0,t) + (sigma^2 / (2a)) * (1 - exp(-2at))
    """

    __slots__ = ("yield_curve", "a", "sigma", "r0")

    def __init__(
        self,
        yield_curve: MarketYieldCurve,
        a: float = 0.10,
        sigma: float = 0.015,
    ) -> None:
        """Initialize Hull-White 1-Factor model.

        Args:
            yield_curve: MarketYieldCurve for exact calibration.
            a: Speed of mean reversion (default 0.10).
            sigma: Constant volatility (default 0.015).
        """
        if a <= 0.0:
            raise ValueError(f"Mean reversion 'a' must be positive. Got {a}.")
        if sigma <= 0.0:
            raise ValueError(f"Volatility 'sigma' must be positive. Got {sigma}.")

        self.yield_curve = yield_curve
        self.a = float(a)
        self.sigma = float(sigma)
        self.r0 = float(self.yield_curve.instantaneous_forward_rate(0.0))

    def theta(self, t: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        """Calibrated time-dependent drift theta(t).

        theta(t) = df(0,t)/dt + a * f(0,t) + (sigma^2 / (2a)) * (1 - exp(-2at))
        """
        t_arr = np.asarray(t, dtype=np.float64)
        is_scalar = t_arr.ndim == 0
        t_flat = np.atleast_1d(t_arr)

        f0_t = np.asarray(self.yield_curve.instantaneous_forward_rate(t_flat), dtype=np.float64)
        df_dt = np.asarray(self.yield_curve.forward_rate_derivative(t_flat), dtype=np.float64)

        vol_term = (self.sigma ** 2 / (2.0 * self.a)) * (1.0 - np.exp(-2.0 * self.a * t_flat))
        th = df_dt + self.a * f0_t + vol_term

        return float(th.flat[0]) if is_scalar else th

    def alpha(self, t: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        """Auxiliary function alpha(t) = f(0,t) + (sigma^2 / (2a^2)) * (1 - exp(-at))^2."""
        t_arr = np.asarray(t, dtype=np.float64)
        is_scalar = t_arr.ndim == 0
        t_flat = np.atleast_1d(t_arr)

        f0_t = np.asarray(self.yield_curve.instantaneous_forward_rate(t_flat), dtype=np.float64)
        vol_adj = (self.sigma ** 2 / (2.0 * (self.a ** 2))) * ((1.0 - np.exp(-self.a * t_flat)) ** 2)
        al = f0_t + vol_adj
        return float(al.flat[0]) if is_scalar else al

    def simulate_paths(
        self,
        n_years: int,
        n_scenarios: int = 1000,
        dt: float = 1.0,
        seed: Optional[int] = 42,
    ) -> np.ndarray:
        """Simulate short-rate paths using exact conditional Gaussian transitions.

        Args:
            n_years: Projection horizon in years.
            n_scenarios: Number of Monte Carlo paths.
            dt: Time step size (default 1.0 for annual steps).
            seed: Random seed.

        Returns:
            2D array of shape (n_scenarios, n_steps + 1) with simulated rates.
        """
        if n_years <= 0 or n_scenarios <= 0 or dt <= 0:
            raise ValueError("n_years, n_scenarios, and dt must be positive.")

        rng = np.random.default_rng(seed)
        n_steps = int(round(n_years / dt))
        time_grid = np.linspace(0.0, n_years, n_steps + 1)

        rates = np.empty((n_scenarios, n_steps + 1), dtype=np.float64)
        rates[:, 0] = self.r0

        # Exact transition variance per step: Var[r(t+dt)|r(t)] = (sigma^2 / 2a) * (1 - exp(-2a*dt))
        step_var = (self.sigma ** 2 / (2.0 * self.a)) * (1.0 - math.exp(-2.0 * self.a * dt))
        step_std = math.sqrt(step_var)
        decay = math.exp(-self.a * dt)

        alpha_vals = np.asarray(self.alpha(time_grid), dtype=np.float64)

        # Standard Gaussian random shocks
        shocks = rng.normal(0.0, 1.0, size=(n_scenarios, n_steps))

        for k in range(n_steps):
            # Conditional mean: r(t) * exp(-a*dt) + alpha(t+dt) - alpha(t) * exp(-a*dt)
            mean_k = rates[:, k] * decay + alpha_vals[k + 1] - alpha_vals[k] * decay
            rates[:, k + 1] = mean_k + step_std * shocks[:, k]

        return rates

    def analytical_zero_price(
        self,
        t: float,
        T: float,
        r_t: Union[float, np.ndarray],
    ) -> Union[float, np.ndarray]:
        """Compute analytical zero-coupon bond price P(t, T, r_t) under Hull-White model.

        P(t, T) = A(t, T) * exp(-B(t, T) * r_t)
        """
        if T < t:
            raise ValueError(f"Maturity T ({T}) must be >= observation time t ({t}).")
        if np.isclose(t, T):
            return 1.0 if np.ndim(r_t) == 0 else np.ones_like(r_t)

        tau = T - t
        B_tT = (1.0 - math.exp(-self.a * tau)) / self.a

        P_0_T = self.yield_curve.zero_price(T)
        P_0_t = self.yield_curve.zero_price(t)
        f0_t = self.yield_curve.instantaneous_forward_rate(t)

        log_ratio = math.log(max(1e-12, P_0_T)) - math.log(max(1e-12, P_0_t))
        convexity = (self.sigma ** 2 / (4.0 * self.a)) * (1.0 - math.exp(-2.0 * self.a * t)) * (B_tT ** 2)
        log_A = log_ratio + B_tT * f0_t - convexity

        p = np.exp(log_A - B_tT * np.asarray(r_t, dtype=np.float64))
        return float(p) if np.ndim(r_t) == 0 else p

    @staticmethod
    def discount_factor_paths(rate_paths: np.ndarray, dt: float = 1.0) -> np.ndarray:
        """Compute cumulative stochastic discount factors D(0, t) = exp(-sum r_k * dt).

        Args:
            rate_paths: Array of shape (n_scenarios, n_steps + 1).
            dt: Time step size.

        Returns:
            Array of shape (n_scenarios, n_steps + 1) with discount factors starting at 1.0.
        """
        n_scenarios, n_cols = rate_paths.shape
        df_paths = np.empty((n_scenarios, n_cols), dtype=np.float64)
        df_paths[:, 0] = 1.0

        cum_integral = np.cumsum(rate_paths[:, :-1] * dt, axis=1)
        df_paths[:, 1:] = np.exp(-cum_integral)
        return df_paths


class CIRModel:
    """Cox-Ingersoll-Ross (CIR) Square-Root Diffusion Model.

    Model SDE:
        dr_t = kappa * (theta - r_t) dt + sigma * sqrt(r_t) * dW_t
    """

    __slots__ = ("r0", "kappa", "theta", "sigma")

    def __init__(
        self,
        r0: float = 0.05,
        kappa: float = 0.20,
        theta: float = 0.05,
        sigma: float = 0.03,
    ) -> None:
        """Initialize CIR Model.

        Args:
            r0: Initial short rate.
            kappa: Speed of mean reversion.
            theta: Long-term mean rate.
            sigma: Square-root diffusion volatility.
        """
        if r0 <= 0 or kappa <= 0 or theta <= 0 or sigma <= 0:
            raise ValueError("All CIR parameters (r0, kappa, theta, sigma) must be strictly positive.")

        self.r0 = float(r0)
        self.kappa = float(kappa)
        self.theta = float(theta)
        self.sigma = float(sigma)

    @property
    def feller_ratio(self) -> float:
        """2*kappa*theta / sigma^2."""
        return (2.0 * self.kappa * self.theta) / (self.sigma ** 2)

    @property
    def is_feller_satisfied(self) -> bool:
        """True if 2*kappa*theta > sigma^2."""
        return self.feller_ratio > 1.0

    def simulate_paths(
        self,
        n_years: int,
        n_scenarios: int = 1000,
        dt: float = 1.0,
        seed: Optional[int] = 42,
    ) -> np.ndarray:
        """Simulate non-negative short-rate paths via Full Truncation Euler scheme.

        Args:
            n_years: Horizon in years.
            n_scenarios: Number of Monte Carlo scenario paths.
            dt: Time step size in years.
            seed: Random seed.

        Returns:
            2D array of shape (n_scenarios, n_steps + 1) with non-negative rates.
        """
        if n_years <= 0 or n_scenarios <= 0 or dt <= 0:
            raise ValueError("n_years, n_scenarios, and dt must be positive.")

        rng = np.random.default_rng(seed)
        n_steps = int(round(n_years / dt))

        rates = np.empty((n_scenarios, n_steps + 1), dtype=np.float64)
        rates[:, 0] = self.r0

        shocks = rng.normal(0.0, 1.0, size=(n_scenarios, n_steps))
        return _simulate_cir_kernel(
            r0=self.r0,
            kappa=self.kappa,
            theta=self.theta,
            sigma=self.sigma,
            dt=dt,
            n_steps=n_steps,
            n_scenarios=n_scenarios,
            random_shocks=shocks,
        )

    def analytical_zero_price(self, T: float) -> float:
        """Compute analytical zero-coupon bond price P(0, T) under CIR."""
        if T <= 1e-8:
            return 1.0

        gamma = math.sqrt(self.kappa ** 2 + 2.0 * (self.sigma ** 2))
        exp_gamma_T = math.exp(gamma * T)
        denom = (gamma + self.kappa) * (exp_gamma_T - 1.0) + 2.0 * gamma

        B_T = (2.0 * (exp_gamma_T - 1.0)) / denom
        numerator_A = 2.0 * gamma * math.exp((self.kappa + gamma) * T / 2.0)
        power_A = (2.0 * self.kappa * self.theta) / (self.sigma ** 2)
        A_T = (numerator_A / denom) ** power_A

        p = A_T * math.exp(-B_T * self.r0)
        return float(np.clip(p, 0.0, 1.0))

    @staticmethod
    def discount_factor_paths(rate_paths: np.ndarray, dt: float = 1.0) -> np.ndarray:
        """Compute cumulative stochastic discount factors D(0, t)."""
        n_scenarios, n_cols = rate_paths.shape
        df_paths = np.empty((n_scenarios, n_cols), dtype=np.float64)
        df_paths[:, 0] = 1.0

        cum_integral = np.cumsum(rate_paths[:, :-1] * dt, axis=1)
        df_paths[:, 1:] = np.exp(-cum_integral)
        return df_paths
