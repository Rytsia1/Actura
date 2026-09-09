"""
JIT-compiled numerical simulation kernels for Stochastic ESG and Monte Carlo rollouts.

Uses Numba's @njit(fastmath=True, nogil=True) for C-speed compilation with graceful
pure-Python fallback if Numba is unavailable.
"""

from __future__ import annotations

import math
from typing import Any, Callable

import numpy as np

try:
    from numba import njit  # type: ignore[import-untyped]
    HAS_NUMBA = True
except ImportError:  # pragma: no cover
    def njit(*args: Any, **kwargs: Any) -> Callable[..., Any]:
        """Fallback no-op decorator when Numba is not installed."""
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            return func
        if len(args) == 1 and callable(args[0]):
            return args[0]
        return decorator
    HAS_NUMBA = False


@njit(fastmath=True, nogil=True)
def _simulate_vasicek_kernel(
    r0: float,
    kappa: float,
    theta: float,
    sigma: float,
    dt: float,
    n_steps: int,
    n_scenarios: int,
    random_shocks: np.ndarray,
) -> np.ndarray:
    """Simulate short-rate paths under the Vasicek model using Euler-Maruyama propagation.

    dr_t = kappa * (theta - r_t) * dt + sigma * sqrt(dt) * Z_t
    """
    rates = np.empty((n_scenarios, n_steps + 1), dtype=np.float64)
    rates[:, 0] = r0

    sqrt_dt = math.sqrt(dt)
    drift_factor = kappa * dt
    diff_factor = sigma * sqrt_dt

    for k in range(n_steps):
        for s in range(n_scenarios):
            r_curr = rates[s, k]
            dr = drift_factor * (theta - r_curr) + diff_factor * random_shocks[s, k]
            rates[s, k + 1] = r_curr + dr

    return rates


@njit(fastmath=True, nogil=True)
def _simulate_cir_kernel(
    r0: float,
    kappa: float,
    theta: float,
    sigma: float,
    dt: float,
    n_steps: int,
    n_scenarios: int,
    random_shocks: np.ndarray,
) -> np.ndarray:
    """Simulate non-negative short-rate paths under the CIR model using Full Truncation."""
    rates = np.empty((n_scenarios, n_steps + 1), dtype=np.float64)
    rates[:, 0] = r0

    sqrt_dt = math.sqrt(dt)
    diff_factor = sigma * sqrt_dt

    for k in range(n_steps):
        for s in range(n_scenarios):
            r_curr = max(0.0, rates[s, k])
            dr = kappa * (theta - r_curr) * dt + diff_factor * math.sqrt(r_curr) * random_shocks[s, k]
            rates[s, k + 1] = max(0.0, r_curr + dr)

    return rates


@njit(fastmath=True, nogil=True)
def _stochastic_liability_kernel(
    discount_matrix: np.ndarray,
    death_claims: np.ndarray,
    maturity_benefits: np.ndarray,
    expenses: np.ndarray,
    premiums: np.ndarray,
    qx_array: np.ndarray,
    base_lapses: np.ndarray,
    rate_paths: np.ndarray,
    credited_rate: float,
    min_lapse: float,
    max_lapse: float,
    sensitivity: float,
    spread_threshold: float,
    use_dynamic_lapse: bool,
) -> np.ndarray:
    """Vectorized multi-scenario stochastic liability rollout kernel."""
    n_scenarios, n_cols = discount_matrix.shape
    max_t = n_cols - 1
    liabilities = np.zeros(n_scenarios, dtype=np.float64)

    for s in range(n_scenarios):
        inforce = 1.0
        pv_liability = 0.0

        for t in range(max_t):
            # Dynamic or static lapse
            w_t = base_lapses[t]
            if use_dynamic_lapse:
                spread = rate_paths[s, t] - credited_rate
                excess = spread - spread_threshold
                mult = 1.0 + (max_lapse / (1.0 + math.exp(-sensitivity * excess)) - (max_lapse / 2.0))
                w_t = min(max_lapse, max(min_lapse, w_t * mult))

            q_t = qx_array[t]
            # Decrements
            q_dep = q_t * (1.0 - 0.5 * w_t)
            w_dep = w_t * (1.0 - 0.5 * q_t)

            deaths = inforce * q_dep

            # Cash flows
            cf_claims = deaths * death_claims[t]
            cf_mat = inforce * maturity_benefits[t] if t == max_t - 1 else 0.0
            cf_exp = inforce * expenses[t]
            cf_prem = inforce * premiums[t]

            net_cf = cf_claims + cf_mat + cf_exp - cf_prem

            # Discount factor at EOY (t+1)
            disc = discount_matrix[s, t + 1]
            pv_liability += net_cf * disc

            # Inforce rollout
            inforce = inforce * max(0.0, 1.0 - q_dep - w_dep)

        liabilities[s] = pv_liability

    return liabilities
