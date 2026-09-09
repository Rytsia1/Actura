"""
Economic Scenario Generator (ESG) using the Vasicek Short-Rate Model.

Provides:
- ``VasicekParams``: Pydantic v2 data model for model parameters
- ``VasicekESG``: Vectorized scenario generator implementing Euler-Maruyama
  and exact Gaussian transition steps, plus stochastic cumulative discount factor computation.

Mathematical Formulation:
    dr_t = κ(θ - r_t)dt + σ dW_t

Discrete Euler-Maruyama:
    r_{t+1} = r_t + κ(θ - r_t)Δt + σ √(Δt) Z_t,  where Z_t ~ N(0, 1)

Exact Gaussian Transition:
    r_{t+1} = r_t e^{-κΔt} + θ(1 - e^{-κΔt}) + σ √((1 - e^{-2κΔt}) / (2κ)) Z_t

Stochastic Discount Factor:
    D(t) = exp(-∫_0^t r_s ds) ≈ exp(-Σ_{k=0}^{t-1} r_k Δt)
"""

from __future__ import annotations

from typing import Optional

import numpy as np
from pydantic import BaseModel, Field, model_validator

from actuary_engine.domain.stochastic._kernels import _simulate_vasicek_kernel


class VasicekParams(BaseModel):
    """Parameters for the Vasicek one-factor short-rate model.

    Attributes:
        r0: Initial instantaneous short rate (e.g. 0.05 for 5%).
        kappa: Speed of mean reversion (κ > 0).
        theta: Long-term mean short rate (θ).
        sigma: Instantaneous volatility of short rate (σ ≥ 0).
    """

    r0: float = Field(
        ...,
        description="Initial short rate at t=0.",
    )
    kappa: float = Field(
        ...,
        gt=0.0,
        description="Speed of mean reversion (κ > 0).",
    )
    theta: float = Field(
        ...,
        description="Long-term mean short rate (θ).",
    )
    sigma: float = Field(
        ...,
        ge=0.0,
        description="Short-rate volatility (σ ≥ 0).",
    )

    @model_validator(mode="after")
    def validate_params(self) -> "VasicekParams":
        """Ensure parameter reasonableness."""
        if self.kappa <= 0.0:
            raise ValueError(f"kappa must be positive. Got {self.kappa}.")
        if self.sigma < 0.0:
            raise ValueError(f"sigma must be non-negative. Got {self.sigma}.")
        return self


