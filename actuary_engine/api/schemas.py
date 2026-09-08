"""
Pydantic Request and Response schemas for the Actuarial Valuation API.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional, Union
from pydantic import BaseModel, Field, field_validator

from actuary_engine.models.assumptions import ExpenseAssumption, LapseAssumption
from actuary_engine.models.contracts import ProductType
from actuary_engine.stochastic.dynamic_lapse import DynamicLapseParams
from actuary_engine.stochastic.esg import VasicekParams


# ────────────────────────────────────────────────────────────
# Assumption Management Schemas
# ────────────────────────────────────────────────────────────

class AssumptionType(str, Enum):
    MORTALITY = "mortality"
    LAPSE = "lapse"
    EXPENSE = "expense"
    INTEREST = "interest"
    INFLATION = "inflation"
    ECONOMIC = "economic"

class AssumptionCreate(BaseModel):
    """Schema for creating a completely new assumption."""
    name: str = Field(..., description="Name of the assumption.")
    type: AssumptionType = Field(..., description="Category of the assumption.")
    description: str = Field(default="", description="Detailed description.")
    source: str = Field(default="", description="Source or methodology reference.")
    effective_date: str = Field(default="", description="Effective date (YYYY-MM-DD).")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Configuration parameters.")

class AssumptionVersionCreate(BaseModel):
    """Schema for creating a new version of an existing assumption."""
    name: Optional[str] = Field(default=None, description="Name (if changed).")
    type: Optional[AssumptionType] = Field(default=None, description="Category (if changed).")
    description: str = Field(default="", description="Detailed description.")
    source: str = Field(default="", description="Source or methodology reference.")
    effective_date: str = Field(default="", description="Effective date (YYYY-MM-DD).")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Configuration parameters.")

class AssumptionRead(BaseModel):
    """Schema for returning assumption records."""
    id: str
    version: int
    name: str
    type: AssumptionType
    description: str
    source: str
    effective_date: str
    status: str
    parameters: dict[str, Any]
    created_by: str
    created_at: float
    updated_at: float

class AssumptionReference(BaseModel):
    """Reference tracking exactly which version of an assumption was used."""
    assumption_id: str
    version: int

class AssumptionStatusUpdate(BaseModel):
    status: str = Field(..., description="ACTIVE or INACTIVE")


# ────────────────────────────────────────────────────────────
# Scenario Management Schemas
# ────────────────────────────────────────────────────────────

class ScenarioAssumptionOverrides(BaseModel):
    """Assumption variations and shocks relative to a base model."""
    interest_rate_bps: Optional[float] = Field(
        default=None, description="Shift in discount rate basis points, e.g. -100 for -100 bps."
    )
    interest_rate_delta: Optional[float] = Field(
        default=None, description="Direct additive shift in annual interest rate, e.g. -0.01."
    )
    interest_rate_override: Optional[float] = Field(
        default=None, description="Absolute replacement for annual interest rate."
    )
    mortality_multiplier: Optional[float] = Field(
        default=None, description="Multiplicative factor on mortality rates, e.g. 1.10 for +10%."
    )
    mortality_table_id: Optional[str] = Field(
        default=None, description="Alternative mortality table ID."
    )
    lapse_multiplier: Optional[float] = Field(
        default=None, description="Multiplicative factor on lapse rates, e.g. 1.20."
    )
    lapse_rate_delta: Optional[float] = Field(
        default=None, description="Additive shift on annual lapse rates, e.g. 0.05 for +5%."
    )
    lapse_override: Optional[float] = Field(
        default=None, description="Absolute replacement for flat annual lapse rate."
    )
    expense_multiplier: Optional[float] = Field(
        default=None, description="Multiplicative factor on expenses, e.g. 1.10 for +10%."
    )
    expense_inflation_pct: Optional[float] = Field(
        default=None, description="Expense inflation percentage."
    )
    custom_overrides: Optional[dict[str, Any]] = Field(
        default_factory=dict, description="Custom extensible overrides."
    )


class ScenarioCreate(BaseModel):
    """Schema for creating a new actuarial scenario."""
    id: Optional[str] = Field(default=None, description="Optional unique identifier (auto-generated if omitted).")
    name: str = Field(..., description="Descriptive name of the scenario.")
    description: str = Field(default="", description="Detailed narrative of scenario purpose and assumptions.")
    base_model_id: str = Field(default="default-endowment", description="Reference identifier to immutable base model.")
    overrides: ScenarioAssumptionOverrides = Field(
        default_factory=ScenarioAssumptionOverrides, description="Assumption overrides relative to base model."
    )
    status: str = Field(default="ACTIVE", description="Scenario status (ACTIVE, DRAFT, ARCHIVED).")


class ScenarioUpdate(BaseModel):
    """Schema for updating an existing scenario."""
    name: Optional[str] = Field(default=None, description="Updated name.")
    description: Optional[str] = Field(default=None, description="Updated description.")
    base_model_id: Optional[str] = Field(default=None, description="Updated base model reference.")
    overrides: Optional[ScenarioAssumptionOverrides] = Field(default=None, description="Updated overrides.")
    status: Optional[str] = Field(default=None, description="Updated status.")


class ScenarioRead(BaseModel):
    """Schema for scenario response record."""
    id: str
    name: str
    description: str
    base_model_id: str
    overrides: dict[str, Any]
    status: str
    created_at: float
    updated_at: float


class BaseModelCreate(BaseModel):
    """Schema for defining a reusable base actuarial model."""
    id: Optional[str] = Field(default=None, description="Unique model identifier.")
    name: str = Field(..., description="Model name.")
    description: str = Field(default="", description="Model description.")
    product_type: ProductType = Field(default=ProductType.ENDOWMENT, description="Insurance product type.")
    issue_age: int = Field(default=30, ge=0, description="Policyholder issue age.")
    term: Optional[int] = Field(default=20, gt=0, description="Policy term in years.")
    sum_assured: float = Field(default=1_000_000.0, gt=0.0, description="Sum assured.")
    premium_paying_term: Optional[int] = Field(default=None, gt=0, description="Premium paying term.")
    interest_rate: float = Field(default=0.05, ge=0.0, le=0.50, description="Baseline annual interest rate.")
    table_id: str = Field(default="soa_ilt", description="Mortality table identifier.")
    expense: Optional[ExpenseAssumption] = Field(default=None, description="Baseline expense loadings.")
    lapse: Optional[LapseAssumption] = Field(default=None, description="Baseline lapse assumptions.")
    gross_premium: Optional[float] = Field(default=None, gt=0.0, description="Fixed gross premium override.")


class BaseModelRead(BaseModel):
    """Schema for reading base model information."""
    id: str
    name: str
    description: str
    product_type: str
    issue_age: int
    term: Optional[int]
    sum_assured: float
    premium_paying_term: Optional[int]
    interest_rate: float
    table_id: str
    expense: dict[str, Any]
    lapse: dict[str, Any]
    gross_premium: Optional[float]
    created_at: float
    updated_at: float


class ScenarioValidationResult(BaseModel):
    """Result of validating scenario overrides against actuarial domain rules."""
    scenario_id: str
    is_valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    effective_assumptions: dict[str, Any] = Field(default_factory=dict)


class ScenarioExecutionResponse(BaseModel):
    """Response payload produced by executing a scenario valuation."""
    scenario_id: str
    scenario_name: str
    base_model_id: str
    valuation_type: str = "Scenario"
    status: str = "COMPLETED"
    job_id: str
    effective_interest_rate: float
    effective_mortality_multiplier: float
    effective_lapse_rate: float
    effective_expense_multiplier: float
    bel: float
    baseline_bel: Optional[float] = None
    delta_bel: Optional[float] = None
    pct_change_bel: Optional[float] = None
    csm: Optional[float] = None
    profit_loss: Optional[float] = None
    annual_net_premium: float
    annual_gross_premium: float
    nsp: float
    annuity_factor: float
    reserve_profile: list[dict[str, Any]] = Field(default_factory=list)
    cash_flows: list[dict[str, Any]] = Field(default_factory=list)
    reproducibility: dict[str, Any] = Field(default_factory=dict)


# ────────────────────────────────────────────────────────────
# First-Class Sensitivity Analysis Schemas (Task 10)
# ────────────────────────────────────────────────────────────

class SensitivityShockConfig(BaseModel):
    """Configurable shock ranges across supported actuarial risk factors."""
    mortality_shocks: Optional[list[float]] = Field(
        default=None,
        description="Relative shifts for mortality (e.g., [-0.20, -0.10, 0.0, 0.10, 0.20]).",
    )
    interest_shocks_bps: Optional[list[float]] = Field(
        default=None,
        description="Basis point shifts for discount rate (e.g., [-200, -100, 0, 100, 200]).",
    )
    lapse_shocks: Optional[list[float]] = Field(
        default=None,
        description="Relative shifts for lapse decrements (e.g., [-0.20, -0.10, 0.0, 0.10, 0.20]).",
    )
    expense_shocks: Optional[list[float]] = Field(
        default=None,
        description="Relative shifts for expense parameters (e.g., [-0.20, -0.10, 0.0, 0.10, 0.20]).",
    )


class SensitivityAnalysisRequest(BaseModel):
    """Request payload for running first-class sensitivity analysis against a base model."""
    base_model_id: str = Field(default="default-endowment", description="Base model to analyze.")
    target_metric: Literal["bel", "csm", "profit_loss"] = Field(
        default="bel",
        description="Target valuation metric to analyze and rank drivers for.",
    )
    shocks: Optional[SensitivityShockConfig] = Field(
        default=None,
        description="Configurable shock ranges. Uses actuarial standard defaults if omitted.",
    )


class SensitivityGridPoint(BaseModel):
    """Single evaluated shock point in the sensitivity grid."""
    variable: str = Field(..., description="Assumption variable (mortality, discount_rate, lapse, expense).")
    variable_label: str = Field(..., description="Human-readable variable label.")
    shock_label: str = Field(..., description="Formatted shock label (e.g. '+10%', '-100 bps', 'Base').")
    shock_value: float = Field(..., description="Numeric shock magnitude.")
    resulting_metric: float = Field(..., description="Resulting value for target_metric.")
    absolute_change: float = Field(..., description="Absolute delta (Metric_shocked - Metric_base).")
    percentage_change: float = Field(..., description="Percentage shift relative to base metric.")
    bel: float = Field(..., description="Best Estimate Liability under this shock.")
    csm: float = Field(..., description="Contractual Service Margin under this shock.")
    profit_loss: float = Field(..., description="PV of underwriting profit under this shock.")


class SensitivityDriverItem(BaseModel):
    """Valuation driver summary ranking assumptions by absolute impact."""
    rank: int = Field(..., description="Impact rank (1 = highest driver).")
    variable: str = Field(..., description="Assumption variable key.")
    variable_label: str = Field(..., description="Human-readable assumption name.")
    swing: float = Field(..., description="Max swing: max(metric) - min(metric).")
    swing_pct: float = Field(..., description="Swing as percentage of base metric value.")
    max_abs_change: float = Field(..., description="Maximum absolute shift from baseline.")
    min_metric: float = Field(..., description="Lowest metric value across tested shocks.")
    max_metric: float = Field(..., description="Highest metric value across tested shocks.")
    most_adverse_shock: str = Field(..., description="Shock causing the most adverse valuation outcome.")
    most_favorable_shock: str = Field(..., description="Shock causing the most favorable valuation outcome.")


class SensitivityAnalysisResponse(BaseModel):
    """Complete response payload for first-class sensitivity analysis."""
    analysis_id: str
    base_model_id: str
    base_model_name: str
    target_metric: str
    base_metric_value: float
    base_bel: float
    base_csm: float
    base_profit_loss: float
    drivers: list[SensitivityDriverItem] = Field(default_factory=list)
    grid_points: list[SensitivityGridPoint] = Field(default_factory=list)
    job_id: str
    created_at: float
    reproducibility: dict[str, Any] = Field(default_factory=dict)


# ────────────────────────────────────────────────────────────
# Run Comparison Schemas (Task 11)
# ────────────────────────────────────────────────────────────

class RunComparisonRequest(BaseModel):
    """Request to compare two valuation runs."""
    run_a_id: str = Field(..., description="Job ID of the baseline run (Run A).")
    run_b_id: str = Field(..., description="Job ID of the comparison run (Run B).")


class MetricComparisonItem(BaseModel):
    """Comparative valuation metric row showing Run A, Run B, and deltas."""
    metric_key: str
    metric_label: str
    category: str = "liability"  # liability, cash_flow, risk, profitability
    value_a: Optional[float] = None
    value_b: Optional[float] = None
    absolute_delta: Optional[float] = None
    percentage_delta: Optional[float] = None
    unit: str = "$"


class ConfigComparisonItem(BaseModel):
    """Comparative configuration parameter showing Run A, Run B, and change status."""
    element_key: str
    label: str
    value_a: Any
    value_b: Any
    has_changed: bool
    change_summary: str


class RunSummaryInfo(BaseModel):
    """High-level summary of a valuation run for comparison header."""
    job_id: str
    valuation_type: str
    status: str
    created_at: Optional[float] = None
    completed_at: Optional[float] = None
    duration_seconds: Optional[float] = None
    model_name: Optional[str] = None
    scenario_name: Optional[str] = None
    engine_version: Optional[str] = None


class RunComparisonResponse(BaseModel):
    """Complete comparison payload between two valuation runs."""
    run_a: RunSummaryInfo
    run_b: RunSummaryInfo
    metrics: list[MetricComparisonItem] = Field(default_factory=list)
    configurations: list[ConfigComparisonItem] = Field(default_factory=list)
    changed_elements: list[str] = Field(default_factory=list)
    summary_explanation: str





# ────────────────────────────────────────────────────────────
# Table Registry Schemas
# ───────────────────────────────────────────────────────────

class TableUploadResponse(BaseModel):
    """Response returned upon uploading and registering a custom mortality table."""

    status: str = Field(default="success", description="Upload operation status.")
    table_id: str = Field(..., description="Assigned table identifier.")
    table_name: str = Field(..., description="Human-readable table name.")
    min_age: int = Field(..., description="Minimum issue age available.")
    max_age: int = Field(..., description="Maximum age (omega).")
    rows_count: int = Field(..., description="Number of age cohorts in table.")
    is_builtin: bool = Field(default=False, description="Whether table is bundled system table.")
    sample_qx: dict[str, float] = Field(default_factory=dict, description="Sample mortality rates.")


class TableListItem(BaseModel):
    """Summary item for table catalogue listings."""

    table_id: str
    name: str
    description: str
    min_age: int
    max_age: int
    omega: int
    radix: int
    is_builtin: bool
    sample_qx: dict[str, float]


# ────────────────────────────────────────────────────────────
# Valuation Request & Response Schemas
# ────────────────────────────────────────────────────────────

class DeterministicValuationRequest(BaseModel):
    """Request payload for Level 1-3 deterministic life insurance valuation."""

    product_type: ProductType = Field(
        default=ProductType.ENDOWMENT, description="Insurance product type."
    )
    issue_age: int = Field(default=30, ge=0, description="Policyholder issue age.")
    term: Optional[int] = Field(default=20, gt=0, description="Coverage term in years.")
    sum_assured: float = Field(default=1_000_000.0, gt=0.0, description="Sum assured / Face amount.")
    premium_paying_term: Optional[int] = Field(default=None, gt=0, description="Premium paying term.")
    interest_rate: float = Field(default=0.05, ge=0.0, le=0.50, description="Annual effective interest rate.")
    gross_premium: Optional[float] = Field(
        default=None, gt=0.0, description="Gross premium. If None, calculated with 20% loading."
    )
    table_id: str = Field(default="soa_ilt", description="Mortality table identifier from TableRegistry.")
    expense: Optional[ExpenseAssumption] = Field(
        default=None, description="Expense loadings."
    )
    lapse: Optional[LapseAssumption] = Field(
        default=None, description="Policyholder lapse decrement rates."
    )
    assumption_refs: Optional[list[AssumptionReference]] = Field(
        default=None, description="List of exact assumption versions utilized."
    )


class DeterministicValuationResponse(BaseModel):
    """Response schema for deterministic valuation results."""

    product_type: str
    issue_age: int
    term: Optional[int]
    sum_assured: float
    annual_net_premium: float
    annual_gross_premium: float
    nsp: float
    annuity_factor: float
    bel: float
    table_id: str = "soa_ilt"
    table_name: str = "SOA Illustrative Life Table"
    reserve_profile: list[dict[str, Any]]
    cash_flows: list[dict[str, Any]]


class StochasticValuationRequest(BaseModel):
    """Request payload for Level 4 stochastic Monte Carlo risk simulation."""

    product_type: ProductType = Field(
        default=ProductType.ENDOWMENT, description="Insurance product type."
    )
    issue_age: int = Field(default=30, ge=0, description="Policyholder issue age.")
    term: Optional[int] = Field(default=20, gt=0, description="Coverage term in years.")
    sum_assured: float = Field(default=1_000_000.0, gt=0.0, description="Sum assured / Face amount.")
    premium_paying_term: Optional[int] = Field(default=None, gt=0, description="Premium paying term.")
    gross_premium: Optional[float] = Field(
        default=None, gt=0.0, description="Gross premium. If None, calculated with 25% loading."
    )
    table_id: str = Field(default="soa_ilt", description="Mortality table identifier from TableRegistry.")
    vasicek: VasicekParams = Field(
        default_factory=lambda: VasicekParams(r0=0.05, kappa=0.20, theta=0.05, sigma=0.015),
        description="Vasicek ESG short-rate model parameters.",
    )
    dynamic_lapse: Optional[DynamicLapseParams] = Field(
        default=None, description="Dynamic S-curve lapse parameters."
    )
    expense: Optional[ExpenseAssumption] = Field(
        default=None, description="Expense loadings."
    )
    n_scenarios: int = Field(
        default=2000, ge=50, le=50000, description="Number of Monte Carlo scenario paths."
    )
    seed: Optional[int] = Field(default=None, description="Random seed for reproducibility. Auto-generated if omitted.")
    assumption_refs: Optional[list[AssumptionReference]] = Field(
        default=None, description="List of exact assumption versions utilized."
    )


class QuantileTrajectory(BaseModel):
    """Percentile bands at each timestep across stochastic paths."""

    p5: list[float] = Field(..., description="5th percentile trajectory (lower bound).")
    p25: list[float] = Field(..., description="25th percentile trajectory (lower quartile).")
    p50: list[float] = Field(..., description="50th percentile trajectory (median).")
    p75: list[float] = Field(..., description="75th percentile trajectory (upper quartile).")
    p95: list[float] = Field(..., description="95th percentile trajectory (upper bound).")


class TerminalDistribution(BaseModel):
    """Statistical distribution, moments, and binned histogram of terminal liabilities."""

    bin_edges: list[float] = Field(..., description="Histogram bin boundary values.")
    counts: list[int] = Field(..., description="Sample count in each histogram bin.")
    mean: float = Field(..., description="Expected mean terminal value.")
    std: float = Field(..., description="Standard deviation.")
    skewness: float = Field(..., description="Third standardized moment (skewness).")
    var_95: float = Field(..., description="Value at Risk at 95% confidence level.")
    cvar_95: float = Field(..., description="Conditional Value at Risk (CTE 95).")
    var_99: float = Field(..., description="Value at Risk at 99% confidence level.")
    cvar_99: float = Field(..., description="Conditional Value at Risk (CTE 99).")


class StochasticValuationResponse(BaseModel):
    """Response schema for compressed server-side stochastic Monte Carlo outputs."""

    timesteps: list[Union[int, str]] = Field(default_factory=list, description="Time projection grid.")
    quantiles: QuantileTrajectory = Field(..., description="Server-aggregated cross-sectional quantile bands.")
    terminal_distribution: TerminalDistribution = Field(..., description="Terminal liability distribution and histogram bins.")
    sample_paths: list[list[float]] = Field(default_factory=list, description="Representative path subset (max 15 traces).")
    summary_kpis: dict[str, float] = Field(default_factory=dict, description="Key summary risk metrics.")

    # Convenience / backward-compatible properties
    mean_bel: float = Field(..., description="Mean Best Estimate Liability.")
    std_bel: float = Field(..., description="Standard deviation of liability.")
    min_bel: float = Field(..., description="Minimum scenario BEL.")
    max_bel: float = Field(..., description="Maximum scenario BEL.")
    var_95: float = Field(..., description="Value at Risk (95% percentile).")
    var_99: float = Field(..., description="Value at Risk (99% percentile).")
    cvar_95: float = Field(..., description="Conditional Value at Risk (95%).")
    cvar_99: float = Field(..., description="Conditional Value at Risk (99%).")
    percentiles: dict[str, float] = Field(default_factory=dict, description="Quantiles mapping.")
    fan_chart_rates: list[dict[str, Any]] = Field(default_factory=list, description="Fan chart rate objects.")
    liability_histogram: list[dict[str, Any]] = Field(default_factory=list, description="Histogram bin objects.")


class AsyncJobCreateResponse(BaseModel):
    """Response returned upon enqueuing an asynchronous simulation task."""

    job_id: str = Field(..., description="Unique simulation job identifier.")
    status: str = Field(default="QUEUED", description="Initial job status.")
    total_paths: int = Field(..., description="Target number of Monte Carlo paths.")
    ws_endpoint: str = Field(..., description="WebSocket URI for streaming progress.")


class RunMetadata(BaseModel):
    """Reproducibility metadata capturing the exact computational identity of a run."""
    seed: int = Field(..., description="The exact random seed used.")
    n_scenarios: int = Field(..., description="Number of paths generated.")
    product_type: str = Field(..., description="Insurance product type.")
    issue_age: int = Field(..., description="Issue age.")
    term: Optional[int] = Field(..., description="Coverage term.")
    sum_assured: float = Field(..., description="Sum assured / Face amount.")
    table_id: str = Field(..., description="Mortality table identifier.")
    economic_model: str = Field(..., description="Economic model used (e.g. VASICEK).")
    economic_parameters: dict[str, Any] = Field(..., description="Parameters of the economic model.")
    engine_version: str = Field(default="0.2.3", description="Version of Actura.")
    creation_timestamp: float = Field(..., description="Unix timestamp of run creation.")
    dependency_versions: dict[str, str] = Field(default_factory=dict, description="Versions of critical libraries.")


class AsyncJobStatusResponse(BaseModel):
    """Polling response schema for job status."""

    job_id: str
    status: str
    progress: float
    completed_paths: int
    total_paths: int
    partial_metrics: Optional[dict[str, Any]] = None
    result: Optional[StochasticValuationResponse] = None
    error: Optional[str] = None
    run_metadata: Optional[RunMetadata] = None
    original_request: Optional[dict[str, Any]] = None


# ────────────────────────────────────────────────────────────
# Portfolio Batch Valuation Schemas
# ────────────────────────────────────────────────────────────

class PortfolioPolicyRecord(BaseModel):
    """Individual policy input item for JSON portfolio batch requests."""

    policy_id: Optional[str] = Field(default=None, description="Unique policy identifier.")
    issue_age: int = Field(..., ge=0, description="Issue age.")
    term_years: Optional[int] = Field(default=20, ge=1, description="Policy term in years.")
    sum_assured: float = Field(..., gt=0.0, description="Sum assured / Face amount.")
    gross_premium: float = Field(..., gt=0.0, description="Annual gross premium.")
    product_type: str = Field(default="term", description="Product type (term, endowment, whole_life, pure_endowment).")
    policy_duration_years: int = Field(default=0, ge=0, description="Current policy in-force duration.")
    gender: Optional[str] = Field(default="U", description="Gender (M, F, U).")


class PortfolioValuationJSONRequest(BaseModel):
    """JSON batch request schema for evaluating a portfolio of contracts."""

    policies: list[PortfolioPolicyRecord] = Field(..., description="List of policy contracts.")
    interest_rate: float = Field(default=0.05, gt=0.0, le=0.50, description="Discount rate.")
    table_id: str = Field(default="soa_ilt", description="Mortality table identifier.")
    expense: Optional[ExpenseAssumption] = Field(default=None, description="Expense assumptions.")
    lapse: Optional[LapseAssumption] = Field(default=None, description="Lapse assumptions.")


class PortfolioValuationResponse(BaseModel):
    """Response schema for aggregate portfolio liabilities and segment breakdowns."""

    total_policies: int
    total_sum_assured: float
    total_pvfb: float
    total_pvfp: float
    total_pvfe: float
    total_bel: float
    annual_cash_flows: list[dict[str, Any]]
    product_breakdown: dict[str, dict[str, Any]]
    age_breakdown: dict[str, dict[str, Any]]
    duration_breakdown: dict[str, dict[str, Any]]
    sample_seriatim: list[dict[str, Any]]


# ────────────────────────────────────────────────────────────
# Lee-Carter Mortality Forecast Schemas
# ────────────────────────────────────────────────────────────

class LeeCarterForecastRequest(BaseModel):
    """Request payload for Lee-Carter stochastic mortality improvement forecasting."""

    table_id: str = Field(default="soa_ilt", description="Base mortality table identifier.")
    n_ahead: int = Field(default=30, ge=1, le=100, description="Forecast horizon in future calendar years.")
    n_scenarios: int = Field(default=1000, ge=50, le=10000, description="Number of Monte Carlo paths for kappa_t.")
    base_year: int = Field(default=2024, ge=1900, le=2100, description="Base calibration calendar year.")
    annual_improvement: float = Field(default=0.012, ge=0.0, le=0.08, description="Historical annual improvement rate assumption.")
    seed: Optional[int] = Field(default=42, description="Random seed for reproducibility.")


class LeeCarterForecastResponse(BaseModel):
    """Response schema for Lee-Carter mortality model fit and forecasted trajectories."""

    table_id: str
    table_name: str
    fit: dict[str, Any]
    forecast: dict[str, Any]


# ────────────────────────────────────────────────────────────
# IFRS 17 / PSAK 117 Valuation Schemas
# ────────────────────────────────────────────────────────────

class IFRS17ValuationRequest(BaseModel):
    """Request payload for IFRS 17 / PSAK 117 General Measurement Model (BBA) valuation."""

    product_type: str = Field(default="endowment", description="Product line (term, endowment, whole_life, pure_endowment).")
    issue_age: int = Field(default=35, ge=0, description="Age at policy issuance.")
    term: Optional[int] = Field(default=20, ge=1, description="Policy coverage term in years.")
    sum_assured: float = Field(default=500000.0, gt=0.0, description="Sum assured / Face amount.")
    premium_paying_term: Optional[int] = Field(default=None, ge=1, description="Premium payment duration.")
    interest_rate: float = Field(default=0.05, ge=0.0, le=0.50, description="Locked-in valuation discount rate.")
    gross_premium: Optional[float] = Field(default=None, gt=0.0, description="Annual gross premium (auto-calculated if omitted).")
    table_id: str = Field(default="soa_ilt", description="Mortality table identifier.")
    ra_ratio: float = Field(default=0.06, ge=0.0, le=0.50, description="Risk Adjustment loading factor.")
    expense: Optional[ExpenseAssumption] = Field(default=None, description="Acquisition and maintenance expense loadings.")
    lapse: Optional[LapseAssumption] = Field(default=None, description="Policyholder lapse decrement rates.")


class IFRS17ValuationResponse(BaseModel):
    """Response payload for IFRS 17 / PSAK 117 Building Block Approach valuation."""

    table_id: str
    table_name: str
    product_type: str
    initial_balance: dict[str, Any]
    balance_sheet_schedule: list[dict[str, Any]]
    income_statement_schedule: list[dict[str, Any]]
    total_insurance_revenue: float
    total_csm_released: float
    total_service_expenses: float


# ────────────────────────────────────────────────────────────
# Advanced ESG Simulation Schemas (Hull-White 1F & CIR)
# ────────────────────────────────────────────────────────────

class ESGModelType(str, Enum):
    """Supported Economic Scenario Generator diffusion models."""

    VASICEK = "VASICEK"
    HULL_WHITE_1F = "HULL_WHITE_1F"
    CIR = "CIR"


class ESGSimulationRequest(BaseModel):
    """Request payload for advanced multi-factor ESG short-rate path generation."""

    model_type: ESGModelType = Field(default=ESGModelType.HULL_WHITE_1F, description="Stochastic short-rate model.")
    benchmark_curve: Optional[str] = Field(default="US_TREASURY", description="Benchmark curve ('US_TREASURY', 'SOVEREIGN_SUN', 'FLAT').")
    custom_yield_points: Optional[list[dict[str, float]]] = Field(
        default=None, description="Custom yield curve pillar points [{'tenor': 1.0, 'rate': 0.05}]."
    )
    # Hull-White / Vasicek parameters
    a: Optional[float] = Field(default=0.10, ge=0.001, le=2.0, description="Mean reversion speed (Hull-White / Vasicek).")
    sigma: Optional[float] = Field(default=0.015, ge=0.0001, le=0.50, description="Rate volatility sigma.")
    # CIR parameters
    r0: Optional[float] = Field(default=0.05, ge=0.0001, le=0.50, description="Initial short rate.")
    kappa: Optional[float] = Field(default=0.20, ge=0.001, le=3.0, description="CIR mean reversion kappa.")
    theta: Optional[float] = Field(default=0.05, ge=0.0001, le=0.50, description="CIR long-term mean theta.")
    # Simulation horizon
    n_years: int = Field(default=20, ge=1, le=80, description="Projection horizon in years.")
    n_scenarios: int = Field(default=1000, ge=50, le=25000, description="Scenario path count.")
    dt: float = Field(default=1.0, ge=0.05, le=1.0, description="Time step size in years.")
    seed: Optional[int] = Field(default=42, description="Random seed for reproducibility.")


class ESGSimulationResponse(BaseModel):
    """Response payload with simulated short rates, quantile fan chart, and discount curve validation."""

    model_type: str
    n_scenarios: int
    n_years: int
    dt: float
    time_grid: list[float]
    fan_chart_rates: list[dict[str, Any]]
    sample_paths: list[list[float]]
    market_discount_factors: list[float]
    simulated_discount_factors: list[float]
    pricing_error_mae: float
    feller_condition_satisfied: Optional[bool] = None
    feller_ratio: Optional[float] = None


# ────────────────────────────────────────────────────────────
# Stress Testing & Sensitivity Analysis Schemas
# ────────────────────────────────────────────────────────────

class SensitivityRequest(BaseModel):
    """Request payload for multi-factor sensitivity and Tornado analysis."""

    product_type: str = Field(default="endowment", description="Product line (term, endowment, whole_life, pure_endowment).")
    issue_age: int = Field(default=35, ge=0, description="Age at policy issuance.")
    term: Optional[int] = Field(default=20, ge=1, description="Policy coverage term in years.")
    sum_assured: float = Field(default=500000.0, gt=0.0, description="Sum assured / Face amount.")
    premium_paying_term: Optional[int] = Field(default=None, ge=1, description="Premium payment duration.")
    interest_rate: float = Field(default=0.05, ge=0.0, le=0.50, description="Baseline valuation discount rate.")
    gross_premium: Optional[float] = Field(default=None, gt=0.0, description="Annual gross premium (auto-calculated if omitted).")
    table_id: str = Field(default="soa_ilt", description="Mortality table identifier.")
    expense: Optional[ExpenseAssumption] = Field(default=None, description="Acquisition and maintenance expense loadings.")
    lapse: Optional[LapseAssumption] = Field(default=None, description="Policyholder lapse decrement rates.")
    shocks: dict[str, float] = Field(default_factory=dict, description="Custom risk factor shocks.")

    @field_validator("shocks", mode="before")
    @classmethod
    def ensure_dict(cls, v: Any) -> dict[str, float]:
        if v is None:
            return {}
        if not isinstance(v, dict):
            raise ValueError("shocks must be a valid dictionary")
        return {str(k): float(val) for k, val in v.items()}


class SensitivityResponse(BaseModel):
    """Response payload with Tornado chart coordinates, baseline duration/convexity/DV01, and compound scenarios."""

    table_id: str
    table_name: str
    product_type: str
    sum_assured: float
    baseline: dict[str, Any]
    tornado_items: list[dict[str, Any]]
    combined_scenarios: list[dict[str, Any]]


class StressTestShocks(BaseModel):
    """Real-time shock parameters for interactive sliders."""

    interest_rate_bps: float = Field(
        default=0.0, ge=-500.0, le=500.0, description="Parallel shift in interest rate in bps (-200 to +200 bps)."
    )
    mortality_multiplier: float = Field(
        default=1.0, ge=0.1, le=5.0, description="Mortality scaling multiplier (0.5 to 2.0 = 50% - 200%)."
    )
    lapse_multiplier: float = Field(
        default=1.0, ge=0.1, le=5.0, description="Lapse scaling multiplier (0.5 to 2.0 = 50% - 200%)."
    )
    expense_inflation_pct: float = Field(
        default=0.0, ge=0.0, le=50.0, description="Expense inflation percentage (0.0% to 15.0%)."
    )


class StressTestRequest(BaseModel):
    """Request payload for real-time stress testing sliders."""

    contract_id: Optional[str] = Field(default=None, description="Optional contract identifier.")
    product_type: str = Field(default="endowment", description="Product line (term, endowment, whole_life, pure_endowment).")
    issue_age: int = Field(default=30, ge=0, description="Age at policy issuance.")
    term: Optional[int] = Field(default=20, ge=1, description="Policy coverage term in years.")
    sum_assured: float = Field(default=1_000_000.0, gt=0.0, description="Sum assured / Face amount.")
    premium_paying_term: Optional[int] = Field(default=None, ge=1, description="Premium payment duration.")
    interest_rate: float = Field(default=0.05, gt=0.0, le=0.50, description="Baseline valuation discount rate.")
    gross_premium: Optional[float] = Field(default=None, gt=0.0, description="Annual gross premium (auto-priced if omitted).")
    table_id: str = Field(default="soa_ilt", description="Mortality table identifier.")
    expense: Optional[ExpenseAssumption] = Field(default=None, description="Baseline expense loadings.")
    lapse: Optional[LapseAssumption] = Field(default=None, description="Baseline lapse decrement rates.")
    base_assumptions: Optional[dict[str, Any]] = Field(default=None, description="Optional dictionary of base assumptions.")
    shocks: Union[StressTestShocks, dict[str, float]] = Field(
        default_factory=StressTestShocks, description="Real-time shock parameters."
    )

    @field_validator("shocks", mode="before")
    @classmethod
    def ensure_stress_shocks(cls, v: Any) -> Any:
        if v is None:
            return StressTestShocks()
        if not isinstance(v, (dict, StressTestShocks)):
            raise ValueError("shocks must be a valid dictionary or StressTestShocks instance")
        return v


class StressTestResponse(BaseModel):
    """Response payload for real-time stress testing sliders."""

    table_id: str
    table_name: str
    product_type: str
    sum_assured: float
    baseline_reserve: float
    stressed_reserve: float
    delta_reserve: float
    delta_pct: float
    effective_duration: float
    dv01: float
    effective_convexity: float
    shocks_applied: dict[str, float]
    tornado_data: list[dict[str, Any]]
    reserve_trajectory: list[dict[str, Any]]


# ────────────────────────────────────────────────────────────
# Visual Node-Based Contract Logic Builder Schemas
# ────────────────────────────────────────────────────────────

class ValidationSeverity(str, Enum):
    """Severity level of a blueprint validation issue."""
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


class ValidationIssue(BaseModel):
    """A single detected validation issue in the contract logic blueprint."""
    severity: ValidationSeverity
    code: str
    message: str
    node_id: Optional[str] = None
    field: Optional[str] = None
    suggested_fix: Optional[str] = None


class ValidationResult(BaseModel):
    """Aggregate result of a blueprint validation pass."""
    is_valid: bool = Field(description="True if the blueprint has zero ERROR level issues.")
    issues: list[ValidationIssue] = Field(default_factory=list, description="Detected issues.")


class GraphNodeData(BaseModel):
    """Single node specification in the visual contract builder DAG."""

    id: str = Field(description="Unique node identifier.")
    type: str = Field(description="Node type (policyInput, inflow, contingency, outflow, valuationSink, accumulator).")
    data: dict[str, Any] = Field(default_factory=dict, description="Node parameters and reactive properties.")
    position: Optional[dict[str, float]] = Field(default=None, description="Canvas (x, y) coordinates.")


class GraphEdgeData(BaseModel):
    """Directed edge connecting two ports in the contract logic DAG."""

    id: Optional[str] = Field(default=None, description="Unique edge identifier.")
    source: str = Field(description="Source node ID.")
    target: str = Field(description="Target node ID.")
    sourceHandle: Optional[str] = Field(default=None, description="Origin port handle.")
    targetHandle: Optional[str] = Field(default=None, description="Destination port handle.")


class GuidedTermLifeRequest(BaseModel):
    """Parameters required to automatically generate a Term Life blueprint."""

    product_type: str = Field(default="term_life", description="Product type identifier.")
    issue_age: int = Field(default=35, ge=0, description="Entry age.")
    term: int = Field(default=20, gt=0, description="Policy term in years.")
    sum_assured: float = Field(default=1_000_000.0, gt=0.0, description="Face amount.")
    premium_freq: str = Field(default="annual", description="Premium payment frequency.")
    table_id: str = Field(default="soa_ilt", description="Mortality table identifier.")
    interest_rate: float = Field(default=0.05, ge=0.0, le=0.50, description="Discount / Interest rate.")
    lapse_rate: Optional[float] = Field(default=0.03, ge=0.0, le=1.0, description="Annual lapse rate.")
    expense_first_year_pct: Optional[float] = Field(default=0.35, ge=0.0, le=1.0, description="Percentage of first year premium.")
    expense_renewal_pct: Optional[float] = Field(default=0.05, ge=0.0, le=1.0, description="Percentage of renewal premium.")


class ContractGraphPayload(BaseModel):
    """Complete serialized node-graph payload submitted for cash flow valuation."""

    contract_id: Optional[str] = Field(default=None, description="Optional contract / product code.")
    nodes: list[GraphNodeData] = Field(default_factory=list, description="List of nodes in the graph.")
    edges: list[GraphEdgeData] = Field(default_factory=list, description="List of directed edges in the graph.")
    discount_rate: Optional[float] = Field(default=0.05, ge=0.0, le=0.50, description="Valuation discount rate.")


class ProvenanceTrace(BaseModel):
    """Domain-level explanation tracking calculation lineage from result to blueprint nodes."""
    metric_name: str = Field(description="Name of the metric being explained.")
    value: float = Field(description="Final computed value.")
    contributing_components: list[str] = Field(default_factory=list, description="Cash flow or calculation components contributing to this value.")
    relevant_assumptions: dict[str, str] = Field(default_factory=dict, description="Key assumptions driving the calculation.")
    source_nodes: list[str] = Field(default_factory=list, description="IDs of blueprint nodes contributing to this calculation.")
    calculation_stage: str = Field(description="High-level valuation stage (e.g. 'Present Value Aggregation').")
    calculation_description: str = Field(description="Actuary-friendly narrative explaining the result.")


class SimulateGraphResponse(BaseModel):
    """Projection output and cash flow waterfall returned by the graph simulator."""

    contract_id: str
    product_name: str
    issue_age: int
    term: int
    sum_assured: float
    annual_premium: float
    total_bel: float
    years: list[int]
    ages: list[int]
    inforce_boy: list[float]
    premiums: list[float]
    death_claims: list[float]
    maturity_payouts: list[float]
    surrender_payouts: list[float]
    expenses: list[float]
    net_cash_flow: list[float]
    discounted_net_cf: list[float]
    reserves: list[float]
    breakdown: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, ProvenanceTrace] = Field(default_factory=dict, description="Deterministic calculation provenance traces mapping metrics back to source nodes.")




