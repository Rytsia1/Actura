"""
Multi-Dimensional Stress Testing & Sensitivity Valuation Engine.

Provides the ``SensitivityEngine`` class for evaluating risk-factor perturbations
across interest rates, mortality scales, lapse multipliers, and expense inflations.
Generates structured Tornado Chart payloads, key risk indicators (effective duration,
convexity, DV01), and combined compound macro-stress scenarios.
"""

from __future__ import annotations

from typing import Any, Optional, TypedDict

import numpy as np
from pydantic import BaseModel, Field

from actuary_engine.models.assumptions import (
    ExpenseAssumption,
    InterestAssumption,
    LapseAssumption,
)
from actuary_engine.models.contracts import PolicyContract, ProductType
from actuary_engine.domain.pricing.premium import LevelPremiumCalculator
from actuary_engine.domain.tables.commutation import CommutationFunctions
from actuary_engine.domain.tables.mortality_table import MortalityTable
from actuary_engine.valuation.gpv import GrossPremiumValuation


class TornadoShockDef(TypedDict):
    """Specification for a one-at-a-time (OAT) parameter sensitivity shock."""

    risk_factor: str
    category: str
    low_label: str
    high_label: str
    low_kwargs: dict[str, float]
    high_kwargs: dict[str, float]


class ScenarioDef(TypedDict):
    """Specification for a compound macro stress testing scenario."""

    scenario_id: str
    name: str
    description: str
    rate_shift_bps: float
    mortality_mult: float
    lapse_mult: float
    expense_mult: float
    eval_kwargs: dict[str, float]
    solvency_impact: str


class SliderTornadoDef(TypedDict):
    """Specification for an interactive slider risk factor tornado bar."""

    risk_factor: str
    category: str
    low_label: str
    high_label: str
    low_kwargs: dict[str, float]
    high_kwargs: dict[str, float]
    current_label: str
    current_kwargs: dict[str, float]


class SensitivityBaselineMetrics(BaseModel):
    """Baseline valuation indicators before applying stress shocks."""

    base_reserve: float = Field(description="Baseline Best Estimate Liability (BEL).")
    annual_net_premium: float = Field(description="Annual equivalence net premium P.")
    annual_gross_premium: float = Field(description="Annual loaded gross premium.")
    effective_duration: float = Field(description="Effective liability duration in years.")
    effective_convexity: float = Field(description="Effective liability convexity.")
    dv01: float = Field(description="Dollar Value of a 1 basis point shift in interest rate.")
    pv_future_benefits: float = Field(description="PV of claims and maturity benefits.")
    pv_future_premiums: float = Field(description="PV of premium inflows.")
    pv_future_expenses: float = Field(description="PV of acquisition and maintenance expenses.")


class TornadoItem(BaseModel):
    """Single risk-factor sensitivity perturbation item for Tornado Chart rendering."""

    risk_factor: str = Field(description="Name of the risk factor under test.")
    category: str = Field(description="Category (MARKET, MORTALITY, POLICYHOLDER, EXPENSE, CATASTROPHE).")
    low_label: str = Field(description="Description of the downside / low shock.")
    high_label: str = Field(description="Description of the upside / high shock.")
    low_reserve: float = Field(description="Reserve liability under low shock.")
    high_reserve: float = Field(description="Reserve liability under high shock.")
    low_delta: float = Field(description="Absolute liability shift under low shock (V_low - V_base).")
    high_delta: float = Field(description="Absolute liability shift under high shock (V_high - V_base).")
    low_delta_pct: float = Field(description="Percentage shift under low shock.")
    high_delta_pct: float = Field(description="Percentage shift under high shock.")
    swing: float = Field(description="Absolute delta swing magnitude |V_high - V_low|.")
    swing_pct: float = Field(description="Percentage swing relative to base reserve.")


class CombinedScenarioResult(BaseModel):
    """Outcome of a compound macro-stress scenario (multi-factor joint shock)."""

    scenario_id: str
    name: str
    description: str
    rate_shift_bps: float
    mortality_multiplier: float
    lapse_multiplier: float
    expense_multiplier: float
    shocked_reserve: float
    delta_reserve: float
    delta_pct: float
    solvency_impact: str


