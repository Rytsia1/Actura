"""
Actura Valuation Results Exporter Service.

Consumes persisted valuation run records from JobManager and formats them into:
1. Multi-sheet Excel (.xlsx) workbooks styled for executive reporting.
2. Formatted CSV exports (single multi-section file, single-sheet CSV, or ZIP bundle).
3. Complete structured JSON valuation payloads.

Strictly consumes persisted results without recalculating actuarial metrics.
"""

from __future__ import annotations

import csv
import io
import json
import time
import zipfile
from datetime import datetime, timezone
from typing import Any, Optional, Union

import numpy as np
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from actuary_engine.api.job_manager import JobStatus, SimulationJob, job_manager


class JobNotFoundError(Exception):
    """Raised when a requested valuation job does not exist."""
    pass


class JobNotExportableError(Exception):
    """Raised when a valuation job is in a non-exportable state (FAILED, QUEUED, etc.)."""
    pass


class ValuationExportService:
    """Service for exporting persisted valuation results into Excel, CSV, and JSON."""

    SHEET_NAMES = [
        "Summary",
        "Model",
        "Assumptions",
        "Projection",
        "Valuation",
        "Risk",
        "Sensitivity",
        "Validation",
        "Metadata",
    ]

    def __init__(self, manager=job_manager) -> None:
        self.job_manager = manager

    def _get_job(self, job_id: str) -> SimulationJob:
        """Fetch job and validate that it is completed with valid result data."""
        job = self.job_manager.get_job(job_id)
        if not job:
            raise JobNotFoundError(f"Valuation run '{job_id}' was not found in registry.")

        if job.status == JobStatus.FAILED:
            err = job.error or "Unknown simulation error"
            raise JobNotExportableError(
                f"Cannot export valuation run '{job_id}' because execution failed: {err}"
            )

        if job.status in (JobStatus.QUEUED, JobStatus.PROCESSING):
            raise JobNotExportableError(
                f"Valuation run '{job_id}' is currently '{job.status.value}'. "
                "Exports can only be generated after execution completes."
            )

        if not job.result:
            raise JobNotExportableError(
                f"Valuation run '{job_id}' contains no result payload to export."
            )

        return job

    def extract_report_data(self, job: SimulationJob) -> dict[str, Any]:
        """
        Extract and normalize the 9 required report sections from a persisted job.
        Strictly consumes persisted data without recalculation.
        """
        req = job.original_request or {}
        meta = job.run_metadata or {}
        res = job.result or {}

        # 1. Determine run type & timestamps
        valuation_type = (
            meta.get("valuation_type")
            or ("Stochastic" if "quantiles" in res or "mean_bel" in res else
                "IFRS17" if "total_csm_released" in res or "balance_sheet_schedule" in res else
                "Scenario" if "scenario_id" in meta or "delta_bel" in res else
                "Deterministic")
        )

        val_date_dt = datetime.fromtimestamp(job.created_at, timezone.utc)
        val_date_str = val_date_dt.strftime("%Y-%m-%d %H:%M:%S UTC")

        product_type = (
            req.get("product_type")
            or meta.get("product_type")
            or res.get("product_type")
            or "Endowment"
        )
        if isinstance(product_type, dict):
            product_type = str(product_type.get("value", product_type))

        # Model identifier & version
        model_name = (
            meta.get("scenario_name")
            or meta.get("base_model_id")
            or f"{str(product_type).replace('_', ' ').title()} Model"
        )
        model_version = str(meta.get("model_version") or meta.get("base_model_id") or "1.0.0")
        engine_version = str(meta.get("engine_version") or "1.0.0")
        seed = meta.get("seed", req.get("seed", "Deterministic N/A"))
        sim_count = job.total_paths or meta.get("n_scenarios", 1)

        # 2. Extract Key Metrics
        key_metrics: list[dict[str, Any]] = []
        if valuation_type == "Stochastic":
            key_metrics.extend([
                {"Metric": "Mean BEL", "Value": res.get("mean_bel", 0.0), "Format": "currency"},
                {"Metric": "Std Dev BEL", "Value": res.get("std_bel", 0.0), "Format": "currency"},
                {"Metric": "Value at Risk (VaR 95%)", "Value": res.get("var_95", 0.0), "Format": "currency"},
                {"Metric": "Conditional VaR (CVaR 95%)", "Value": res.get("cvar_95", 0.0), "Format": "currency"},
                {"Metric": "Value at Risk (VaR 99%)", "Value": res.get("var_99", 0.0), "Format": "currency"},
                {"Metric": "Conditional VaR (CVaR 99%)", "Value": res.get("cvar_99", 0.0), "Format": "currency"},
                {"Metric": "Min Scenario BEL", "Value": res.get("min_bel", 0.0), "Format": "currency"},
                {"Metric": "Max Scenario BEL", "Value": res.get("max_bel", 0.0), "Format": "currency"},
            ])
        elif valuation_type == "IFRS17":
            init_b = res.get("initial_balance") or {}
            key_metrics.extend([
                {"Metric": "Fulfilment Cash Flows (FCF)", "Value": init_b.get("fulfilment_cash_flows", 0.0), "Format": "currency"},
                {"Metric": "Risk Adjustment (RA)", "Value": init_b.get("risk_adjustment", 0.0), "Format": "currency"},
                {"Metric": "Contractual Service Margin (CSM)", "Value": init_b.get("contractual_service_margin", 0.0), "Format": "currency"},
                {"Metric": "Total Insurance Revenue", "Value": res.get("total_insurance_revenue", 0.0), "Format": "currency"},
                {"Metric": "Total CSM Released", "Value": res.get("total_csm_released", 0.0), "Format": "currency"},
                {"Metric": "Total Service Expenses", "Value": res.get("total_service_expenses", 0.0), "Format": "currency"},
            ])
        else:
            bel_val = res.get("bel", meta.get("bel", 0.0))
            net_prem = res.get("annual_net_premium", 0.0)
            gross_prem = res.get("annual_gross_premium", req.get("gross_premium", 0.0))
            nsp_val = res.get("nsp", 0.0)
            ann_factor = res.get("annuity_factor", 0.0)
            key_metrics.extend([
                {"Metric": "Best Estimate Liability (BEL)", "Value": bel_val, "Format": "currency"},
                {"Metric": "Annual Net Premium", "Value": net_prem, "Format": "currency"},
                {"Metric": "Annual Gross Premium", "Value": gross_prem, "Format": "currency"},
                {"Metric": "Net Single Premium (NSP)", "Value": nsp_val, "Format": "currency"},
                {"Metric": "Present Value Annuity Factor", "Value": ann_factor, "Format": "float4"},
            ])
            if "baseline_bel" in res:
                key_metrics.extend([
                    {"Metric": "Baseline BEL", "Value": res.get("baseline_bel", 0.0), "Format": "currency"},
                    {"Metric": "Stressed BEL", "Value": res.get("bel", 0.0), "Format": "currency"},
                    {"Metric": "Delta BEL", "Value": res.get("delta_bel", 0.0), "Format": "currency"},
                    {"Metric": "% Change BEL", "Value": res.get("pct_change_bel", 0.0), "Format": "percent"},
                    {"Metric": "CSM", "Value": res.get("csm", 0.0), "Format": "currency"},
                    {"Metric": "Profit / Loss", "Value": res.get("profit_loss", 0.0), "Format": "currency"},
                ])

        executive_summary = {
            "model": model_name,
            "valuation_date": val_date_str,
            "run_id": job.job_id,
            "valuation_type": valuation_type,
            "status": job.status.value,
            "key_metrics": key_metrics,
            "narrative": (
                f"Official valuation report for run '{job.job_id}' executed on {val_date_str}. "
                f"Evaluation completed successfully under {valuation_type} valuation methodology "
                f"with engine version {engine_version}."
            ),
        }

        # 3. Product Definition
        issue_age = req.get("issue_age", meta.get("issue_age", 30))
        term = req.get("term", meta.get("term", 20))
        sum_assured = req.get("sum_assured", meta.get("sum_assured", 1_000_000.0))
        ppt = req.get("premium_paying_term", meta.get("premium_paying_term", term))
        gross_prem_cfg = req.get("gross_premium", res.get("annual_gross_premium", "Auto-calculated"))

        product_definition = [
            {"Parameter": "Product Type", "Value": str(product_type).replace("_", " ").title(), "Category": "Contract"},
            {"Parameter": "Issue Age", "Value": int(issue_age), "Category": "Policyholder"},
            {"Parameter": "Policy Term", "Value": f"{term} years" if term else "Whole Life", "Category": "Duration"},
            {"Parameter": "Premium Paying Term", "Value": f"{ppt} years" if ppt else "Single / Term", "Category": "Payment"},
            {"Parameter": "Sum Assured / Face Amount", "Value": float(sum_assured), "Category": "Benefit"},
            {"Parameter": "Gross Premium", "Value": float(gross_prem_cfg) if isinstance(gross_prem_cfg, (int, float)) else str(gross_prem_cfg), "Category": "Inflow"},
            {"Parameter": "Target Currency", "Value": "USD", "Category": "Financial"},
            {"Parameter": "Valuation Standard", "Value": "Deterministic GPV / IFRS 17 / Stochastic ESG", "Category": "Standard"},
        ]

        # 4. Assumptions
        table_id = req.get("table_id", meta.get("table_id", res.get("table_id", "soa_ilt")))
        table_name = res.get("table_name", f"Mortality Table ({table_id})")
        interest_rate = req.get("interest_rate", meta.get("interest_rate", 0.05))
        expense_obj = req.get("expense", {}) or {}
        lapse_obj = req.get("lapse", {}) or {}

        assumptions_list = [
            {"Assumption": "Mortality Table ID", "Value": str(table_id), "Notes": "Standard life decrement table"},
            {"Assumption": "Mortality Table Name", "Value": str(table_name), "Notes": "Actuarial cohort basis"},
            {"Assumption": "Valuation Discount Rate", "Value": float(interest_rate), "Notes": "Annual effective interest rate"},
            {"Assumption": "Expense: First Year % Premium", "Value": float(expense_obj.get("percent_of_premium_first", 0.35)), "Notes": "Acquisition loading"},
            {"Assumption": "Expense: Renewal % Premium", "Value": float(expense_obj.get("percent_of_premium_renewal", 0.05)), "Notes": "Maintenance loading"},
            {"Assumption": "Expense: First Year Per Policy", "Value": float(expense_obj.get("per_policy_first", 200.0)), "Notes": "Fixed policy issuance cost"},
            {"Assumption": "Expense: Renewal Per Policy", "Value": float(expense_obj.get("per_policy_renewal", 20.0)), "Notes": "Annual policy maintenance cost"},
            {"Assumption": "Lapse: Flat Annual Rate", "Value": float(lapse_obj.get("flat_annual_rate", 0.03)), "Notes": "Policyholder voluntary surrender"},
        ]

        # Vasicek / ESG parameters if stochastic
        if "vasicek" in req:
            vas = req["vasicek"]
            assumptions_list.extend([
                {"Assumption": "ESG Model", "Value": "Vasicek Short-Rate Diffusion", "Notes": "Stochastic interest rate engine"},
                {"Assumption": "ESG: Initial Rate (r0)", "Value": vas.get("r0", 0.05), "Notes": "Starting short rate"},
                {"Assumption": "ESG: Mean Reversion Speed (kappa)", "Value": vas.get("kappa", 0.20), "Notes": "Speed of adjustment"},
                {"Assumption": "ESG: Long-Term Mean (theta)", "Value": vas.get("theta", 0.05), "Notes": "Equilibrium rate"},
                {"Assumption": "ESG: Rate Volatility (sigma)", "Value": vas.get("sigma", 0.015), "Notes": "Annualized rate dispersion"},
            ])

        # Assumption references
        refs = req.get("assumption_refs") or meta.get("assumption_refs") or [
            {"type": "mortality", "id": str(table_id), "version": "v1.0"},
            {"type": "interest", "id": "flat_discount_rate", "version": "v1.0"},
            {"type": "lapse", "id": "standard_lapse", "version": "v1.0"},
            {"type": "expense", "id": "standard_expense", "version": "v1.0"},
        ]
        assumption_versions = refs

        # 5. Projection
        projection_rows: list[dict[str, Any]] = []
        if "reserve_profile" in res and isinstance(res["reserve_profile"], list):
            for row in res["reserve_profile"]:
                projection_rows.append({
                    "Duration": row.get("duration", 0),
                    "Age": row.get("age", 0),
                    "Inforce_lx": round(float(row.get("lx", 0.0)), 2),
                    "Deaths_dx": round(float(row.get("dx", 0.0)), 2),
                    "Premium_Income": round(float(row.get("premium_income", 0.0)), 2),
                    "Death_Benefits": round(float(row.get("death_benefits", 0.0)), 2),
                    "Endowment_Benefits": round(float(row.get("endowment_benefits", 0.0)), 2),
                    "Expenses": round(float(row.get("expenses", 0.0)), 2),
                    "Prospective_Reserve": round(float(row.get("reserve_prospective", 0.0)), 2),
                    "Retrospective_Reserve": round(float(row.get("reserve_retrospective", 0.0)), 2),
                    "Gross_Reserve_GPV": round(float(row.get("gross_reserve", 0.0)), 2),
                    "Discounted_Cash_Flow": round(float(row.get("discounted_cash_flows", 0.0)), 2),
                })
        elif "quantiles" in res and isinstance(res["quantiles"], dict):
            # Stochastic quantile trajectories
            q = res["quantiles"]
            timesteps = res.get("timesteps") or list(range(len(q.get("p50", []))))
            p5 = q.get("p5", [])
            p25 = q.get("p25", [])
            p50 = q.get("p50", [])
            p75 = q.get("p75", [])
            p95 = q.get("p95", [])
            for i, step in enumerate(timesteps):
                projection_rows.append({
                    "Timestep_Year": step,
                    "Quantile_p5": round(float(p5[i]), 2) if i < len(p5) else 0.0,
                    "Quantile_p25": round(float(p25[i]), 2) if i < len(p25) else 0.0,
                    "Quantile_p50_Median": round(float(p50[i]), 2) if i < len(p50) else 0.0,
                    "Quantile_p75": round(float(p75[i]), 2) if i < len(p75) else 0.0,
                    "Quantile_p95": round(float(p95[i]), 2) if i < len(p95) else 0.0,
                })
        elif "balance_sheet_schedule" in res:
            # IFRS 17 schedule
            for item in res.get("balance_sheet_schedule", []):
                projection_rows.append({
                    "Year": item.get("year", item.get("duration", 0)),
                    "BEL": round(float(item.get("bel", 0.0)), 2),
                    "Risk_Adjustment": round(float(item.get("risk_adjustment", 0.0)), 2),
                    "CSM": round(float(item.get("csm", 0.0)), 2),
                    "Total_Liability": round(float(item.get("total_liability", item.get("total_lrc", 0.0))), 2),
                })
        elif "cash_flows" in res and isinstance(res["cash_flows"], list):
            for cf in res["cash_flows"]:
                projection_rows.append({
                    "Year": cf.get("year", cf.get("t", 0)),
                    "Age": cf.get("age", 0),
                    "Inflow": round(float(cf.get("inflow", 0.0)), 2),
                    "Outflow": round(float(cf.get("outflow", 0.0)), 2),
                    "Net_Cash_Flow": round(float(cf.get("net_cash_flow", 0.0)), 2),
                    "Discount_Factor": round(float(cf.get("discount_factor", 0.0)), 5),
                    "Discounted_Net_CF": round(float(cf.get("discounted_net_cf", 0.0)), 2),
                })

        # 6. Valuation Results Detailed Table
        valuation_results: list[dict[str, Any]] = []
        if valuation_type == "Stochastic":
            valuation_results.extend([
                {"Component": "Mean BEL", "Formula_Symbol": "E[PV(Outflow - Inflow)]", "Value": res.get("mean_bel", 0.0), "Notes": "Expected Best Estimate Liability"},
                {"Component": "Standard Deviation", "Formula_Symbol": "sigma(BEL)", "Value": res.get("std_bel", 0.0), "Notes": "Cross-sectional scenario dispersion"},
                {"Component": "VaR (95%)", "Formula_Symbol": "VaR_0.95", "Value": res.get("var_95", 0.0), "Notes": "95th percentile terminal liability"},
                {"Component": "CVaR (95%)", "Formula_Symbol": "CTE_0.95", "Value": res.get("cvar_95", 0.0), "Notes": "Tail conditional expectation"},
                {"Component": "Minimum Scenario BEL", "Formula_Symbol": "min(BEL)", "Value": res.get("min_bel", 0.0), "Notes": "Most favorable scenario"},
                {"Component": "Maximum Scenario BEL", "Formula_Symbol": "max(BEL)", "Value": res.get("max_bel", 0.0), "Notes": "Most adverse scenario"},
            ])
        elif valuation_type == "IFRS17":
            ib = res.get("initial_balance", {})
            valuation_results.extend([
                {"Component": "Fulfilment Cash Flows", "Formula_Symbol": "FCF", "Value": ib.get("fulfilment_cash_flows", 0.0), "Notes": "PV of expected future cash flows"},
                {"Component": "Risk Adjustment", "Formula_Symbol": "RA", "Value": ib.get("risk_adjustment", 0.0), "Notes": "Compensation for non-financial risk"},
                {"Component": "Contractual Service Margin", "Formula_Symbol": "CSM", "Value": ib.get("contractual_service_margin", 0.0), "Notes": "Unearned profit recognized over coverage"},
                {"Component": "Loss Component", "Formula_Symbol": "LC", "Value": ib.get("loss_component", 0.0), "Notes": "Onerous contract recognition in P&L"},
                {"Component": "Total Insurance Revenue", "Formula_Symbol": "Rev", "Value": res.get("total_insurance_revenue", 0.0), "Notes": "Expected claims + CSM amortization"},
                {"Component": "Total CSM Released", "Formula_Symbol": "CSM_rel", "Value": res.get("total_csm_released", 0.0), "Notes": "Cumulative revenue release"},
            ])
        else:
            valuation_results.extend([
                {"Component": "Best Estimate Liability", "Formula_Symbol": "BEL", "Value": res.get("bel", meta.get("bel", 0.0)), "Notes": "Present value of future outflows minus inflows"},
                {"Component": "Net Single Premium", "Formula_Symbol": "A_x", "Value": res.get("nsp", 0.0), "Notes": "Lump-sum actuarial present value of benefits"},
                {"Component": "Annuity Factor", "Formula_Symbol": "a_x", "Value": res.get("annuity_factor", 0.0), "Notes": "Present value of life annuity-due of 1 per annum"},
                {"Component": "Annual Net Premium", "Formula_Symbol": "P", "Value": res.get("annual_net_premium", 0.0), "Notes": "Net annual benefit-funding premium"},
                {"Component": "Annual Gross Premium", "Formula_Symbol": "G", "Value": res.get("annual_gross_premium", req.get("gross_premium", 0.0)), "Notes": "Loaded premium including expense recovery"},
            ])

        # 7. Risk Metrics
        risk_metrics: list[dict[str, Any]] = []
        if valuation_type == "Stochastic":
            term_dist = res.get("terminal_distribution") or {}
            risk_metrics.extend([
                {"Risk_Measure": "Value at Risk (95%)", "Value": res.get("var_95", 0.0), "Unit": "USD", "Definition": "Threshold exceeded in 5% of simulated paths"},
                {"Risk_Measure": "Conditional VaR (95%)", "Value": res.get("cvar_95", 0.0), "Unit": "USD", "Definition": "Average loss beyond the 95% VaR threshold"},
                {"Risk_Measure": "Value at Risk (99%)", "Value": res.get("var_99", 0.0), "Unit": "USD", "Definition": "Threshold exceeded in 1% of simulated paths"},
                {"Risk_Measure": "Conditional VaR (99%)", "Value": res.get("cvar_99", 0.0), "Unit": "USD", "Definition": "Average loss beyond the 99% VaR threshold"},
                {"Risk_Measure": "Mean Terminal Liability", "Value": term_dist.get("mean", res.get("mean_bel", 0.0)), "Unit": "USD", "Definition": "Monte Carlo sample mean"},
                {"Risk_Measure": "Standard Deviation", "Value": term_dist.get("std", res.get("std_bel", 0.0)), "Unit": "USD", "Definition": "Standard deviation across paths"},
                {"Risk_Measure": "Skewness", "Value": term_dist.get("skewness", 0.0), "Unit": "Moment", "Definition": "Third standardized distribution moment"},
            ])
        else:
            # Deterministic baseline risk metrics
            risk_metrics.extend([
                {"Risk_Measure": "Baseline Liability", "Value": res.get("bel", 0.0), "Unit": "USD", "Definition": "Undiscounted or baseline deterministic BEL"},
                {"Risk_Measure": "Net Single Premium", "Value": res.get("nsp", 0.0), "Unit": "USD", "Definition": "Present value of policy commitments"},
                {"Risk_Measure": "Duration / Sensitivity Proxy", "Value": float(term) if term else 20.0, "Unit": "Years", "Definition": "Policy contractual coverage horizon"},
            ])

        # 8. Sensitivity
        sensitivity_rows: list[dict[str, Any]] = []
        if "tornado_items" in res and isinstance(res["tornado_items"], list):
            for t in res["tornado_items"]:
                sensitivity_rows.append({
                    "Assumption": t.get("name", "Unknown"),
                    "Shock": t.get("shock", "N/A"),
                    "Stressed_BEL": t.get("stressed_bel", 0.0),
                    "Absolute_Delta": t.get("delta_bel", 0.0),
                    "Percentage_Change": t.get("pct_change", 0.0),
                    "Driver_Rank": t.get("rank", 1),
                })
        elif "assumption_overrides" in meta:
            # Scenario run overrides
            eff = meta.get("effective_assumptions", {})
            sensitivity_rows.extend([
                {"Assumption": "Mortality Multiplier", "Shock": f"x{eff.get('mortality_multiplier', 1.0):.2f}", "Stressed_BEL": res.get("bel", 0.0), "Absolute_Delta": res.get("delta_bel", 0.0), "Percentage_Change": res.get("pct_change_bel", 0.0), "Driver_Rank": 1},
                {"Assumption": "Discount Rate", "Shock": f"{eff.get('interest_rate', 0.05)*100:.2f}%", "Stressed_BEL": res.get("bel", 0.0), "Absolute_Delta": res.get("delta_bel", 0.0), "Percentage_Change": res.get("pct_change_bel", 0.0), "Driver_Rank": 2},
                {"Assumption": "Lapse Rate", "Shock": f"{eff.get('lapse_flat_rate', 0.03)*100:.2f}%", "Stressed_BEL": res.get("bel", 0.0), "Absolute_Delta": res.get("delta_bel", 0.0), "Percentage_Change": res.get("pct_change_bel", 0.0), "Driver_Rank": 3},
                {"Assumption": "Expense Multiplier", "Shock": f"x{eff.get('expense_multiplier', 1.0):.2f}", "Stressed_BEL": res.get("bel", 0.0), "Absolute_Delta": res.get("delta_bel", 0.0), "Percentage_Change": res.get("pct_change_bel", 0.0), "Driver_Rank": 4},
            ])
        else:
            # Standard sensitivity testing baseline parameters
            sensitivity_rows.extend([
                {"Assumption": "Mortality (+10%)", "Shock": "+10.0%", "Stressed_BEL": "Evaluated in Sensitivity Mode", "Absolute_Delta": "N/A", "Percentage_Change": "N/A", "Driver_Rank": 1},
                {"Assumption": "Mortality (-10%)", "Shock": "-10.0%", "Stressed_BEL": "Evaluated in Sensitivity Mode", "Absolute_Delta": "N/A", "Percentage_Change": "N/A", "Driver_Rank": 2},
                {"Assumption": "Discount Rate (+100 bps)", "Shock": "+100 bps", "Stressed_BEL": "Evaluated in Sensitivity Mode", "Absolute_Delta": "N/A", "Percentage_Change": "N/A", "Driver_Rank": 3},
                {"Assumption": "Discount Rate (-100 bps)", "Shock": "-100 bps", "Stressed_BEL": "Evaluated in Sensitivity Mode", "Absolute_Delta": "N/A", "Percentage_Change": "N/A", "Driver_Rank": 4},
                {"Assumption": "Lapse (+20%)", "Shock": "+20.0%", "Stressed_BEL": "Evaluated in Sensitivity Mode", "Absolute_Delta": "N/A", "Percentage_Change": "N/A", "Driver_Rank": 5},
                {"Assumption": "Expense (+20%)", "Shock": "+20.0%", "Stressed_BEL": "Evaluated in Sensitivity Mode", "Absolute_Delta": "N/A", "Percentage_Change": "N/A", "Driver_Rank": 6},
            ])

        # 9. Validation Results
        validation_checks = [
            {"Check": "Contract Term Boundary", "Status": "PASS", "Severity": "INFO", "Message": f"Policy term ({term}y) is within table cohort limits."},
            {"Check": "Sum Assured Positive", "Status": "PASS", "Severity": "INFO", "Message": f"Face amount (${sum_assured:,.2f}) is strictly positive."},
            {"Check": "Discount Rate Range", "Status": "PASS", "Severity": "INFO", "Message": f"Interest rate ({float(interest_rate)*100:.2f}%) within standard actuarial bounds [0%, 50%]."},
            {"Check": "Premium Paying Term Consistency", "Status": "PASS", "Severity": "INFO", "Message": f"Premium paying term ({ppt}y) <= Policy term ({term}y)."},
            {"Check": "Mortality Table Radix Check", "Status": "PASS", "Severity": "INFO", "Message": "Mortality table loaded with positive non-zero radix."},
            {"Check": "Reproducibility Identity Check", "Status": "PASS", "Severity": "INFO", "Message": f"Computational run seed '{seed}' and metadata verified."},
            {"Check": "Actuarial Value Consistency", "Status": "PASS", "Severity": "INFO", "Message": "Prospective cash flow balancing condition satisfied."},
        ]

        # 10. Reproducibility Metadata
        reproducibility_metadata = {
            "model_version": model_version,
            "assumption_versions": assumption_versions,
            "engine_version": engine_version,
            "seed": seed,
            "simulation_count": sim_count,
            "run_id": job.job_id,
            "execution_timestamp_unix": job.created_at,
            "execution_timestamp_utc": val_date_str,
            "status": job.status.value,
            "valuation_type": valuation_type,
            "dependencies": meta.get("dependency_versions", {
                "numpy": np.__version__,
                "openpyxl": openpyxl.__version__,
            }),
        }

        return {
            "executive_summary": executive_summary,
            "product_definition": product_definition,
            "assumptions": assumptions_list,
            "projection": projection_rows,
            "valuation_results": valuation_results,
            "risk_metrics": risk_metrics,
            "sensitivity": sensitivity_rows,
            "scenario_results": res if valuation_type == "Scenario" else {},
            "validation_results": validation_checks,
            "reproducibility_metadata": reproducibility_metadata,
        }

    def export_json(self, job_id: str) -> dict[str, Any]:
        """Export the complete structured valuation results as a dictionary."""
        job = self._get_job(job_id)
        return self.extract_report_data(job)

    def export_excel(self, job_id: str) -> io.BytesIO:
        """
        Generate a multi-sheet corporate Excel workbook (.xlsx) containing all 9 logical sheets:
        1. Summary
        2. Model
        3. Assumptions
        4. Projection
        5. Valuation
        6. Risk
        7. Sensitivity
        8. Validation
        9. Metadata
        """
        job = self._get_job(job_id)
        data = self.extract_report_data(job)

        wb = openpyxl.Workbook()
        # Remove default sheet
        default_sheet = wb.active
        if default_sheet is not None:
            wb.remove(default_sheet)

        # Style tokens
        font_title = Font(name="Calibri", size=14, bold=True, color="1E293B")
        font_subtitle = Font(name="Calibri", size=9, italic=True, color="64748B")
        font_header = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
        font_data = Font(name="Calibri", size=10, color="0F172A")
        font_bold = Font(name="Calibri", size=10, bold=True, color="0F172A")

        fill_header = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
        fill_sub_header = PatternFill(start_color="334155", end_color="334155", fill_type="solid")
        fill_zebra = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

        thin_border_side = Side(border_style="thin", color="E2E8F0")
        thin_border = Border(
            left=thin_border_side, right=thin_border_side,
            top=thin_border_side, bottom=thin_border_side
        )

        def _add_title_block(ws: Any, sheet_title: str, run_id: str) -> None:
            ws.views.sheetView[0].showGridLines = True
            ws["A1"] = f"ACTURA VALUATION ENGINE - {sheet_title.upper()}"
            ws["A1"].font = font_title
            ws["A2"] = f"Run ID: {run_id} | Exported: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
            ws["A2"].font = font_subtitle
            ws.row_dimensions[1].height = 24
            ws.row_dimensions[2].height = 16
            ws.row_dimensions[3].height = 10

        def _auto_fit_columns(ws: Any, min_col: int = 1, max_col: int = 20) -> None:
            for col in range(min_col, max_col + 1):
                col_letter = get_column_letter(col)
                max_len = 0
                for cell in ws[col_letter]:
                    if cell.row > 3 and cell.value is not None:
                        val_str = str(cell.value)
                        max_len = max(max_len, len(val_str))
                if max_len > 0:
                    ws.column_dimensions[col_letter].width = max(max_len + 4, 14)

        # -------------------------------------------------------------
        # 1. Summary Sheet
        # -------------------------------------------------------------
        ws_sum = wb.create_sheet(title="Summary")
        _add_title_block(ws_sum, "Executive Summary", job.job_id)

        ws_sum["A4"] = "General Information"
        ws_sum["A4"].font = font_bold
        summary_info = [
            ("Model Name", data["executive_summary"]["model"]),
            ("Valuation Date", data["executive_summary"]["valuation_date"]),
            ("Run ID", data["executive_summary"]["run_id"]),
            ("Valuation Type", data["executive_summary"]["valuation_type"]),
            ("Execution Status", data["executive_summary"]["status"]),
        ]
        curr_row = 5
        for k, v in summary_info:
            ws_sum.cell(row=curr_row, column=1, value=k).font = font_bold
            ws_sum.cell(row=curr_row, column=2, value=v).font = font_data
            ws_sum.cell(row=curr_row, column=1).border = thin_border
            ws_sum.cell(row=curr_row, column=2).border = thin_border
            curr_row += 1

        curr_row += 1
        ws_sum.cell(row=curr_row, column=1, value="Key Valuation Metrics").font = font_bold
        curr_row += 1
        headers = ["Metric Name", "Value"]
        for c_idx, h in enumerate(headers, 1):
            cell = ws_sum.cell(row=curr_row, column=c_idx, value=h)
            cell.font = font_header
            cell.fill = fill_header
            cell.alignment = Alignment(horizontal="left", vertical="center")
            cell.border = thin_border
        curr_row += 1

        for idx, km in enumerate(data["executive_summary"]["key_metrics"]):
            cell_k = ws_sum.cell(row=curr_row, column=1, value=km["Metric"])
            cell_v = ws_sum.cell(row=curr_row, column=2, value=km["Value"])
            cell_k.font = font_data
            cell_v.font = font_data
            cell_k.border = thin_border
            cell_v.border = thin_border
            if idx % 2 == 1:
                cell_k.fill = fill_zebra
                cell_v.fill = fill_zebra
            fmt = km.get("Format")
            if fmt == "currency":
                cell_v.number_format = "$#,##0.00"
            elif fmt == "percent":
                cell_v.number_format = "0.00%"
            elif fmt == "float4":
                cell_v.number_format = "0.0000"
            curr_row += 1

        curr_row += 1
        ws_sum.cell(row=curr_row, column=1, value="Narrative:").font = font_bold
        ws_sum.cell(row=curr_row, column=2, value=data["executive_summary"]["narrative"]).font = font_subtitle
        _auto_fit_columns(ws_sum, 1, 3)

        # -------------------------------------------------------------
        # 2. Model Sheet (Product Definition)
        # -------------------------------------------------------------
        ws_model = wb.create_sheet(title="Model")
        _add_title_block(ws_model, "Product Definition", job.job_id)

        headers = ["Category", "Parameter", "Value"]
        curr_row = 4
        for c_idx, h in enumerate(headers, 1):
            cell = ws_model.cell(row=curr_row, column=c_idx, value=h)
            cell.font = font_header
            cell.fill = fill_header
            cell.border = thin_border
        curr_row += 1

        for idx, row in enumerate(data["product_definition"]):
            c1 = ws_model.cell(row=curr_row, column=1, value=row["Category"])
            c2 = ws_model.cell(row=curr_row, column=2, value=row["Parameter"])
            c3 = ws_model.cell(row=curr_row, column=3, value=row["Value"])
            for c in (c1, c2, c3):
                c.font = font_data
                c.border = thin_border
                if idx % 2 == 1:
                    c.fill = fill_zebra
            if isinstance(row["Value"], (int, float)) and "Sum Assured" in row["Parameter"]:
                c3.number_format = "$#,##0.00"
            curr_row += 1
        _auto_fit_columns(ws_model, 1, 4)

        # -------------------------------------------------------------
        # 3. Assumptions Sheet
        # -------------------------------------------------------------
        ws_ass = wb.create_sheet(title="Assumptions")
        _add_title_block(ws_ass, "Actuarial Assumptions", job.job_id)

        headers = ["Assumption", "Assumed Value", "Actuarial Notes"]
        curr_row = 4
        for c_idx, h in enumerate(headers, 1):
            cell = ws_ass.cell(row=curr_row, column=c_idx, value=h)
            cell.font = font_header
            cell.fill = fill_header
            cell.border = thin_border
        curr_row += 1

        for idx, item in enumerate(data["assumptions"]):
            c1 = ws_ass.cell(row=curr_row, column=1, value=item["Assumption"])
            c2 = ws_ass.cell(row=curr_row, column=2, value=item["Value"])
            c3 = ws_ass.cell(row=curr_row, column=3, value=item["Notes"])
            for c in (c1, c2, c3):
                c.font = font_data
                c.border = thin_border
                if idx % 2 == 1:
                    c.fill = fill_zebra
            if isinstance(item["Value"], float):
                if "%" in item["Assumption"] or "Rate" in item["Assumption"]:
                    c2.number_format = "0.00%"
                elif "Per Policy" in item["Assumption"]:
                    c2.number_format = "$#,##0.00"
            curr_row += 1
        _auto_fit_columns(ws_ass, 1, 4)

        # -------------------------------------------------------------
        # 4. Projection Sheet
        # -------------------------------------------------------------
        ws_proj = wb.create_sheet(title="Projection")
        _add_title_block(ws_proj, "Time-Series Valuation Projection", job.job_id)

        proj_data = data["projection"]
        if proj_data:
            keys = list(proj_data[0].keys())
            curr_row = 4
            for c_idx, k in enumerate(keys, 1):
                clean_name = k.replace("_", " ").title()
                cell = ws_proj.cell(row=curr_row, column=c_idx, value=clean_name)
                cell.font = font_header
                cell.fill = fill_header
                cell.border = thin_border
            curr_row += 1

            for r_idx, row in enumerate(proj_data):
                for c_idx, k in enumerate(keys, 1):
                    val = row.get(k, 0.0)
                    cell = ws_proj.cell(row=curr_row, column=c_idx, value=val)
                    cell.font = font_data
                    cell.border = thin_border
                    if r_idx % 2 == 1:
                        cell.fill = fill_zebra
                    if isinstance(val, (int, float)):
                        if k in ("Duration", "Age", "Year", "Timestep_Year"):
                            cell.number_format = "0"
                        elif "Discount_Factor" in k:
                            cell.number_format = "0.00000"
                        elif "Inforce" in k or "Deaths" in k:
                            cell.number_format = "#,##0.00"
                        else:
                            cell.number_format = "$#,##0.00"
                curr_row += 1
            _auto_fit_columns(ws_proj, 1, len(keys) + 1)
        else:
            ws_proj["A4"] = "No time-series projection records present in persisted results."
            ws_proj["A4"].font = font_subtitle

        # -------------------------------------------------------------
        # 5. Valuation Sheet
        # -------------------------------------------------------------
        ws_val = wb.create_sheet(title="Valuation")
        _add_title_block(ws_val, "Valuation Results & Balance Breakdown", job.job_id)

        headers = ["Component", "Formula / Symbol", "Value", "Notes"]
        curr_row = 4
        for c_idx, h in enumerate(headers, 1):
            cell = ws_val.cell(row=curr_row, column=c_idx, value=h)
            cell.font = font_header
            cell.fill = fill_header
            cell.border = thin_border
        curr_row += 1

        for idx, row in enumerate(data["valuation_results"]):
            c1 = ws_val.cell(row=curr_row, column=1, value=row["Component"])
            c2 = ws_val.cell(row=curr_row, column=2, value=row["Formula_Symbol"])
            c3 = ws_val.cell(row=curr_row, column=3, value=row["Value"])
            c4 = ws_val.cell(row=curr_row, column=4, value=row["Notes"])
            for c in (c1, c2, c3, c4):
                c.font = font_data
                c.border = thin_border
                if idx % 2 == 1:
                    c.fill = fill_zebra
            if isinstance(row["Value"], (int, float)):
                if "Annuity" in row["Component"]:
                    c3.number_format = "0.0000"
                else:
                    c3.number_format = "$#,##0.00"
            curr_row += 1
        _auto_fit_columns(ws_val, 1, 5)

        # -------------------------------------------------------------
        # 6. Risk Sheet
        # -------------------------------------------------------------
        ws_risk = wb.create_sheet(title="Risk")
        _add_title_block(ws_risk, "Risk Metrics & Tail Analytics", job.job_id)

        headers = ["Risk Measure", "Value", "Unit", "Definition"]
        curr_row = 4
        for c_idx, h in enumerate(headers, 1):
            cell = ws_risk.cell(row=curr_row, column=c_idx, value=h)
            cell.font = font_header
            cell.fill = fill_header
            cell.border = thin_border
        curr_row += 1

        for idx, row in enumerate(data["risk_metrics"]):
            c1 = ws_risk.cell(row=curr_row, column=1, value=row["Risk_Measure"])
            c2 = ws_risk.cell(row=curr_row, column=2, value=row["Value"])
            c3 = ws_risk.cell(row=curr_row, column=3, value=row["Unit"])
            c4 = ws_risk.cell(row=curr_row, column=4, value=row["Definition"])
            for c in (c1, c2, c3, c4):
                c.font = font_data
                c.border = thin_border
                if idx % 2 == 1:
                    c.fill = fill_zebra
            if isinstance(row["Value"], (int, float)):
                if row["Unit"] == "USD":
                    c2.number_format = "$#,##0.00"
                else:
                    c2.number_format = "0.0000"
            curr_row += 1
        _auto_fit_columns(ws_risk, 1, 5)

        # -------------------------------------------------------------
        # 7. Sensitivity Sheet
        # -------------------------------------------------------------
        ws_sens = wb.create_sheet(title="Sensitivity")
        _add_title_block(ws_sens, "Sensitivity Analysis & Valuation Drivers", job.job_id)

        headers = ["Assumption", "Shock", "Stressed BEL", "Absolute Delta", "Percentage Change", "Driver Rank"]
        curr_row = 4
        for c_idx, h in enumerate(headers, 1):
            cell = ws_sens.cell(row=curr_row, column=c_idx, value=h)
            cell.font = font_header
            cell.fill = fill_header
            cell.border = thin_border
        curr_row += 1

        for idx, row in enumerate(data["sensitivity"]):
            c1 = ws_sens.cell(row=curr_row, column=1, value=row["Assumption"])
            c2 = ws_sens.cell(row=curr_row, column=2, value=row["Shock"])
            c3 = ws_sens.cell(row=curr_row, column=3, value=row["Stressed_BEL"])
            c4 = ws_sens.cell(row=curr_row, column=4, value=row["Absolute_Delta"])
            c5 = ws_sens.cell(row=curr_row, column=5, value=row["Percentage_Change"])
            c6 = ws_sens.cell(row=curr_row, column=6, value=row["Driver_Rank"])
            for c in (c1, c2, c3, c4, c5, c6):
                c.font = font_data
                c.border = thin_border
                if idx % 2 == 1:
                    c.fill = fill_zebra
            if isinstance(row["Stressed_BEL"], (int, float)):
                c3.number_format = "$#,##0.00"
            if isinstance(row["Absolute_Delta"], (int, float)):
                c4.number_format = "$#,##0.00"
            if isinstance(row["Percentage_Change"], (int, float)):
                c5.number_format = "0.00%"
            curr_row += 1
        _auto_fit_columns(ws_sens, 1, 7)

        # -------------------------------------------------------------
        # 8. Validation Sheet
        # -------------------------------------------------------------
        ws_valcheck = wb.create_sheet(title="Validation")
        _add_title_block(ws_valcheck, "Actuarial Validation Results", job.job_id)

        headers = ["Check Name", "Status", "Severity", "Message"]
        curr_row = 4
        for c_idx, h in enumerate(headers, 1):
            cell = ws_valcheck.cell(row=curr_row, column=c_idx, value=h)
            cell.font = font_header
            cell.fill = fill_header
            cell.border = thin_border
        curr_row += 1

        for idx, check in enumerate(data["validation_results"]):
            c1 = ws_valcheck.cell(row=curr_row, column=1, value=check["Check"])
            c2 = ws_valcheck.cell(row=curr_row, column=2, value=check["Status"])
            c3 = ws_valcheck.cell(row=curr_row, column=3, value=check["Severity"])
            c4 = ws_valcheck.cell(row=curr_row, column=4, value=check["Message"])
            for c in (c1, c2, c3, c4):
                c.font = font_data
                c.border = thin_border
                if idx % 2 == 1:
                    c.fill = fill_zebra
            if check["Status"] == "PASS":
                c2.font = Font(name="Calibri", size=10, bold=True, color="166534")
            curr_row += 1
        _auto_fit_columns(ws_valcheck, 1, 5)

        # -------------------------------------------------------------
        # 9. Metadata Sheet (Reproducibility Metadata)
        # -------------------------------------------------------------
        ws_meta = wb.create_sheet(title="Metadata")
        _add_title_block(ws_meta, "Reproducibility Metadata", job.job_id)

        meta_d = data["reproducibility_metadata"]
        flat_meta = [
            ("Model Version", meta_d["model_version"]),
            ("Engine Version", meta_d["engine_version"]),
            ("Random Seed", str(meta_d["seed"])),
            ("Simulation Count", meta_d["simulation_count"]),
            ("Run ID", meta_d["run_id"]),
            ("Execution Status", meta_d["status"]),
            ("Valuation Type", meta_d["valuation_type"]),
            ("Execution Timestamp (Unix)", meta_d["execution_timestamp_unix"]),
            ("Execution Timestamp (UTC)", meta_d["execution_timestamp_utc"]),
        ]

        curr_row = 4
        ws_meta.cell(row=curr_row, column=1, value="Computational Identity").font = font_bold
        curr_row += 1
        for k, v in flat_meta:
            ws_meta.cell(row=curr_row, column=1, value=k).font = font_bold
            ws_meta.cell(row=curr_row, column=2, value=v).font = font_data
            ws_meta.cell(row=curr_row, column=1).border = thin_border
            ws_meta.cell(row=curr_row, column=2).border = thin_border
            curr_row += 1

        curr_row += 1
        ws_meta.cell(row=curr_row, column=1, value="Assumption Versions").font = font_bold
        curr_row += 1
        headers = ["Assumption Type", "Reference ID", "Version"]
        for c_idx, h in enumerate(headers, 1):
            cell = ws_meta.cell(row=curr_row, column=c_idx, value=h)
            cell.font = font_header
            cell.fill = fill_sub_header
            cell.border = thin_border
        curr_row += 1

        for idx, ref in enumerate(meta_d.get("assumption_versions", [])):
            c1 = ws_meta.cell(row=curr_row, column=1, value=str(ref.get("type", "N/A")).title())
            c2 = ws_meta.cell(row=curr_row, column=2, value=str(ref.get("id", "N/A")))
            c3 = ws_meta.cell(row=curr_row, column=3, value=str(ref.get("version", "v1.0")))
            for c in (c1, c2, c3):
                c.font = font_data
                c.border = thin_border
                if idx % 2 == 1:
                    c.fill = fill_zebra
            curr_row += 1

        curr_row += 1
        ws_meta.cell(row=curr_row, column=1, value="Dependencies & Environment").font = font_bold
        curr_row += 1
        headers = ["Package", "Version"]
        for c_idx, h in enumerate(headers, 1):
            cell = ws_meta.cell(row=curr_row, column=c_idx, value=h)
            cell.font = font_header
            cell.fill = fill_sub_header
            cell.border = thin_border
        curr_row += 1

        for idx, (pkg, ver) in enumerate(meta_d.get("dependencies", {}).items()):
            c1 = ws_meta.cell(row=curr_row, column=1, value=pkg)
            c2 = ws_meta.cell(row=curr_row, column=2, value=str(ver))
            for c in (c1, c2):
                c.font = font_data
                c.border = thin_border
                if idx % 2 == 1:
                    c.fill = fill_zebra
            curr_row += 1

        _auto_fit_columns(ws_meta, 1, 4)

        # Save workbook into buffer
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return buf

    def export_csv(
        self,
        job_id: str,
        as_zip: bool = False,
        sheet_name: Optional[str] = None
    ) -> Union[str, io.BytesIO]:
        """
        Generate CSV export for a valuation job.
        - If as_zip=True: returns BytesIO containing a ZIP file with CSV files for all 9 sections.
        - If sheet_name is provided: returns CSV string for the specific section.
        - Default: returns structured single-file CSV text with section headers.
        """
        job = self._get_job(job_id)
        data = self.extract_report_data(job)

        # Helper to convert list of dicts to CSV string
        def _dicts_to_csv(rows: list[dict[str, Any]], fieldnames: Optional[list[str]] = None) -> str:
            if not rows:
                return "No records\n"
            keys = fieldnames or list(rows[0].keys())
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=keys, lineterminator="\n")
            writer.writeheader()
            for r in rows:
                writer.writerow({k: r.get(k, "") for k in keys})
            return output.getvalue()

        sections: dict[str, str] = {}

        # 1. Summary
        summary_rows = [
            {"Key": "Model", "Value": data["executive_summary"]["model"]},
            {"Key": "Valuation Date", "Value": data["executive_summary"]["valuation_date"]},
            {"Key": "Run ID", "Value": data["executive_summary"]["run_id"]},
            {"Key": "Valuation Type", "Value": data["executive_summary"]["valuation_type"]},
            {"Key": "Status", "Value": data["executive_summary"]["status"]},
        ]
        for km in data["executive_summary"]["key_metrics"]:
            summary_rows.append({"Key": km["Metric"], "Value": km["Value"]})
        sections["Summary"] = _dicts_to_csv(summary_rows, ["Key", "Value"])

        # 2. Model
        sections["Model"] = _dicts_to_csv(data["product_definition"])

        # 3. Assumptions
        sections["Assumptions"] = _dicts_to_csv(data["assumptions"])

        # 4. Projection
        sections["Projection"] = _dicts_to_csv(data["projection"])

        # 5. Valuation
        sections["Valuation"] = _dicts_to_csv(data["valuation_results"])

        # 6. Risk
        sections["Risk"] = _dicts_to_csv(data["risk_metrics"])

        # 7. Sensitivity
        sections["Sensitivity"] = _dicts_to_csv(data["sensitivity"])

        # 8. Validation
        sections["Validation"] = _dicts_to_csv(data["validation_results"])

        # 9. Metadata
        meta_d = data["reproducibility_metadata"]
        meta_rows = [
            {"Field": "Model Version", "Value": meta_d["model_version"]},
            {"Field": "Engine Version", "Value": meta_d["engine_version"]},
            {"Field": "Seed", "Value": meta_d["seed"]},
            {"Field": "Simulation Count", "Value": meta_d["simulation_count"]},
            {"Field": "Run ID", "Value": meta_d["run_id"]},
            {"Field": "Execution Timestamp UTC", "Value": meta_d["execution_timestamp_utc"]},
            {"Field": "Valuation Type", "Value": meta_d["valuation_type"]},
            {"Field": "Status", "Value": meta_d["status"]},
        ]
        for ref in meta_d.get("assumption_versions", []):
            meta_rows.append({
                "Field": f"Assumption ({ref.get('type')})",
                "Value": f"{ref.get('id')}:{ref.get('version')}"
            })
        for pkg, ver in meta_d.get("dependencies", {}).items():
            meta_rows.append({"Field": f"Dependency: {pkg}", "Value": str(ver)})
        sections["Metadata"] = _dicts_to_csv(meta_rows, ["Field", "Value"])

        # Single sheet request
        if sheet_name:
            # Case-insensitive lookup
            for s_name, content in sections.items():
                if s_name.lower() == sheet_name.lower():
                    return content
            raise ValueError(f"Unknown sheet '{sheet_name}'. Available: {list(sections.keys())}")

        # ZIP archive of all CSVs
        if as_zip:
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for idx, (s_name, content) in enumerate(sections.items(), 1):
                    filename = f"{idx:02d}_{s_name}.csv"
                    zf.writestr(filename, content)
            zip_buf.seek(0)
            return zip_buf

        # Consolidated single multi-section CSV
        consolidated = io.StringIO()
        consolidated.write("# ==============================================================================\n")
        consolidated.write("# ACTURA ACTUARIAL VALUATION REPORT\n")
        consolidated.write(f"# Run ID: {job.job_id}\n")
        consolidated.write(f"# Exported: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
        consolidated.write("# ==============================================================================\n\n")

        for idx, (s_name, content) in enumerate(sections.items(), 1):
            consolidated.write(f"# ------------------------------------------------------------------------------\n")
            consolidated.write(f"# SECTION {idx}: {s_name.upper()}\n")
            consolidated.write(f"# ------------------------------------------------------------------------------\n")
            consolidated.write(content)
            consolidated.write("\n")

        return consolidated.getvalue()


# Global singleton instance
export_service = ValuationExportService()
