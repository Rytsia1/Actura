"""
Stochastic valuation, Economic Scenario Generator (ESG), and Mortality Forecasting package.

Provides modules for:
- Vasicek Economic Scenario Generator (short-rate paths and discount factors)
- Hull-White 1-Factor Short-Rate Model with exact initial yield curve calibration
- Cox-Ingersoll-Ross (CIR) Model with Feller condition checking
- Dynamic policyholder lapse behavior (S-curve interest rate sensitivity)
- Monte Carlo Stochastic Valuation Engine (path-dependent liability rollout, VaR, CVaR)
- Lee-Carter Stochastic Mortality Improvement Model (SVD decomposition & RWD forecasting)
"""

from actuary_engine.domain.stochastic.dynamic_lapse import DynamicLapseModel, DynamicLapseParams
from actuary_engine.domain.stochastic.esg import VasicekESG, VasicekParams
from actuary_engine.domain.stochastic.esg_advanced import (
    CIRModel,
    CIRParams,
    HullWhite1FModel,
    HullWhiteParams,
)
from actuary_engine.domain.stochastic.lee_carter import (
    LeeCarterFitResult,
    LeeCarterForecastSummary,
    LeeCarterModel,
)
from actuary_engine.domain.stochastic.monte_carlo import (
    RiskMetricsResult,
    StochasticValuationEngine,
)

__all__ = [
    "VasicekParams",
    "VasicekESG",
    "HullWhiteParams",
    "HullWhite1FModel",
    "CIRParams",
    "CIRModel",
    "DynamicLapseParams",
    "DynamicLapseModel",
    "RiskMetricsResult",
    "StochasticValuationEngine",
    "LeeCarterModel",
    "LeeCarterFitResult",
    "LeeCarterForecastSummary",
]
