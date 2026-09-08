"""
Actuarial Scenario Valuation and Validation Service.
Applies assumption overrides against base models, enforces actuarial domain rules,
executes deterministic valuations, and persists reproducible run history.
"""
from __future__ import annotations

import json
import time
from typing import Any, Optional

import numpy as np

from actuary_engine.api.job_manager import job_manager
from actuary_engine.infrastructure.scenario_repo import scenario_repo
from actuary_engine.tables.mortality_table import MortalityTable
from actuary_engine.tables.registry import table_registry
from actuary_engine.models.assumptions import (
    InterestAssumption,
    ExpenseAssumption,
    LapseAssumption,
)
from actuary_engine.models.contracts import PolicyContract, ProductType
from actuary_engine.tables.commutation import CommutationFunctions
from actuary_engine.pricing.premium import LevelPremiumCalculator
from actuary_engine.valuation.gpv import GrossPremiumValuation
from actuary_engine.valuation.ifrs17 import IFRS17Engine
from actuary_engine.api.schemas import (
    ScenarioValidationResult,
    ScenarioExecutionResponse,
)


class ScenarioService:
    def __init__(self) -> None:
        self.repo = scenario_repo
        self.table_reg = table_registry

    def resolve_effective_assumptions(
        self, base_model: dict[str, Any], overrides: dict[str, Any]
    ) -> dict[str, Any]:
        """Compute the effective assumption parameters after applying overrides."""
        # 1. Interest rate
        base_ir = float(base_model.get("interest_rate", 0.05))
        if overrides.get("interest_rate_override") is not None:
            eff_ir = float(overrides["interest_rate_override"])
        elif overrides.get("interest_rate_bps") is not None:
            eff_ir = base_ir + (float(overrides["interest_rate_bps"]) / 10000.0)
        elif overrides.get("interest_rate_delta") is not None:
            eff_ir = base_ir + float(overrides["interest_rate_delta"])
        else:
            eff_ir = base_ir

        # 2. Mortality
        eff_mort_mult = float(overrides.get("mortality_multiplier") or 1.0)
        eff_table_id = overrides.get("mortality_table_id") or base_model.get("table_id", "soa_ilt")

        # 3. Lapse
        base_lapse = base_model.get("lapse", {})
        if isinstance(base_lapse, str):
            base_lapse = json.loads(base_lapse)
        base_flat_lapse = float(base_lapse.get("flat_annual_rate", 0.03))

        if overrides.get("lapse_override") is not None:
            eff_lapse_rate = float(overrides["lapse_override"])
        else:
            l_delta = float(overrides.get("lapse_rate_delta") or 0.0)
            l_mult = float(overrides.get("lapse_multiplier") or 1.0)
            eff_lapse_rate = (base_flat_lapse + l_delta) * l_mult

        # 4. Expense
        eff_exp_mult = float(overrides.get("expense_multiplier") or 1.0)
        if overrides.get("expense_inflation_pct") is not None:
            eff_exp_mult *= (1.0 + float(overrides["expense_inflation_pct"]) / 100.0)

        return {
            "interest_rate": eff_ir,
            "mortality_multiplier": eff_mort_mult,
            "table_id": eff_table_id,
            "lapse_flat_rate": eff_lapse_rate,
            "expense_multiplier": eff_exp_mult,
        }

    def validate_overrides(
        self, base_model: dict[str, Any], overrides: dict[str, Any]
    ) -> tuple[bool, list[str], list[str], dict[str, Any]]:
        """Validate assumption overrides against a base model according to actuarial domain guardrails."""
        errors: list[str] = []
        warnings: list[str] = []

        eff = self.resolve_effective_assumptions(base_model, overrides)

        # Validate interest rate
        eff_ir = eff["interest_rate"]
        if eff_ir <= 0.0:
            errors.append(f"Effective interest rate ({eff_ir * 100:.2f}%) must be strictly positive.")
        elif eff_ir > 0.50:
            errors.append(f"Effective interest rate ({eff_ir * 100:.2f}%) exceeds maximum limit of 50%.")
        elif eff_ir < 0.01:
            warnings.append(f"Effective interest rate ({eff_ir * 100:.2f}%) is unusually low.")

        # Validate mortality multiplier
        mort_mult = eff["mortality_multiplier"]
        if mort_mult <= 0.0:
            errors.append(f"Mortality multiplier ({mort_mult:.2f}) must be strictly positive.")
        elif mort_mult > 5.0:
            warnings.append(f"Mortality multiplier ({mort_mult:.2f}) is extremely high (> 5.0x).")

        # Validate table exists
        table_id = eff["table_id"]
        try:
            self.table_reg.get_table(table_id)
        except KeyError:
            errors.append(f"Mortality table '{table_id}' not found in registry.")

        # Validate lapse rate
        eff_lapse = eff["lapse_flat_rate"]
        if eff_lapse < 0.0:
            errors.append(f"Effective lapse rate ({eff_lapse * 100:.2f}%) cannot be negative.")
        elif eff_lapse > 1.0:
            errors.append(f"Effective lapse rate ({eff_lapse * 100:.2f}%) cannot exceed 100%.")

        # Validate expense multiplier
        exp_mult = eff["expense_multiplier"]
        if exp_mult < 0.0:
            errors.append(f"Effective expense multiplier ({exp_mult:.2f}) cannot be negative.")

        return len(errors) == 0, errors, warnings, eff

    def validate_scenario(self, scenario_id: str) -> ScenarioValidationResult:
        """Actuarially validate a scenario's overrides against its referenced base model."""
        scenario = self.repo.get_scenario(scenario_id)
        if not scenario:
            return ScenarioValidationResult(
                scenario_id=scenario_id,
                is_valid=False,
                errors=[f"Scenario '{scenario_id}' not found."],
            )

        base_model_id = scenario["base_model_id"]
        base_model = self.repo.get_base_model(base_model_id)
        if not base_model:
            return ScenarioValidationResult(
                scenario_id=scenario_id,
                is_valid=False,
                errors=[f"Referenced base model '{base_model_id}' does not exist."],
            )

        overrides = scenario.get("overrides", {})
        is_valid, errors, warnings, eff = self.validate_overrides(base_model, overrides)

        return ScenarioValidationResult(
            scenario_id=scenario_id,
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            effective_assumptions=eff,
        )

    def evaluate_model_with_overrides(
        self, base_model: dict[str, Any], overrides: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute deterministic valuation with overrides against a base model.

        Calculates BEL, CSM, profit/loss, reserves, and cash flows.
        Does NOT mutate base_model.
        """
        is_valid, errors, warnings, eff = self.validate_overrides(base_model, overrides)
        if not is_valid:
            raise ValueError(f"Assumption validation failed: {'; '.join(errors)}")

        # 1. Base Table & Contract
        raw_table = self.table_reg.get_table(eff["table_id"])
        mort_mult = eff["mortality_multiplier"]
        if mort_mult != 1.0:
            qx_shocked = np.clip(raw_table.qx * mort_mult, 0.0, 1.0)
            qx_shocked[:-1] = np.minimum(qx_shocked[:-1], 0.9999)
            qx_shocked[-1] = 1.0
            table = MortalityTable(
                ages=raw_table.ages,
                qx=qx_shocked,
                name=f"{raw_table.name} (x{mort_mult:.2f})",
                radix=raw_table.radix,
            )
        else:
            table = raw_table

        product_type = ProductType(base_model["product_type"])
        contract = PolicyContract(
            product_type=product_type,
            issue_age=base_model["issue_age"],
            term=base_model.get("term"),
            sum_assured=base_model["sum_assured"],
            premium_paying_term=base_model.get("premium_paying_term"),
        )
        contract.validate_against_table(table)

        # 2. Shocked Assumptions
        interest = InterestAssumption(annual_rate=eff["interest_rate"])

        # Base expense
        base_exp = base_model.get("expense", {})
        if isinstance(base_exp, str):
            base_exp = json.loads(base_exp)
        exp_mult = eff["expense_multiplier"]
        expense = ExpenseAssumption(
            percent_of_premium_first=min(1.0, float(base_exp.get("percent_of_premium_first", 0.35)) * exp_mult),
            percent_of_premium_renewal=min(1.0, float(base_exp.get("percent_of_premium_renewal", 0.05)) * exp_mult),
            per_policy_first=float(base_exp.get("per_policy_first", 200.0)) * exp_mult,
            per_policy_renewal=float(base_exp.get("per_policy_renewal", 20.0)) * exp_mult,
        )

        # Base lapse
        base_lapse = base_model.get("lapse", {})
        if isinstance(base_lapse, str):
            base_lapse = json.loads(base_lapse)
        l_delta = float(overrides.get("lapse_rate_delta") or 0.0)
        l_mult = float(overrides.get("lapse_multiplier") or 1.0)

        if overrides.get("lapse_override") is not None:
            lapse = LapseAssumption(flat_annual_rate=float(overrides["lapse_override"]))
        else:
            flat_rate = min(1.0, max(0.0, (float(base_lapse.get("flat_annual_rate", 0.03)) + l_delta) * l_mult))
            base_dur = base_lapse.get("duration_rates")
            if base_dur:
                dur_rates = [min(1.0, max(0.0, (float(r) + l_delta) * l_mult)) for r in base_dur]
                lapse = LapseAssumption(flat_annual_rate=flat_rate, duration_rates=dur_rates)
            else:
                lapse = LapseAssumption(flat_annual_rate=flat_rate)

        # 3. Pricing & Premium
        comm = CommutationFunctions(table, interest)
        calc = LevelPremiumCalculator(comm)
        prem_res = calc.price_contract(contract)
        net_premium = prem_res.annual_premium
        nsp = prem_res.nsp
        annuity_factor = prem_res.annuity_factor

        gross_premium = base_model.get("gross_premium")
        if gross_premium is None:
            gross_premium = net_premium * 1.20

        # 4. GPV Projection & BEL
        gpv_engine = GrossPremiumValuation(
            table=table,
            interest=interest,
            expense=expense,
            lapse=lapse,
        )
        cf_df = gpv_engine.project(contract, gross_premium=gross_premium)
        bel = float(gpv_engine.best_estimate_liability(contract, gross_premium=gross_premium))
        res_df = gpv_engine.gross_reserve_profile(contract, gross_premium=gross_premium)

        # 5. IFRS 17 Evaluation for CSM & Profit
        ifrs_engine = IFRS17Engine(
            table=table,
            interest=interest,
            expense=expense,
            lapse=lapse,
        )
        ifrs_init = ifrs_engine.evaluate_initial_recognition(contract, gross_premium=gross_premium)
        csm = float(ifrs_init.csm_0)

        pv_future_premiums = float(cf_df["pv_premium"].sum())
        pv_future_outgo = float(
            cf_df["pv_death_claims"].sum()
            + cf_df["pv_lapse_payouts"].sum()
            + cf_df["pv_maturity"].sum()
            + cf_df["pv_expense"].sum()
        )
        profit_loss = float(pv_future_premiums - pv_future_outgo)

        # Format Schedules
        reserve_profile = [
            {
                "duration": int(r["duration"]),
                "age": int(r["age"]),
                "gross_reserve": round(float(r["gross_reserve"]), 2),
            }
            for _, r in res_df.iterrows()
        ]
        cash_flows = [
            {
                "year": int(r["year"]),
                "age": int(r["age"]),
                "inforce_boy": round(float(r["inforce_boy"]), 6),
                "premium_income": round(float(r["premium_income"]), 2),
                "death_claims": round(float(r["death_claims"]), 2),
                "maturity_benefit": round(float(r["maturity_benefit"]), 2),
                "total_expense": round(float(r["total_expense"]), 2),
                "net_liability_cf": round(float(r["net_liability_cf"]), 2),
                "pv_net_liability": round(float(r["pv_net_liability"]), 2),
            }
            for _, r in cf_df.iterrows()
        ]

        return {
            "bel": bel,
            "csm": csm,
            "profit_loss": profit_loss,
            "net_premium": net_premium,
            "gross_premium": gross_premium,
            "nsp": nsp,
            "annuity_factor": annuity_factor,
            "effective_assumptions": eff,
            "reserve_profile": reserve_profile,
            "cash_flows": cash_flows,
            "contract": contract,
            "table": table,
            "interest": interest,
            "expense": expense,
            "lapse": lapse,
        }

    def execute_scenario(self, scenario_id: str) -> ScenarioExecutionResponse:
        """Execute a deterministic valuation for a scenario, keeping base model untouched."""
        scenario = self.repo.get_scenario(scenario_id)
        if not scenario:
            raise ValueError(f"Scenario '{scenario_id}' not found.")

        base_model = self.repo.get_base_model(scenario["base_model_id"])
        if not base_model:
            raise ValueError(f"Base model '{scenario['base_model_id']}' not found.")

        overrides = scenario.get("overrides", {})
        eval_res = self.evaluate_model_with_overrides(base_model, overrides)
        eff = eval_res["effective_assumptions"]
        bel = eval_res["bel"]
        csm = eval_res["csm"]
        profit_loss = eval_res["profit_loss"]

        # Baseline Evaluation for Comparison
        baseline_bel = self._compute_baseline_bel(base_model, eval_res["contract"])
        delta_bel = bel - baseline_bel
        pct_change = (delta_bel / max(1.0, abs(baseline_bel))) * 100.0

        # Reproducibility & Job Persistence
        exec_time = time.time()
        run_meta_dict = {
            "engine_version": "1.0.0",
            "execution_time": exec_time,
            "valuation_type": "Scenario",
            "scenario": scenario["name"],
            "scenario_id": scenario_id,
            "base_model_id": base_model["id"],
            "assumption_overrides": overrides,
            "effective_assumptions": eff,
            "baseline_bel": round(baseline_bel, 2),
            "stressed_bel": round(bel, 2),
            "delta_bel": round(delta_bel, 2),
            "pct_change_bel": round(pct_change, 2),
            "csm": round(csm, 2),
            "profit_loss": round(profit_loss, 2),
        }

        job = job_manager.create_job(
            total_paths=1,
            run_metadata=run_meta_dict,
            original_request={"scenario_id": scenario_id, "overrides": overrides},
        )

        response = ScenarioExecutionResponse(
            scenario_id=scenario_id,
            scenario_name=scenario["name"],
            base_model_id=base_model["id"],
            valuation_type="Scenario",
            status="COMPLETED",
            job_id=job.job_id,
            effective_interest_rate=round(eff["interest_rate"], 4),
            effective_mortality_multiplier=round(eff["mortality_multiplier"], 4),
            effective_lapse_rate=round(eff["lapse_flat_rate"], 4),
            effective_expense_multiplier=round(eff["expense_multiplier"], 4),
            bel=round(bel, 2),
            baseline_bel=round(baseline_bel, 2),
            delta_bel=round(delta_bel, 2),
            pct_change_bel=round(pct_change, 2),
            csm=round(csm, 2),
            profit_loss=round(profit_loss, 2),
            annual_net_premium=round(eval_res["net_premium"], 2),
            annual_gross_premium=round(eval_res["gross_premium"], 2),
            nsp=round(eval_res["nsp"], 2),
            annuity_factor=round(eval_res["annuity_factor"], 4),
            reserve_profile=eval_res["reserve_profile"],
            cash_flows=eval_res["cash_flows"],
            reproducibility=run_meta_dict,
        )

        # Update job table
        from sqlalchemy import update
        stmt = (
            update(job_manager.jobs_table)
            .where(job_manager.jobs_table.c.job_id == job.job_id)
            .values(
                status="COMPLETED",
                progress=100.0,
                completed_paths=1,
                result=json.dumps(response.model_dump()),
                updated_at=exec_time,
            )
        )
        with job_manager.engine.begin() as conn:
            conn.execute(stmt)

        return response

    def _compute_baseline_bel(self, base_model: dict[str, Any], contract: PolicyContract) -> float:
        """Compute the unshocked baseline BEL for comparison."""
        table = self.table_reg.get_table(base_model.get("table_id", "soa_ilt"))
        interest = InterestAssumption(annual_rate=float(base_model.get("interest_rate", 0.05)))

        base_exp = base_model.get("expense", {})
        if isinstance(base_exp, str):
            base_exp = json.loads(base_exp)
        expense = ExpenseAssumption(
            percent_of_premium_first=float(base_exp.get("percent_of_premium_first", 0.35)),
            percent_of_premium_renewal=float(base_exp.get("percent_of_premium_renewal", 0.05)),
            per_policy_first=float(base_exp.get("per_policy_first", 200.0)),
            per_policy_renewal=float(base_exp.get("per_policy_renewal", 20.0)),
        )

        base_lapse = base_model.get("lapse", {})
        if isinstance(base_lapse, str):
            base_lapse = json.loads(base_lapse)
        base_dur = base_lapse.get("duration_rates")
        if base_dur:
            lapse = LapseAssumption(
                flat_annual_rate=float(base_lapse.get("flat_annual_rate", 0.03)),
                duration_rates=[float(r) for r in base_dur],
            )
        else:
            lapse = LapseAssumption(flat_annual_rate=float(base_lapse.get("flat_annual_rate", 0.03)))

        gross_premium = base_model.get("gross_premium")
        if gross_premium is None:
            comm = CommutationFunctions(table, interest)
            calc = LevelPremiumCalculator(comm)
            prem_res = calc.price_contract(contract)
            gross_premium = prem_res.annual_premium * 1.20

        gpv_engine = GrossPremiumValuation(
            table=table,
            interest=interest,
            expense=expense,
            lapse=lapse,
        )
        return float(gpv_engine.best_estimate_liability(contract, gross_premium=gross_premium))


scenario_service = ScenarioService()
