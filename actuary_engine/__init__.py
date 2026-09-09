"""
Actuary Engine — Modular Actuarial Valuation & Risk Simulation Engine.

A production-ready Python engine for life insurance liability modeling,
prospective reserves, stochastic risk simulation, market yield curves, and IFRS 17 / PSAK 117 valuation.
"""

__version__ = "0.3.0"

from actuary_engine.domain.curves.survival import SurvivalCurve
from actuary_engine.domain.curves.yield_curve import MarketYieldCurve
from actuary_engine.models.assumptions import (
    ExpenseAssumption,
    InterestAssumption,
    LapseAssumption,
    MortalityAssumption,
    ValuationAssumptions,
)
from actuary_engine.models.contracts import PolicyContract, ProductType
from actuary_engine.domain.pricing.annuity import AnnuityPricer
from actuary_engine.domain.pricing.insurance import InsurancePricer
from actuary_engine.domain.pricing.premium import LevelPremiumCalculator, PremiumResult
from actuary_engine.projections.cash_flow import CashFlowProjector
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
from actuary_engine.domain.tables.commutation import CommutationFunctions
from actuary_engine.domain.tables.mortality_table import MortalityTable
from actuary_engine.domain.tables.parsers import (
    TableParsingError,
    parse_csv_mortality_table,
    parse_mortality_file,
    parse_xtbml_mortality_table,
)
from actuary_engine.domain.tables.registry import TableMetadata, TableRegistry, table_registry
from actuary_engine.valuation.gpv import GrossPremiumValuation
from actuary_engine.valuation.ifrs17 import (
    IFRS17CohortClassification,
    IFRS17Engine,
    IFRS17InitialBalance,
    IFRS17ValuationResult,
)
from actuary_engine.valuation.portfolio import PortfolioSummary, PortfolioValuationEngine
from actuary_engine.valuation.reserves import ReserveCalculator
from actuary_engine.valuation.sensitivity import (
    CombinedScenarioResult,
    SensitivityBaselineMetrics,
    SensitivityEngine,
    SensitivityReport,
    TornadoItem,
)

__all__ = [
    "MortalityTable",
    "CommutationFunctions",
    "TableMetadata",
    "TableRegistry",
    "table_registry",
    "TableParsingError",
    "parse_csv_mortality_table",
    "parse_xtbml_mortality_table",
    "parse_mortality_file",
    "InsurancePricer",
    "AnnuityPricer",
    "LevelPremiumCalculator",
    "PremiumResult",
    "SurvivalCurve",
    "MarketYieldCurve",
    "CashFlowProjector",
    "InterestAssumption",
    "MortalityAssumption",
    "ExpenseAssumption",
    "LapseAssumption",
    "ValuationAssumptions",
    "PolicyContract",
    "ProductType",
    "ReserveCalculator",
    "GrossPremiumValuation",
    "PortfolioValuationEngine",
    "PortfolioSummary",
    "IFRS17Engine",
    "IFRS17CohortClassification",
    "IFRS17InitialBalance",
    "IFRS17ValuationResult",
    "SensitivityEngine",
    "SensitivityReport",
    "SensitivityBaselineMetrics",
    "TornadoItem",
    "CombinedScenarioResult",
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

