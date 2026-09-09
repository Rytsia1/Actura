"""
Valuation Run Comparison and Configuration Difference Explanation Service.

Enables transparent side-by-side comparison of any two valuation runs.
Extracts normalized metrics (BEL, CSM, risk metrics, premiums, benefits, expenses, profit/loss),
computes absolute and percentage deltas, identifies changed configuration elements,
and generates human-readable difference explanations.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from actuary_engine.api.job_manager import job_manager
from actuary_engine.api.schemas import (
    ConfigComparisonItem,
    MetricComparisonItem,
    RunComparisonResponse,
    RunSummaryInfo,
)


class RunComparisonService:
    def __init__(self) -> None:
        self.jobs = job_manager

    def get_comparable_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return a list of completed valuation runs available for comparison."""
        all_jobs = self.jobs.list_jobs(limit=limit)
        comparable = []
        for j in all_jobs:
            if j.status.value != "COMPLETED":
                continue
            meta = j.run_metadata or {}
            req = j.original_request or {}
            res = j.result or {}

            # Extract a friendly model/scenario name
            name = (
                meta.get("scenario")
                or meta.get("base_model_name")
                or req.get("product_type", "Valuation Run").title()
            )

            # Try to grab primary metric for quick display
            bel = (
                res.get("bel")
                or res.get("mean_bel")
                or res.get("stressed_bel")
                or res.get("initial_balance", {}).get("bel_0")
                or meta.get("base_bel")
            )

            comparable.append({
                "job_id": j.job_id,
                "valuation_type": meta.get("valuation_type", "Valuation"),
                "status": j.status.value,
                "created_at": j.created_at,
                "name": name,
                "bel": round(float(bel), 2) if bel is not None else None,
                "model_version": meta.get("model_version") or req.get("contract_id") or "1.0",
                "scenario": meta.get("scenario", "Base"),
                "engine_version": meta.get("engine_version", "1.0.0"),
            })
        return comparable

    def compare_runs(self, run_a_id: str, run_b_id: str) -> RunComparisonResponse:
        """Compare Run A and Run B, calculate deltas, and explain differences."""
        job_a = self.jobs.get_job(run_a_id)
        if not job_a:
            raise ValueError(f"Run A '{run_a_id}' not found.")
        job_b = self.jobs.get_job(run_b_id)
        if not job_b:
            raise ValueError(f"Run B '{run_b_id}' not found.")

        # 1. Extract Summary Info
        summary_a = self._extract_summary_info(job_a)
        summary_b = self._extract_summary_info(job_b)

        # 2. Extract and Compare Metrics
        metrics_map_a = self._extract_metrics(job_a)
        metrics_map_b = self._extract_metrics(job_b)
        metric_items = self._build_metric_comparisons(metrics_map_a, metrics_map_b)

        # 3. Extract and Compare Configurations
        config_items = self._build_config_comparisons(job_a, job_b)
        changed_elements = [c.label for c in config_items if c.has_changed]

        # 4. Generate High-Level Plain English Explanation
        summary_explanation = self._generate_explanation(metric_items, changed_elements)

        return RunComparisonResponse(
            run_a=summary_a,
            run_b=summary_b,
            metrics=metric_items,
            configurations=config_items,
            changed_elements=changed_elements,
            summary_explanation=summary_explanation,
        )

    def _extract_summary_info(self, job: Any) -> RunSummaryInfo:
        meta = job.run_metadata or {}
        req = job.original_request or {}
        model_name = (
            meta.get("base_model_name")
            or req.get("product_type", "Insurance Policy").title()
        )
        duration = None
        if job.updated_at and job.created_at:
            duration = round(float(job.updated_at - job.created_at), 2)

        return RunSummaryInfo(
            job_id=job.job_id,
            valuation_type=meta.get("valuation_type", "Valuation"),
            status=job.status.value,
            created_at=job.created_at,
            completed_at=job.updated_at,
            duration_seconds=duration,
            model_name=model_name,
            scenario_name=meta.get("scenario") or meta.get("scenario_name") or "Base",
            engine_version=meta.get("engine_version", "1.0.0"),
        )

    def _extract_metrics(self, job: Any) -> dict[str, float]:
        """Extract a flattened dictionary of normalized valuation metrics from job data."""
        metrics: dict[str, float] = {}
        res = job.result or {}
        meta = job.run_metadata or {}
        req = job.original_request or {}

        # If result is stored as JSON string in raw DB row
        if isinstance(res, str):
            try:
                res = json.loads(res)
            except Exception:
                res = {}

        # 1. Best Estimate Liability (BEL)
        bel_val = (
            res.get("bel")
            or res.get("mean_bel")
            or res.get("stressed_bel")
            or res.get("initial_balance", {}).get("bel_0")
            or meta.get("stressed_bel")
            or meta.get("baseline_bel")
            or meta.get("base_bel")
        )
        if bel_val is not None:
            metrics["bel"] = round(float(bel_val), 2)

        # 2. Contractual Service Margin (CSM)
        csm_val = (
            res.get("csm")
            or res.get("total_csm_released")
            or res.get("initial_balance", {}).get("csm_0")
            or meta.get("csm")
            or meta.get("base_csm")
        )
        if csm_val is not None:
            metrics["csm"] = round(float(csm_val), 2)

        # 3. IFRS 17 LRC & FCF
        init_bal = res.get("initial_balance") or {}
        if init_bal.get("initial_lrc") is not None:
            metrics["initial_lrc"] = round(float(init_bal["initial_lrc"]), 2)
        if init_bal.get("fcf_0") is not None:
            metrics["fcf"] = round(float(init_bal["fcf_0"]), 2)

        # 4. Premiums
        if res.get("annual_net_premium") is not None:
            metrics["annual_net_premium"] = round(float(res["annual_net_premium"]), 2)
        if res.get("annual_gross_premium") is not None:
            metrics["annual_gross_premium"] = round(float(res["annual_gross_premium"]), 2)
        if init_bal.get("pv_future_premiums") is not None:
            metrics["pv_premiums"] = round(float(init_bal["pv_future_premiums"]), 2)

        # 5. Benefits & Claims
        if res.get("nsp") is not None:
            metrics["nsp"] = round(float(res["nsp"]), 2)
        if init_bal.get("pv_future_benefits") is not None:
            metrics["pv_benefits"] = round(float(init_bal["pv_future_benefits"]), 2)

        # 6. Expenses
        if init_bal.get("pv_future_expenses") is not None:
            metrics["pv_expenses"] = round(float(init_bal["pv_future_expenses"]), 2)
        if res.get("total_service_expenses") is not None:
            metrics["total_expenses"] = round(float(res["total_service_expenses"]), 2)

        # 7. Profit / Loss
        pl_val = (
            res.get("profit_loss")
            or meta.get("profit_loss")
            or meta.get("base_profit_loss")
        )
        if pl_val is not None:
            metrics["profit_loss"] = round(float(pl_val), 2)
        elif "bel" in metrics and "pv_premiums" not in metrics:
            # Under GPV without separate premium PV breakdown, profit is approx -BEL
            metrics["profit_loss"] = round(-metrics["bel"], 2)

        # 8. Annuity Factor
        if res.get("annuity_factor") is not None:
            metrics["annuity_factor"] = round(float(res["annuity_factor"]), 4)

        # 9. Risk Metrics
        if init_bal.get("ra_0") is not None:
            metrics["risk_adjustment"] = round(float(init_bal["ra_0"]), 2)
        if res.get("var_995") is not None:
            metrics["var_995"] = round(float(res["var_995"]), 2)
        if res.get("cte_99") is not None:
            metrics["cte_99"] = round(float(res["cte_99"]), 2)
        if res.get("stdev_bel") is not None:
            metrics["stdev_bel"] = round(float(res["stdev_bel"]), 2)

        return metrics

    def _build_metric_comparisons(
        self, map_a: dict[str, float], map_b: dict[str, float]
    ) -> list[MetricComparisonItem]:
        """Construct comparative rows with absolute and percentage deltas."""
        definitions = [
            ("bel", "Best Estimate Liability (BEL)", "liability", "$"),
            ("csm", "Contractual Service Margin (CSM)", "liability", "$"),
            ("initial_lrc", "Initial LRC (IFRS 17)", "liability", "$"),
            ("fcf", "Fulfilment Cash Flows (FCF)", "liability", "$"),
            ("annual_net_premium", "Annual Net Equivalence Premium", "cash_flow", "$"),
            ("annual_gross_premium", "Annual Loaded Gross Premium", "cash_flow", "$"),
            ("pv_premiums", "PV of Future Premiums", "cash_flow", "$"),
            ("pv_benefits", "PV of Future Benefits / Claims", "cash_flow", "$"),
            ("nsp", "Net Single Premium (NSP)", "cash_flow", "$"),
            ("pv_expenses", "PV of Future Expenses", "cash_flow", "$"),
            ("profit_loss", "PV of Underwriting Profit", "profitability", "$"),
            ("annuity_factor", "Annuity Factor (ä)", "profitability", ""),
            ("risk_adjustment", "Risk Adjustment (RA)", "risk", "$"),
            ("var_995", "Value at Risk (VaR 99.5%)", "risk", "$"),
            ("cte_99", "Conditional Tail Expectation (CTE 99%)", "risk", "$"),
            ("stdev_bel", "Liability Volatility (Std Dev)", "risk", "$"),
        ]

        items: list[MetricComparisonItem] = []
        for key, label, category, unit in definitions:
            val_a = map_a.get(key)
            val_b = map_b.get(key)
            if val_a is None and val_b is None:
                continue

            abs_delta = None
            pct_delta = None
            if val_a is not None and val_b is not None:
                abs_delta = round(val_b - val_a, 2)
                denom = max(1.0, abs(val_a))
                pct_delta = round((abs_delta / denom) * 100.0, 2)

            items.append(
                MetricComparisonItem(
                    metric_key=key,
                    metric_label=label,
                    category=category,
                    value_a=val_a,
                    value_b=val_b,
                    absolute_delta=abs_delta,
                    percentage_delta=pct_delta,
                    unit=unit,
                )
            )
        return items

    def _build_config_comparisons(self, job_a: Any, job_b: Any) -> list[ConfigComparisonItem]:
        """Compare configuration and assumption elements between Run A and Run B."""
        configs_to_check = [
            ("model_version", "Model Version", self._extract_model_version),
            ("assumption_versions", "Assumption Versions", self._extract_assumption_versions),
            ("scenario", "Scenario", self._extract_scenario),
            ("discount_rate", "Discount Rate", self._extract_discount_rate),
            ("mortality", "Mortality Assumption", self._extract_mortality),
            ("lapse", "Lapse Assumption", self._extract_lapse),
            ("expense", "Expense Assumption", self._extract_expense),
            ("simulation_count", "Simulation Count", self._extract_sim_count),
            ("random_seed", "Random Seed", self._extract_random_seed),
            ("engine_version", "Engine Version", self._extract_engine_version),
        ]

        items: list[ConfigComparisonItem] = []
        for key, label, extractor in configs_to_check:
            val_a = extractor(job_a)
            val_b = extractor(job_b)

            has_changed = str(val_a).strip() != str(val_b).strip()
            summary = "Identical"
            if has_changed:
                summary = f"Changed from '{val_a}' to '{val_b}'"

            items.append(
                ConfigComparisonItem(
                    element_key=key,
                    label=label,
                    value_a=val_a,
                    value_b=val_b,
                    has_changed=has_changed,
                    change_summary=summary,
                )
            )
        return items

    # --- Extractors for configuration elements ---

    def _extract_model_version(self, job: Any) -> str:
        meta = job.run_metadata or {}
        req = job.original_request or {}
        return (
            meta.get("model_version")
            or req.get("contract_id")
            or meta.get("base_model_id")
            or "v1.0"
        )

    def _extract_assumption_versions(self, job: Any) -> str:
        meta = job.run_metadata or {}
        req = job.original_request or {}
        assump = meta.get("assumption_versions") or req.get("assumption_versions")
        if assump:
            if isinstance(assump, dict):
                return ", ".join(f"{k}:{v}" for k, v in assump.items())
            return str(assump)
        return "Standard v1"

    def _extract_scenario(self, job: Any) -> str:
        meta = job.run_metadata or {}
        return meta.get("scenario") or meta.get("scenario_name") or "Base"

    def _extract_discount_rate(self, job: Any) -> str:
        meta = job.run_metadata or {}
        req = job.original_request or {}
        eff = meta.get("effective_assumptions") or {}
        rate = (
            eff.get("interest_rate")
            or meta.get("effective_interest_rate")
            or req.get("interest_rate")
        )
        if rate is not None:
            return f"{float(rate) * 100:.2f}%"
        return "5.00%"

    def _extract_mortality(self, job: Any) -> str:
        meta = job.run_metadata or {}
        req = job.original_request or {}
        eff = meta.get("effective_assumptions") or {}
        table = eff.get("table_id") or req.get("table_id") or "soa_ilt"
        mult = eff.get("mortality_multiplier") or meta.get("effective_mortality_multiplier")
        if mult is not None and mult != 1.0:
            return f"{table} (x{float(mult):.2f})"
        return f"{table}"

    def _extract_lapse(self, job: Any) -> str:
        meta = job.run_metadata or {}
        req = job.original_request or {}
        eff = meta.get("effective_assumptions") or {}
        lapse_req = req.get("lapse") or {}
        if not isinstance(lapse_req, dict):
            lapse_req = {}
        rate = (
            eff.get("lapse_flat_rate")
            or meta.get("effective_lapse_rate")
            or lapse_req.get("flat_annual_rate")
        )
        if rate is not None:
            return f"{float(rate) * 100:.2f}%"
        return "3.00%"

    def _extract_expense(self, job: Any) -> str:
        meta = job.run_metadata or {}
        req = job.original_request or {}
        eff = meta.get("effective_assumptions") or {}
        mult = eff.get("expense_multiplier") or meta.get("effective_expense_multiplier")
        if mult is not None and mult != 1.0:
            return f"Loaded (x{float(mult):.2f})"
        exp_req = req.get("expense")
        if exp_req:
            return "Custom Loadings"
        return "Standard Loadings"

    def _extract_sim_count(self, job: Any) -> str:
        paths = job.total_paths or 1
        return f"{paths:,} paths" if paths > 1 else "1 (Deterministic)"

    def _extract_random_seed(self, job: Any) -> str:
        meta = job.run_metadata or {}
        req = job.original_request or {}
        seed = meta.get("seed") or req.get("seed")
        return str(seed) if seed is not None else "None"

    def _extract_engine_version(self, job: Any) -> str:
        meta = job.run_metadata or {}
        return meta.get("engine_version", "1.0.0")

    def _generate_explanation(
        self, metrics: list[MetricComparisonItem], changed_elements: list[str]
    ) -> str:
        """Generate high-level explanation summary."""
        # Check BEL change
        bel_item = next((m for m in metrics if m.metric_key == "bel"), None)
        bel_part = ""
        if bel_item and bel_item.percentage_delta is not None:
            pct = bel_item.percentage_delta
            if abs(pct) < 0.05:
                bel_part = "BEL remained virtually unchanged (< 0.1%)."
            elif pct > 0:
                bel_part = f"BEL increased by {pct:.1f}%."
            else:
                bel_part = f"BEL decreased by {abs(pct):.1f}%."
        else:
            bel_part = "Valuation metrics compared."

        if changed_elements:
            changes_part = f"Primary configuration changes: {', '.join(changed_elements)}."
        else:
            changes_part = "Primary configuration elements are identical."

        return f"{bel_part} {changes_part}"


run_comparison_service = RunComparisonService()