class VasicekESG:
    """Vectorized Vasicek Economic Scenario Generator.

    Simulates short-rate paths across Monte Carlo scenarios and computes
    stochastic path-dependent discount factors.

    Attributes:
        params: Vasicek model parameters.
        seed: Optional master random seed for reproducible simulations.
    """

    __slots__ = ("params", "seed")

    def __init__(
        self,
        params: VasicekParams,
        seed: Optional[int] = None,
    ) -> None:
        """Initialize ESG.

        Args:
            params: Validated VasicekParams instance.
            seed: Optional default random seed for NumPy RNG.
        """
        self.params = params
        self.seed = seed

    def simulate_paths(
        self,
        n_scenarios: int,
        n_years: int,
        dt: float = 1.0,
        method: str = "euler",
        seed: Optional[int] = None,
    ) -> np.ndarray:
        """Simulate short-rate paths across scenarios.

        Generates a 2D NumPy array of shape ``(n_scenarios, n_steps + 1)``,
        where column 0 is the initial rate r0 at time t=0.

        Args:
            n_scenarios: Number of Monte Carlo scenario paths.
            n_years: Horizon in years.
            dt: Time step size in years (default 1.0 for annual).
            method: Discretization method ('euler' or 'exact').
            seed: Optional scenario-specific seed override.

        Returns:
            Array of shape (n_scenarios, n_steps + 1) containing short rates.

        Raises:
            ValueError: If inputs are invalid or method is unsupported.
        """
        if n_scenarios <= 0:
            raise ValueError(f"n_scenarios must be positive. Got {n_scenarios}.")
        if n_years <= 0:
            raise ValueError(f"n_years must be positive. Got {n_years}.")
        if dt <= 0.0:
            raise ValueError(f"dt must be positive. Got {dt}.")

        effective_seed = seed if seed is not None else self.seed
        rng = np.random.default_rng(effective_seed)

        n_steps = int(round(n_years / dt))
        paths = np.empty((n_scenarios, n_steps + 1), dtype=np.float64)
        paths[:, 0] = self.params.r0

        kappa = self.params.kappa
        theta = self.params.theta
        sigma = self.params.sigma

        # Standard normal random shocks for all scenarios and steps
        # Shape: (n_scenarios, n_steps)
        if sigma > 0.0:
            z = rng.standard_normal((n_scenarios, n_steps))
        else:
            z = np.zeros((n_scenarios, n_steps), dtype=np.float64)

        if method == "euler":
            # JIT-compiled Euler-Maruyama propagation kernel
            paths = _simulate_vasicek_kernel(
                r0=self.params.r0,
                kappa=kappa,
                theta=theta,
                sigma=sigma,
                dt=dt,
                n_steps=n_steps,
                n_scenarios=n_scenarios,
                random_shocks=z,
            )

        elif method == "exact":
            # Exact Gaussian solution of the SDE over interval dt
            exp_kdt = np.exp(-kappa * dt)
            cond_mean_factor = 1.0 - exp_kdt
            if kappa > 1e-12:
                cond_var = (sigma ** 2 / (2.0 * kappa)) * (1.0 - np.exp(-2.0 * kappa * dt))
                cond_std = np.sqrt(max(cond_var, 0.0))
            else:
                cond_std = sigma * np.sqrt(dt)

            for t in range(n_steps):
                r_t = paths[:, t]
                paths[:, t + 1] = r_t * exp_kdt + theta * cond_mean_factor + cond_std * z[:, t]

        else:
            raise ValueError(
                f"Unsupported simulation method: '{method}'. Choose 'euler' or 'exact'."
            )

        return paths

    def compute_discount_factors(
        self,
        short_rate_paths: np.ndarray,
        dt: float = 1.0,
        compounding: str = "continuous",
    ) -> np.ndarray:
        """Compute stochastic cumulative discount factors from short-rate paths.

        Returns an array of shape ``(n_scenarios, n_steps + 1)`` where:
        - D[:, 0] = 1.0 (discount factor at t=0)
        - D[:, t] = discount factor for cash flow occurring at time t*dt

        Under continuous compounding:
            D(t) = exp(-Σ_{k=0}^{t-1} r_k dt)

        Under discrete annual compounding:
            D(t) = Π_{k=0}^{t-1} (1 + r_k dt)^{-1}

        Args:
            short_rate_paths: 2D array (n_scenarios, n_steps + 1) of short rates.
            dt: Time step size in years.
            compounding: 'continuous' or 'discrete'.

        Returns:
            2D array of discount factors of identical shape.
        """
        if short_rate_paths.ndim != 2:
            raise ValueError(
                f"short_rate_paths must be 2-dimensional. Got shape {short_rate_paths.shape}."
            )

        n_scenarios, n_cols = short_rate_paths.shape
        discount_factors = np.empty_like(short_rate_paths)
        discount_factors[:, 0] = 1.0

        rates_active = short_rate_paths[:, :-1]  # Rates applied during each step

        if compounding == "continuous":
            # Cumulative integral of r_t dt
            cumulative_rate = np.cumsum(rates_active * dt, axis=1)
            discount_factors[:, 1:] = np.exp(-cumulative_rate)

        elif compounding in ("discrete", "annual"):
            # Product of 1 / (1 + r_k dt)
            period_discount = 1.0 / (1.0 + rates_active * dt)
            discount_factors[:, 1:] = np.cumprod(period_discount, axis=1)

        else:
            raise ValueError(
                f"Unsupported compounding '{compounding}'. Choose 'continuous' or 'discrete'."
            )

        return discount_factors

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

    def analytical_mean(self, t: float) -> float:
        """Compute the theoretical analytical expectation E[r(t)].

        E[r(t)] = r0 * e^(-κt) + θ * (1 - e^(-κt))

        Args:
            t: Time in years.

        Returns:
            Expected short rate at time t.
        """
        kappa = self.params.kappa
        theta = self.params.theta
        r0 = self.params.r0
        return float(r0 * np.exp(-kappa * t) + theta * (1.0 - np.exp(-kappa * t)))

    def analytical_variance(self, t: float) -> float:
        """Compute the theoretical analytical variance Var(r(t)).

        Var(r(t)) = (σ^2 / (2κ)) * (1 - e^(-2κt))

        Args:
            t: Time in years.

        Returns:
            Variance of short rate at time t.
        """
        kappa = self.params.kappa
        sigma = self.params.sigma
        if kappa < 1e-12:
            return float(sigma ** 2 * t)
        return float((sigma ** 2 / (2.0 * kappa)) * (1.0 - np.exp(-2.0 * kappa * t)))

    def __repr__(self) -> str:
        return (
            f"VasicekESG(r0={self.params.r0:.4f}, kappa={self.params.kappa:.4f}, "
            f"theta={self.params.theta:.4f}, sigma={self.params.sigma:.4f})"
        )
