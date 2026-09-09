"""
Dynamic Policyholder Behavior: Interest-Rate-Sensitive Lapse Modeling.

Implements an actuarial S-curve (logistic/sigmoid) mapping interest rate
differentials between prevailing market rates and contractual credited rates
to dynamic policyholder surrender/lapse rates.

Mathematical Formulation:
    Let Δr = r_market - r_credited - spread_threshold
    S(Δr) = 1 / (1 + exp(-γ · Δr))
    w(r_market) = w_min + (w_max - w_min) · S(Δr)

Properties:
- Monotonically increasing with market interest rates (disintermediation risk)
- Strictly bounded in [w_min, w_max]
- Fully vectorized for multi-scenario, multi-period simulations
"""

from __future__ import annotations

from typing import Optional

import numpy as np
from pydantic import BaseModel, Field, model_validator


class DynamicLapseParams(BaseModel):
    """Parameters for the dynamic interest-rate-sensitive lapse S-curve.

    Attributes:
        base_lapse_rate: Baseline annual lapse rate when market rate equals credited rate.
        credited_rate: Contractual credited or guaranteed interest rate (r_cred).
        min_lapse_rate: Minimum asymptotic lapse rate (as market rate drops).
        max_lapse_rate: Maximum asymptotic lapse rate (as market rate surges).
        sensitivity: S-curve steepness / sensitivity parameter (γ > 0).
        spread_threshold: Interest rate differential threshold (midpoint offset x0).
    """

    base_lapse_rate: float = Field(
        default=0.04,
        ge=0.0,
        le=1.0,
        description="Base lapse rate when market rate equals credited rate.",
    )
    credited_rate: float = Field(
        default=0.04,
        description="Contractual or guaranteed credited rate.",
    )
    min_lapse_rate: float = Field(
        default=0.01,
        ge=0.0,
        le=1.0,
        description="Lower bound on lapse rate (floor).",
    )
    max_lapse_rate: float = Field(
        default=0.40,
        ge=0.0,
        le=1.0,
        description="Upper bound on lapse rate (cap).",
    )
    sensitivity: float = Field(
        default=25.0,
        gt=0.0,
        description="Steepness of the S-curve (γ > 0).",
    )
    spread_threshold: float = Field(
        default=0.0,
        description="Interest rate spread threshold / midpoint offset.",
    )

    @model_validator(mode="after")
    def validate_bounds(self) -> "DynamicLapseParams":
        """Ensure min <= base <= max."""
        if self.min_lapse_rate > self.max_lapse_rate:
            raise ValueError(
                f"min_lapse_rate ({self.min_lapse_rate}) cannot exceed "
                f"max_lapse_rate ({self.max_lapse_rate})."
            )
        if self.base_lapse_rate < self.min_lapse_rate or self.base_lapse_rate > self.max_lapse_rate:
            raise ValueError(
                f"base_lapse_rate ({self.base_lapse_rate}) must be within "
                f"[{self.min_lapse_rate}, {self.max_lapse_rate}]."
            )
        return self


class DynamicLapseModel:
    """Dynamic policyholder lapse evaluation engine.

    Maps market interest rates to dynamic lapse rates using a parameterized
    S-curve. Fully vectorized for high-performance Monte Carlo projections.

    Attributes:
        params: DynamicLapseParams instance.
    """

    __slots__ = ("params",)

    def __init__(self, params: Optional[DynamicLapseParams] = None) -> None:
        """Initialize dynamic lapse model.

        Args:
            params: Validated DynamicLapseParams (default parameters if omitted).
        """
        self.params = params or DynamicLapseParams()

    def compute_lapse_rates(
        self,
        market_rates: np.ndarray,
        base_rates: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """Compute dynamic lapse rates for an array of market interest rates.

        Supports 1D (vector) or 2D (scenarios × years) NumPy arrays.

        If ``base_rates`` is provided (e.g. duration-specific baseline rates),
        the S-curve acts as a dynamic multiplier centered around 1.0, scaled
        and clipped within [w_min, w_max]. Otherwise, the direct S-curve
        formula is applied.

        Args:
            market_rates: Array of market interest rates (e.g. from Vasicek ESG).
            base_rates: Optional duration-specific baseline lapse rates array.

        Returns:
            Array of dynamic lapse rates matching the shape of market_rates.
        """
        r_market = np.asarray(market_rates, dtype=np.float64)
        p = self.params

        # Interest rate spread: r_market - r_cred - threshold
        spread = r_market - p.credited_rate - p.spread_threshold

        # Numerically stable logistic function: 1 / (1 + exp(-γ * spread))
        # Prevent overflow for large |γ * spread|
        z = np.clip(p.sensitivity * spread, -50.0, 50.0)
        s_curve = 1.0 / (1.0 + np.exp(-z))

        if base_rates is not None:
            # Baseline duration vector is scaled by the dynamic factor
            # S-curve is 0.5 at spread=0; we normalize multiplier = 2 * s_curve
            base = np.asarray(base_rates, dtype=np.float64)
            multiplier = 2.0 * s_curve
            dynamic_rates = base * multiplier
            return np.clip(dynamic_rates, p.min_lapse_rate, p.max_lapse_rate)

        # Standard direct S-curve between w_min and w_max
        dynamic_rates = p.min_lapse_rate + (p.max_lapse_rate - p.min_lapse_rate) * s_curve
        return dynamic_rates

    def __repr__(self) -> str:
        return (
            f"DynamicLapseModel(credited={self.params.credited_rate:.2%}, "
            f"min={self.params.min_lapse_rate:.2%}, "
            f"max={self.params.max_lapse_rate:.2%}, "
            f"gamma={self.params.sensitivity:.1f})"
        )