class SensitivityReport(BaseModel):
    """Complete stress testing report containing baseline metrics, sorted tornado items, and compound scenarios."""

    table_name: str
    product_type: str
    sum_assured: float
    baseline: SensitivityBaselineMetrics
    tornado_items: list[TornadoItem]
    combined_scenarios: list[CombinedScenarioResult]


class SensitivityEngine:
    """Stress testing & sensitivity valuation engine."""

    __slots__ = ("table", "interest", "expense", "lapse")

    def __init__(
        self,
        table: MortalityTable,
        interest: InterestAssumption,
        expense: Optional[ExpenseAssumption] = None,
        lapse: Optional[LapseAssumption] = None,
    ) -> None:
        """Initialize SensitivityEngine.

        Args:
            table: Parsed baseline MortalityTable.
            interest: Baseline InterestAssumption.
            expense: Baseline ExpenseAssumption.
            lapse: Baseline LapseAssumption.
        """
        self.table = table
        self.interest = interest
        self.expense = expense or ExpenseAssumption()
        self.lapse = lapse or LapseAssumption()

    def evaluate_point(
        self,
        contract: PolicyContract,
        gross_premium: Optional[float] = None,
        interest_shift: float = 0.0,
        mortality_mult: float = 1.0,
        mortality_add: float = 0.0,
        lapse_mult: float = 1.0,
        lapse_mass_y1: float = 0.0,
        expense_mult: float = 1.0,
    ) -> dict[str, float]:
        """Evaluate valuation metrics under a specific parameter perturbation.

        Args:
            contract: PolicyContract specification.
            gross_premium: Annual gross premium (if None, priced on base assumptions).
            interest_shift: Parallel shift in annual interest rate (e.g. +0.01 for +100 bps).
            mortality_mult: Multiplicative scale on qx array (e.g. 1.20 for +20%).
            mortality_add: Additive shift on qx array (e.g. +0.002 for pandemic).
            lapse_mult: Multiplicative scale on lapse rates.
            lapse_mass_y1: Instantaneous surge added to year-1 lapse rate.
            expense_mult: Multiplicative scale on expenses.

        Returns:
            Dictionary containing 'reserve', 'pvfb', 'pvfe', 'pvfp', 'annual_net_premium', 'gross_premium'.
        """
        contract.validate_against_table(self.table)

        base_rate = getattr(self.interest, "annual_rate", 0.05)
        shocked_rate = max(0.0001, base_rate + interest_shift)
        shocked_interest = InterestAssumption(annual_rate=shocked_rate)

        # 1. Mortality Shock Table
        if mortality_mult != 1.0 or mortality_add != 0.0:
            qx_shocked = np.clip(self.table.qx * mortality_mult + mortality_add, 0.0, 1.0)
            qx_shocked[:-1] = np.minimum(qx_shocked[:-1], 0.9999)
            qx_shocked[-1] = 1.0  # Terminal closure
            shocked_table = MortalityTable(
                ages=self.table.ages,
                qx=qx_shocked,
                name=f"{self.table.name}_shocked",
                radix=self.table.radix,
            )
        else:
            shocked_table = self.table

        # 2. Expense Shock
        if expense_mult != 1.0:
            shocked_expense = ExpenseAssumption(
                percent_of_premium_first=min(1.0, self.expense.percent_of_premium_first * expense_mult),
                percent_of_premium_renewal=min(1.0, self.expense.percent_of_premium_renewal * expense_mult),
                per_policy_first=self.expense.per_policy_first * expense_mult,
                per_policy_renewal=self.expense.per_policy_renewal * expense_mult,
            )
        else:
            shocked_expense = self.expense

        # 3. Lapse Shock
        if lapse_mult != 1.0 or lapse_mass_y1 != 0.0:
            if self.lapse.duration_rates is not None:
                dur_rates = [min(0.95, r * lapse_mult) for r in self.lapse.duration_rates]
                if lapse_mass_y1 > 0 and len(dur_rates) > 0:
                    dur_rates[0] = min(0.95, dur_rates[0] + lapse_mass_y1)
                shocked_lapse = LapseAssumption(
                    flat_annual_rate=min(0.95, self.lapse.flat_annual_rate * lapse_mult),
                    duration_rates=dur_rates,
                )
            else:
                shocked_lapse = LapseAssumption(
                    flat_annual_rate=min(0.95, self.lapse.flat_annual_rate * lapse_mult + lapse_mass_y1),
                )
        else:
            shocked_lapse = self.lapse

        # Resolve effective gross premium and net premium
        comm = CommutationFunctions(shocked_table, shocked_interest)
        pricer = LevelPremiumCalculator(comm)
        net_res = pricer.price_contract(contract)

        eff_gp = gross_premium
        if eff_gp is None:
            eff_gp = net_res.annual_premium * 1.20

        # Project GPV cash flows
        gpv = GrossPremiumValuation(
            table=shocked_table,
            interest=shocked_interest,
            expense=shocked_expense,
            lapse=shocked_lapse,
        )
        cf_df = gpv.project(contract, eff_gp)

        pvfb = float(cf_df["pv_death_claims"].sum() + cf_df["pv_maturity"].sum() + cf_df["pv_lapse_payouts"].sum())
        pvfe = float(cf_df["pv_expense"].sum())
        pvfp = float(cf_df["pv_premium"].sum())
        bel = pvfb + pvfe - pvfp

        return {
            "reserve": bel,
            "pvfb": pvfb,
            "pvfe": pvfe,
            "pvfp": pvfp,
            "annual_net_premium": net_res.annual_premium,
            "gross_premium": eff_gp,
        }

    def run_tornado_analysis(
        self,
        contract: PolicyContract,
        gross_premium: Optional[float] = None,
    ) -> SensitivityReport:
        """Run systematic one-at-a-time (OAT) parameter sensitivity shocks for Tornado Chart.

        Args:
            contract: PolicyContract specification.
            gross_premium: Optional user-specified annual gross premium.

        Returns:
            SensitivityReport with sorted tornado items and key sensitivity metrics.
        """
        # 1. Base Valuation Point
        base_res = self.evaluate_point(contract, gross_premium=gross_premium)
        v_base = base_res["reserve"]
        abs_base = max(1.0, abs(v_base))

        # 2. Key Duration & Convexity Metrics (Using +-100 bps shifts)
        delta_i = 0.01  # 100 bps
        res_plus_i = self.evaluate_point(contract, gross_premium=gross_premium, interest_shift=delta_i)
        res_minus_i = self.evaluate_point(contract, gross_premium=gross_premium, interest_shift=-delta_i)

        pv_outgo_base = base_res["pvfb"] + base_res["pvfe"]
        pv_outgo_plus = res_plus_i["pvfb"] + res_plus_i["pvfe"]
        pv_outgo_minus = res_minus_i["pvfb"] + res_minus_i["pvfe"]

        # Effective Duration & Convexity formulas on liability obligations
        eff_duration = -(pv_outgo_plus - pv_outgo_minus) / (2.0 * delta_i * max(1.0, pv_outgo_base))
        eff_convexity = (pv_outgo_plus + pv_outgo_minus - 2.0 * pv_outgo_base) / ((delta_i ** 2) * max(1.0, pv_outgo_base))
        dv01 = abs(pv_outgo_minus - pv_outgo_plus) / 200.0  # dollar impact per 1 bp

        baseline = SensitivityBaselineMetrics(
            base_reserve=round(v_base, 2),
            annual_net_premium=round(base_res["annual_net_premium"], 2),
            annual_gross_premium=round(base_res["gross_premium"], 2),
            effective_duration=round(eff_duration, 3),
            effective_convexity=round(eff_convexity, 3),
            dv01=round(dv01, 2),
            pv_future_benefits=round(base_res["pvfb"], 2),
            pv_future_premiums=round(base_res["pvfp"], 2),
            pv_future_expenses=round(base_res["pvfe"], 2),
        )

        # 3. Tornado Shock Definitions
        shocks_to_run: list[TornadoShockDef] = [
            {
                "risk_factor": "Discount Rate (±100 bps)",
                "category": "MARKET",
                "low_label": "-100 bps",
                "high_label": "+100 bps",
                "low_kwargs": {"interest_shift": -0.01},
                "high_kwargs": {"interest_shift": +0.01},
            },
            {
                "risk_factor": "Discount Rate (±200 bps)",
                "category": "MARKET",
                "low_label": "-200 bps",
                "high_label": "+200 bps",
                "low_kwargs": {"interest_shift": -0.02},
                "high_kwargs": {"interest_shift": +0.02},
            },
            {
                "risk_factor": "Mortality Rate (±20%)",
                "category": "MORTALITY",
                "low_label": "-20% qx",
                "high_label": "+20% qx",
                "low_kwargs": {"mortality_mult": 0.80},
                "high_kwargs": {"mortality_mult": 1.20},
            },
            {
                "risk_factor": "Lapse / Surrender Rate (±50%)",
                "category": "POLICYHOLDER",
                "low_label": "-50% Lapse",
                "high_label": "+50% Lapse",
                "low_kwargs": {"lapse_mult": 0.50},
                "high_kwargs": {"lapse_mult": 1.50},
            },
            {
                "risk_factor": "Acquisition & Maint. Expenses (±20%)",
                "category": "EXPENSE",
                "low_label": "-20% Expenses",
                "high_label": "+20% Expenses",
                "low_kwargs": {"expense_mult": 0.80},
                "high_kwargs": {"expense_mult": 1.20},
            },
            {
                "risk_factor": "Mass Surrender Event (+30% Y1)",
                "category": "CATASTROPHE",
                "low_label": "Base",
                "high_label": "+30% Year 1 Surrender",
                "low_kwargs": {},
                "high_kwargs": {"lapse_mass_y1": 0.30},
            },
            {
                "risk_factor": "Pandemic Mortality Spike (+2‰)",
                "category": "CATASTROPHE",
                "low_label": "Base",
                "high_label": "+2‰ Flat Death Spike",
                "low_kwargs": {},
                "high_kwargs": {"mortality_add": 0.002},
            },
        ]

        tornado_items: list[TornadoItem] = []
        for shock in shocks_to_run:
            low_kwargs = shock.get("low_kwargs", {})
            if not isinstance(low_kwargs, dict):
                low_kwargs = {}
            high_kwargs = shock.get("high_kwargs", {})
            if not isinstance(high_kwargs, dict):
                high_kwargs = {}

            low_eval = self.evaluate_point(contract, gross_premium=gross_premium, **low_kwargs)
            high_eval = self.evaluate_point(contract, gross_premium=gross_premium, **high_kwargs)

            v_l = float(low_eval["reserve"])
            v_h = float(high_eval["reserve"])

            delta_l = v_l - v_base
            delta_h = v_h - v_base
            swing = abs(v_h - v_l)
            swing_pct = (swing / abs_base) * 100.0

            tornado_items.append(
                TornadoItem(
                    risk_factor=str(shock.get("risk_factor", "")),
                    category=str(shock.get("category", "")),
                    low_label=str(shock.get("low_label", "")),
                    high_label=str(shock.get("high_label", "")),
                    low_reserve=round(v_l, 2),
                    high_reserve=round(v_h, 2),
                    low_delta=round(delta_l, 2),
                    high_delta=round(delta_h, 2),
                    low_delta_pct=round((delta_l / abs_base) * 100.0, 2),
                    high_delta_pct=round((delta_h / abs_base) * 100.0, 2),
                    swing=round(swing, 2),
                    swing_pct=round(swing_pct, 2),
                )
            )

        # Sort descending by swing magnitude for proper Tornado layout
        tornado_items.sort(key=lambda x: x.swing, reverse=True)

        # 4. Compound Combined Stress Scenarios
        combined_scenarios = self.run_combined_scenarios(contract, gross_premium=gross_premium)

        return SensitivityReport(
            table_name=self.table.name,
            product_type=contract.product_type.value,
            sum_assured=contract.sum_assured,
            baseline=baseline,
            tornado_items=tornado_items,
            combined_scenarios=combined_scenarios,
        )

    def run_combined_scenarios(
        self,
        contract: PolicyContract,
        gross_premium: Optional[float] = None,
    ) -> list[CombinedScenarioResult]:
        """Evaluate compound multi-factor stress packages (e.g. Solvency II, Stagflation, Pandemic)."""
        base_res = self.evaluate_point(contract, gross_premium=gross_premium)
        v_base = base_res["reserve"]
        abs_base = max(1.0, abs(v_base))

        scenarios_defs: list[ScenarioDef] = [
            {
                "scenario_id": "stagflation_crisis",
                "name": "Stagflation Crisis",
                "description": "Interest rate drops -100 bps with +20% expense inflation and +30% lapses.",
                "rate_shift_bps": -100.0,
                "mortality_mult": 1.0,
                "lapse_mult": 1.30,
                "expense_mult": 1.20,
                "eval_kwargs": {"interest_shift": -0.01, "lapse_mult": 1.30, "expense_mult": 1.20},
                "solvency_impact": "HIGH RISK",
            },
            {
                "scenario_id": "pandemic_surge",
                "name": "Severe Pandemic Shock",
                "description": "Mortality spikes +30%, interest rates ease -50 bps, and lapses decline -20%.",
                "rate_shift_bps": -50.0,
                "mortality_mult": 1.30,
                "lapse_mult": 0.80,
                "expense_mult": 1.0,
                "eval_kwargs": {"mortality_mult": 1.30, "interest_shift": -0.005, "lapse_mult": 0.80},
                "solvency_impact": "HIGH RISK",
            },
            {
                "scenario_id": "mass_lapse_run",
                "name": "Disintermediation & Mass Surrender",
                "description": "Market rate spikes +150 bps triggering +40% Year 1 policy surrender surge.",
                "rate_shift_bps": +150.0,
                "mortality_mult": 1.0,
                "lapse_mult": 1.50,
                "expense_mult": 1.0,
                "eval_kwargs": {"interest_shift": +0.015, "lapse_mult": 1.50, "lapse_mass_y1": 0.40},
                "solvency_impact": "MODERATE RISK",
            },
            {
                "scenario_id": "regulator_standard_stress",
                "name": "Solvency II / OJK Standard Stress",
                "description": "Rate -150 bps, Mortality +15%, Lapse +50%, Expense +10%.",
                "rate_shift_bps": -150.0,
                "mortality_mult": 1.15,
                "lapse_mult": 1.50,
                "expense_mult": 1.10,
                "eval_kwargs": {"interest_shift": -0.015, "mortality_mult": 1.15, "lapse_mult": 1.50, "expense_mult": 1.10},
                "solvency_impact": "HIGH RISK",
            },
            {
                "scenario_id": "economic_boom",
                "name": "Economic Expansion (Bull Market)",
                "description": "Rate +100 bps, Mortality improves -10%, Expense efficiencies -10%.",
                "rate_shift_bps": +100.0,
                "mortality_mult": 0.90,
                "lapse_mult": 0.90,
                "expense_mult": 0.90,
                "eval_kwargs": {"interest_shift": +0.01, "mortality_mult": 0.90, "lapse_mult": 0.90, "expense_mult": 0.90},
                "solvency_impact": "FAVORABLE",
            },
        ]

        results: list[CombinedScenarioResult] = []
        for sc in scenarios_defs:
            eval_kwargs = sc.get("eval_kwargs", {})
            if not isinstance(eval_kwargs, dict):
                eval_kwargs = {}

            shock_eval = self.evaluate_point(contract, gross_premium=gross_premium, **eval_kwargs)
            v_s = float(shock_eval["reserve"])
            delta = v_s - v_base
            delta_pct = (delta / abs_base) * 100.0

            results.append(
                CombinedScenarioResult(
                    scenario_id=str(sc.get("scenario_id", "")),
                    name=str(sc.get("name", "")),
                    description=str(sc.get("description", "")),
                    rate_shift_bps=float(sc.get("rate_shift_bps", 0.0)),
                    mortality_multiplier=float(sc.get("mortality_mult", 1.0)),
                    lapse_multiplier=float(sc.get("lapse_mult", 1.0)),
                    expense_multiplier=float(sc.get("expense_mult", 1.0)),
                    shocked_reserve=round(v_s, 2),
                    delta_reserve=round(delta, 2),
                    delta_pct=round(delta_pct, 2),
                    solvency_impact=str(sc.get("solvency_impact", "MODERATE")),
                )
            )

        return results

    def run_realtime_stress_test(
        self,
        contract: PolicyContract,
        shocks: dict[str, float],
        gross_premium: Optional[float] = None,
    ) -> dict[str, Any]:
        """Execute interactive real-time stress testing with custom slider shocks.

        Computes:
        - Baseline vs. Stressed overall BEL and delta metrics.
        - Detailed duration-by-duration reserve trajectory comparison.
        - Dynamic Tornado sensitivity items including slider positions.
        - Duration, convexity, and DV01 indicators.

        Args:
            contract: PolicyContract specification.
            shocks: Dictionary with 'interest_rate_bps', 'mortality_multiplier',
                   'lapse_multiplier', 'expense_inflation_pct'.
            gross_premium: Optional gross premium override.

        Returns:
            Dictionary payload ready for StressTestResponse serialization.
        """
        # 1. Parse Shocks
        ir_bps = shocks.get("interest_rate_bps", 0.0)
        mort_mult = shocks.get("mortality_multiplier", 1.0)
        lapse_mult = shocks.get("lapse_multiplier", 1.0)
        exp_infl_pct = shocks.get("expense_inflation_pct", 0.0)
        exp_mult = 1.0 + (exp_infl_pct / 100.0)

        # 2. Determine Effective Gross Premium
        eff_gp = gross_premium
        if eff_gp is None:
            comm = CommutationFunctions(self.table, self.interest)
            pricer = LevelPremiumCalculator(comm)
            net_res = pricer.price_contract(contract)
            eff_gp = net_res.annual_premium * 1.20

        # 3. Baseline Valuation & Trajectory
        gpv_base = GrossPremiumValuation(
            table=self.table,
            interest=self.interest,
            expense=self.expense,
            lapse=self.lapse,
        )
        cf_base = gpv_base.project(contract, eff_gp)
        res_base = gpv_base.gross_reserve_profile(contract, eff_gp)
        v_base = float(cf_base["pv_net_liability"].sum())
        abs_base = max(1.0, abs(v_base))

        # 4. Stressed Valuation & Trajectory
        # Construct shocked assumptions
        delta_r = ir_bps / 10000.0  # bps to decimal
        shocked_interest = InterestAssumption(annual_rate=max(0.0001, self.interest.annual_rate + delta_r))

        if mort_mult != 1.0:
            qx_shocked = np.clip(self.table.qx * mort_mult, 0.0, 1.0)
            qx_shocked[:-1] = np.minimum(qx_shocked[:-1], 0.9999)
            qx_shocked[-1] = 1.0
            shocked_table = MortalityTable(
                ages=self.table.ages,
                qx=qx_shocked,
                name=f"{self.table.name}_stress",
                radix=self.table.radix,
            )
        else:
            shocked_table = self.table

        if exp_mult != 1.0:
            shocked_expense = ExpenseAssumption(
                percent_of_premium_first=min(1.0, self.expense.percent_of_premium_first * exp_mult),
                percent_of_premium_renewal=min(1.0, self.expense.percent_of_premium_renewal * exp_mult),
                per_policy_first=self.expense.per_policy_first * exp_mult,
                per_policy_renewal=self.expense.per_policy_renewal * exp_mult,
            )
        else:
            shocked_expense = self.expense

        if lapse_mult != 1.0:
            if self.lapse.duration_rates is not None:
                shocked_lapse = LapseAssumption(
                    flat_annual_rate=min(0.95, self.lapse.flat_annual_rate * lapse_mult),
                    duration_rates=[min(0.95, r * lapse_mult) for r in self.lapse.duration_rates],
                )
            else:
                shocked_lapse = LapseAssumption(
                    flat_annual_rate=min(0.95, self.lapse.flat_annual_rate * lapse_mult),
                )
        else:
            shocked_lapse = self.lapse

        gpv_stress = GrossPremiumValuation(
            table=shocked_table,
            interest=shocked_interest,
            expense=shocked_expense,
            lapse=shocked_lapse,
        )
        cf_stress = gpv_stress.project(contract, eff_gp)
        res_stress = gpv_stress.gross_reserve_profile(contract, eff_gp)
        v_stress = float(cf_stress["pv_net_liability"].sum())

        delta_res = v_stress - v_base
        delta_pct = (delta_res / abs_base) * 100.0

        # 5. Build Duration-by-Duration Trajectory List
        reserve_trajectory: list[dict[str, Any]] = []
        n_durations = min(len(res_base), len(res_stress))
        for t in range(n_durations):
            dur = int(res_base.iloc[t]["duration"])
            age = int(res_base.iloc[t]["age"])
            b_val = float(res_base.iloc[t]["gross_reserve"])
            s_val = float(res_stress.iloc[t]["gross_reserve"]) if t < len(res_stress) else 0.0
            b_cf = float(cf_base.iloc[t]["net_liability_cf"]) if t < len(cf_base) else 0.0
            s_cf = float(cf_stress.iloc[t]["net_liability_cf"]) if t < len(cf_stress) else 0.0

            reserve_trajectory.append({
                "duration": dur,
                "age": age,
                "baseline_reserve": round(b_val, 2),
                "stressed_reserve": round(s_val, 2),
                "delta_reserve": round(s_val - b_val, 2),
                "baseline_net_cf": round(b_cf, 2),
                "stressed_net_cf": round(s_cf, 2),
            })

        # 6. Compute Key Risk Metrics (Duration & DV01)
        delta_i = 0.01  # 100 bps
        res_plus_i = self.evaluate_point(contract, gross_premium=eff_gp, interest_shift=delta_i)
        res_minus_i = self.evaluate_point(contract, gross_premium=eff_gp, interest_shift=-delta_i)
        pv_outgo_base = float(cf_base["pv_death_claims"].sum() + cf_base["pv_maturity"].sum() + cf_base["pv_expense"].sum() + cf_base["pv_lapse_payouts"].sum())
        pv_outgo_plus = res_plus_i["pvfb"] + res_plus_i["pvfe"]
        pv_outgo_minus = res_minus_i["pvfb"] + res_minus_i["pvfe"]

        eff_duration = -(pv_outgo_plus - pv_outgo_minus) / (2.0 * delta_i * max(1.0, pv_outgo_base))
        eff_convexity = (pv_outgo_plus + pv_outgo_minus - 2.0 * pv_outgo_base) / ((delta_i ** 2) * max(1.0, pv_outgo_base))
        dv01 = abs(pv_outgo_minus - pv_outgo_plus) / 200.0

        # 7. Compute Dynamic Tornado Data (OAT Sensitivity for Sliders)
        tornado_defs: list[SliderTornadoDef] = [
            {
                "risk_factor": "Interest Rate Shift",
                "category": "MARKET",
                "low_label": "-200 bps",
                "high_label": "+200 bps",
                "low_kwargs": {"interest_shift": -0.02},
                "high_kwargs": {"interest_shift": +0.02},
                "current_label": f"{ir_bps:+.0f} bps",
                "current_kwargs": {"interest_shift": ir_bps / 10000.0},
            },
            {
                "risk_factor": "Mortality Multiplier",
                "category": "MORTALITY",
                "low_label": "50% qx",
                "high_label": "200% qx",
                "low_kwargs": {"mortality_mult": 0.50},
                "high_kwargs": {"mortality_mult": 2.00},
                "current_label": f"{mort_mult * 100:.0f}%",
                "current_kwargs": {"mortality_mult": mort_mult},
            },
            {
                "risk_factor": "Lapse Rate Shock",
                "category": "POLICYHOLDER",
                "low_label": "50% Lapse",
                "high_label": "200% Lapse",
                "low_kwargs": {"lapse_mult": 0.50},
                "high_kwargs": {"lapse_mult": 2.00},
                "current_label": f"{lapse_mult * 100:.0f}%",
                "current_kwargs": {"lapse_mult": lapse_mult},
            },
            {
                "risk_factor": "Expense Inflation",
                "category": "EXPENSE",
                "low_label": "0% Base",
                "high_label": "+15% Inflation",
                "low_kwargs": {"expense_mult": 1.00},
                "high_kwargs": {"expense_mult": 1.15},
                "current_label": f"{exp_infl_pct:+.1f}%",
                "current_kwargs": {"expense_mult": exp_mult},
            },
        ]

        tornado_items: list[dict[str, Any]] = []
        for item in tornado_defs:
            l_kwargs = item.get("low_kwargs", {})
            if not isinstance(l_kwargs, dict):
                l_kwargs = {}
            h_kwargs = item.get("high_kwargs", {})
            if not isinstance(h_kwargs, dict):
                h_kwargs = {}
            c_kwargs = item.get("current_kwargs", {})
            if not isinstance(c_kwargs, dict):
                c_kwargs = {}

            l_eval = self.evaluate_point(contract, gross_premium=eff_gp, **l_kwargs)
            h_eval = self.evaluate_point(contract, gross_premium=eff_gp, **h_kwargs)
            c_eval = self.evaluate_point(contract, gross_premium=eff_gp, **c_kwargs)

            v_l = float(l_eval["reserve"])
            v_h = float(h_eval["reserve"])
            v_c = float(c_eval["reserve"])

            delta_l = v_l - v_base
            delta_h = v_h - v_base
            delta_c = v_c - v_base
            swing = abs(v_h - v_l)
            swing_pct = (swing / abs_base) * 100.0

            tornado_items.append({
                "risk_factor": str(item.get("risk_factor", "")),
                "category": str(item.get("category", "")),
                "low_label": str(item.get("low_label", "")),
                "high_label": str(item.get("high_label", "")),
                "low_reserve": round(v_l, 2),
                "high_reserve": round(v_h, 2),
                "low_delta": round(delta_l, 2),
                "high_delta": round(delta_h, 2),
                "low_delta_pct": round((delta_l / abs_base) * 100.0, 2),
                "high_delta_pct": round((delta_h / abs_base) * 100.0, 2),
                "current_label": str(item.get("current_label", "")),
                "current_reserve": round(v_c, 2),
                "current_delta": round(delta_c, 2),
                "current_delta_pct": round((delta_c / abs_base) * 100.0, 2),
                "swing": round(swing, 2),
                "swing_pct": round(swing_pct, 2),
            })

        tornado_items.sort(key=lambda x: x["swing"], reverse=True)

        return {
            "baseline_reserve": round(v_base, 2),
            "stressed_reserve": round(v_stress, 2),
            "delta_reserve": round(delta_res, 2),
            "delta_pct": round(delta_pct, 2),
            "effective_duration": round(eff_duration, 3),
            "dv01": round(dv01, 2),
            "effective_convexity": round(eff_convexity, 3),
            "shocks_applied": {
                "interest_rate_bps": ir_bps,
                "mortality_multiplier": mort_mult,
                "lapse_multiplier": lapse_mult,
                "expense_inflation_pct": exp_infl_pct,
            },
            "reserve_trajectory": reserve_trajectory,
            "tornado_data": tornado_items,
            "product_type": contract.product_type.value,
        }
