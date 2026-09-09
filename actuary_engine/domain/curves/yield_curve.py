"""
Market Yield Curve and Term Structure of Interest Rates.

Provides the ``MarketYieldCurve`` class for interpolating spot rates, zero-coupon bond
discount factors P(0, t), instantaneous forward rates f(0, t), and forward rate derivatives
using cubic spline, linear, or Nelson-Siegel-Svensson (NSS) representations.
"""

from __future__ import annotations

from typing import Optional, Union

import numpy as np
from scipy.interpolate import CubicSpline


class MarketYieldCurve:
    """Market Yield Curve and Term Structure Model.

    Attributes:
        tenors: Array of pillar maturities in years.
        rates: Array of annual continuously-compounded spot rates.
        method: Interpolation methodology ('spline', 'linear', or 'flat').
    """

    __slots__ = ("tenors", "rates", "method", "_spline", "_r0")

    def __init__(
        self,
        tenors: np.ndarray,
        rates: np.ndarray,
        method: str = "spline",
    ) -> None:
        """Initialize MarketYieldCurve.

        Args:
            tenors: Array of maturities (e.g., [0.5, 1, 2, 5, 10, 20, 30]).
            rates: Array of spot yields (e.g., [0.045, 0.048, 0.051, ...]).
            method: Interpolation method ('spline', 'linear', 'flat').
        """
        tenors_arr = np.asarray(tenors, dtype=np.float64)
        rates_arr = np.asarray(rates, dtype=np.float64)

        if len(tenors_arr) != len(rates_arr):
            raise ValueError(f"Tenors ({len(tenors_arr)}) and rates ({len(rates_arr)}) must have equal length.")
        if len(tenors_arr) == 0:
            raise ValueError("Tenors and rates cannot be empty.")
        if np.any(tenors_arr <= 0.0):
            raise ValueError("All tenors must be strictly positive.")

        # Sort by tenor
        sort_idx = np.argsort(tenors_arr)
        self.tenors = tenors_arr[sort_idx]
        self.rates = rates_arr[sort_idx]
        self.method = method.lower()

        # Add point at t=0 for smooth anchoring if needed
        t_nodes = np.insert(self.tenors, 0, 0.0)
        r_nodes = np.insert(self.rates, 0, self.rates[0])
        self._r0 = float(self.rates[0])

        if self.method == "spline" and len(t_nodes) >= 3:
            self._spline = CubicSpline(t_nodes, r_nodes, bc_type="natural", extrapolate=True)
        else:
            self._spline = None

    def spot_rate(self, t: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        """Compute continuously-compounded spot rate y(t).

        Args:
            t: Maturity tenor in years (scalar or array).

        Returns:
            Spot yield y(t).
        """
        t_arr = np.asarray(t, dtype=np.float64)
        is_scalar = t_arr.ndim == 0
        t_flat = np.atleast_1d(t_arr)

        if self._spline is not None:
            # Evaluate cubic spline with flat extrapolation at extremities
            max_t = self.tenors[-1]
            t_clamped = np.clip(t_flat, 0.0, max_t)
            rates = self._spline(t_clamped)
            # Beyond max tenor, keep flat spot yield
            rates = np.where(t_flat > max_t, float(self.rates[-1]), rates)
        else:
            # Linear interpolation
            rates = np.interp(t_flat, self.tenors, self.rates, left=self._r0, right=float(self.rates[-1]))

        # Guarantee non-negative rate floor
        rates = np.maximum(0.0001, rates)
        return float(rates[0]) if is_scalar else rates

    def zero_price(self, t: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        """Compute zero-coupon discount factor P(0, t) = exp(-y(t) * t).

        Args:
            t: Maturity tenor in years.

        Returns:
            Discount factor P(0, t).
        """
        t_arr = np.asarray(t, dtype=np.float64)
        is_scalar = t_arr.ndim == 0
        t_flat = np.atleast_1d(t_arr)

        y = self.spot_rate(t_flat)
        # P(0, 0) = 1.0
        p = np.where(t_flat <= 1e-8, 1.0, np.exp(-y * t_flat))
        p = np.clip(p, 0.0, 1.0)
        return float(p[0]) if is_scalar else p

    def instantaneous_forward_rate(self, t: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        """Compute instantaneous forward rate f(0, t) = -d/dt ln P(0, t) = y(t) + t * y'(t).

        Args:
            t: Tenor in years.

        Returns:
            Instantaneous forward rate f(0, t).
        """
        t_arr = np.asarray(t, dtype=np.float64)
        is_scalar = t_arr.ndim == 0
        t_flat = np.atleast_1d(t_arr)

        eps = 1e-4
        t_plus = np.maximum(0.0, t_flat + eps)
        t_minus = np.maximum(0.0, t_flat - eps)

        p_plus = self.zero_price(t_plus)
        p_minus = self.zero_price(t_minus)

        log_p_diff = np.log(np.maximum(1e-12, p_minus)) - np.log(np.maximum(1e-12, p_plus))
        f = log_p_diff / (t_plus - t_minus)
        f = np.maximum(0.0001, f)

        return float(f[0]) if is_scalar else f

    def forward_rate_derivative(self, t: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        """Compute partial derivative of forward rate with respect to maturity: df(0, t)/dt.

        Args:
            t: Tenor in years.

        Returns:
            Derivative df(0, t)/dt.
        """
        t_arr = np.asarray(t, dtype=np.float64)
        is_scalar = t_arr.ndim == 0
        t_flat = np.atleast_1d(t_arr)

        eps = 1e-4
        f_plus = self.instantaneous_forward_rate(t_flat + eps)
        f_minus = self.instantaneous_forward_rate(np.maximum(0.0, t_flat - eps))

        df_dt = np.asarray((f_plus - f_minus) / (2.0 * eps), dtype=np.float64)
        return float(df_dt.flat[0]) if is_scalar else df_dt

    @classmethod
    def from_flat_rate(cls, rate: float = 0.05) -> MarketYieldCurve:
        """Create a flat yield curve with constant spot rate."""
        tenors = np.array([0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 50.0])
        rates = np.full_like(tenors, float(rate))
        return cls(tenors, rates, method="flat")

    @classmethod
    def from_us_treasury(cls) -> MarketYieldCurve:
        """Standard US Treasury benchmark yield curve (representative)."""
        tenors = np.array([0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 20.0, 30.0])
        rates = np.array([0.052, 0.050, 0.047, 0.044, 0.042, 0.041, 0.042, 0.043, 0.046, 0.045])
        return cls(tenors, rates, method="spline")

    @classmethod
    def from_sovereign_sun(cls) -> MarketYieldCurve:
        """Indonesian Sovereign Bond (Surat Utang Negara - SUN) benchmark yield curve."""
        tenors = np.array([0.5, 1.0, 2.0, 5.0, 7.0, 10.0, 15.0, 20.0, 30.0])
        rates = np.array([0.061, 0.063, 0.064, 0.066, 0.067, 0.068, 0.069, 0.070, 0.071])
        return cls(tenors, rates, method="spline")
