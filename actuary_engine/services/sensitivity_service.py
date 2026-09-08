"""
First-Class Sensitivity Analysis & Valuation Driver Ranking Service.

Evaluates actuarial sensitivities across mortality, discount rate, lapse, and expenses
against base models by systematically applying assumption overrides via ScenarioService.
Ranks assumptions into Top Valuation Drivers by absolute impact (swing magnitude).
Persists reproducible run records in the job history database.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Optional

from sqlalchemy import update

from actuary_engine.api.job_manager import job_manager
from actuary_engine.infrastructure.scenario_repo import scenario_repo
from actuary_engine.services.scenario_service import scenario_service
from actuary_engine.api.schemas import (
    SensitivityAnalysisRequest,
    SensitivityAnalysisResponse,
    SensitivityDriverItem,
    SensitivityGridPoint,
    SensitivityShockConfig,
)


VARIABLE_LABELS = {
    "mortality": "Mortality",
    "discount_rate": "Discount Rate",
    "lapse": "Lapse / Surrender",
    "expense": "Expense Loadings",
}

DEFAULT_SHOCKS = {
    "mortality": [-0.20, -0.10, 0.0, 0.10, 0.20],
    "discount_rate": [-200.0, -100.0, 0.0, 100.0, 200.0],  # in basis points
    "lapse": [-0.20, -0.10, 0.0, 0.10, 0.20],
    "expense": [-0.20, -0.10, 0.0, 0.10, 0.20],
}


class SensitivityService:
    def __init__(self) -> None:
        self.repo = scenario_repo
        self.scenario_service = scenario_service

    def get_default_shocks(self) -> dict[str, Any]:
        """Return the standard default shock grid specifications."""
        return {
            "mortality": {
                "unit": "pct",
                "shocks": DEFAULT_SHOCKS["mortality"],
                "labels": ["-20%", "-10%", "Base", "+10%", "+20%"],
            },
            "discount_rate": {
                "unit": "bps",
                "shocks": DEFAULT_SHOCKS["discount_rate"],
                "labels": ["-200 bps", "-100 bps", "Base", "+100 bps", "+200 bps"],
            },
            "lapse": {
                "unit": "pct",
                "shocks": DEFAULT_SHOCKS["lapse"],
                "labels": ["-20%", "-10%", "Base", "+10%", "+20%"],
            },
            "expense": {
                "unit": "pct",
                "shocks": DEFAULT_SHOCKS["expense"],
                "labels": ["-20%", "-10%", "Base", "+10%", "+20%"],
            },
        }

    def _normalize_and_validate_shocks(
        self,
        base_model: dict[str, Any],
        config: Optional[SensitivityShockConfig],
    ) -> dict[str, list[tuple[float, str, dict[str, Any]]]]:
        """Normalize user input shocks and validate them against actuarial constraints.

        Returns a dictionary of:
            variable -> list of (raw_shock_value, formatted_label, override_dict)
        """
        base_ir = float(base_model.get("interest_rate", 0.05))

        def _to_fraction(s: float) -> float:
            return s / 100.0 if abs(s) >= 2.0 else s

        # 1. Mortality
        mort_raw = (
            config.mortality_shocks
            if config and config.mortality_shocks is not None
            else DEFAULT_SHOCKS["mortality"]
        )
        if not mort_raw:
            mort_raw = DEFAULT_SHOCKS["mortality"]

        mort_specs: list[tuple[float, str, dict[str, Any]]] = []
        for s in mort_raw:
            frac = _to_fraction(s)
            mult = 1.0 + frac
            if mult <= 0.0:
                raise ValueError(
                    f"Invalid mortality shock ({s}): resulting multiplier ({mult:.2f}) must be strictly positive."
                )
            pct_int = int(round(frac * 100))
            label = "Base" if pct_int == 0 else f"{'+' if pct_int > 0 else ''}{pct_int}%"
            mort_specs.append((s, label, {"mortality_multiplier": mult}))

        # 2. Discount Rate (in bps)
        ir_raw = (
            config.interest_shocks_bps
            if config and config.interest_shocks_bps is not None
            else DEFAULT_SHOCKS["discount_rate"]
        )
        if not ir_raw:
            ir_raw = DEFAULT_SHOCKS["discount_rate"]

        ir_specs: list[tuple[float, str, dict[str, Any]]] = []
        for s in ir_raw:
            # If user passed small decimal e.g. 0.01, treat as 100 bps
            bps = s * 10000.0 if (abs(s) <= 0.05 and s != 0.0) else s
            eff_rate = base_ir + (bps / 10000.0)
            if eff_rate <= 0.0:
                raise ValueError(
                    f"Invalid discount rate shock ({bps:+.0f} bps): resulting interest rate ({eff_rate * 100:.2f}%) must be strictly positive."
                )
            if eff_rate > 0.50:
                raise ValueError(
                    f"Invalid discount rate shock ({bps:+.0f} bps): resulting interest rate ({eff_rate * 100:.2f}%) exceeds maximum limit of 50%."
                )
            bps_int = int(round(bps))
            label = "Base" if bps_int == 0 else f"{'+' if bps_int > 0 else ''}{bps_int} bps"
            ir_specs.append((s, label, {"interest_rate_bps": bps}))

        # 3. Lapse
        lapse_raw = (
            config.lapse_shocks
            if config and config.lapse_shocks is not None
            else DEFAULT_SHOCKS["lapse"]
        )
        if not lapse_raw:
            lapse_raw = DEFAULT_SHOCKS["lapse"]

        lapse_specs: list[tuple[float, str, dict[str, Any]]] = []
        for s in lapse_raw:
            frac = _to_fraction(s)
            mult = 1.0 + frac
            if mult < 0.0:
                raise ValueError(
                    f"Invalid lapse shock ({s}): resulting multiplier ({mult:.2f}) cannot be negative."
                )
            pct_int = int(round(frac * 100))
            label = "Base" if pct_int == 0 else f"{'+' if pct_int > 0 else ''}{pct_int}%"
            lapse_specs.append((s, label, {"lapse_multiplier": mult}))

        # 4. Expense
        exp_raw = (
            config.expense_shocks
            if config and config.expense_shocks is not None
            else DEFAULT_SHOCKS["expense"]
        )
        if not exp_raw:
            exp_raw = DEFAULT_SHOCKS["expense"]

        exp_specs: list[tuple[float, str, dict[str, Any]]] = []
        for s in exp_raw:
            frac = _to_fraction(s)
            mult = 1.0 + frac
            if mult < 0.0:
                raise ValueError(
                    f"Invalid expense shock ({s}): resulting multiplier ({mult:.2f}) cannot be negative."
                )
            pct_int = int(round(frac * 100))
            label = "Base" if pct_int == 0 else f"{'+' if pct_int > 0 else ''}{pct_int}%"
            exp_specs.append((s, label, {"expense_multiplier": mult}))

        return {
            "mortality": mort_specs,
            "discount_rate": ir_specs,
            "lapse": lapse_specs,
            "expense": exp_specs,
        }

    def run_sensitivity_analysis(
        self, request: SensitivityAnalysisRequest
    ) -> SensitivityAnalysisResponse:
        """Execute a full sensitivity analysis sweep across all 4 variables.

        Reuses ScenarioService to compute deterministic BEL, CSM, and profit/loss.
        Guarantees base model remains unchanged and results are persisted in job history.
        """
        # 1. Fetch Base Model
        base_model = self.repo.get_base_model(request.base_model_id)
        if not base_model:
            raise ValueError(f"Base model '{request.base_model_id}' not found.")

        target_metric = request.target_metric
        if target_metric not in ("bel", "csm", "profit_loss"):
            raise ValueError(f"Invalid target_metric '{target_metric}'. Must be 'bel', 'csm', or 'profit_loss'.")

        # 2. Normalize and Validate Shocks
        shock_specs = self._normalize_and_validate_shocks(base_model, request.shocks)

        # 3. Base Case Evaluation
        base_res = self.scenario_service.evaluate_model_with_overrides(base_model, {})
        base_bel = round(float(base_res["bel"]), 2)
        base_csm = round(float(base_res["csm"]), 2)
        base_profit_loss = round(float(base_res["profit_loss"]), 2)

        if target_metric == "bel":
            base_metric_value = base_bel
        elif target_metric == "csm":
            base_metric_value = base_csm
        else:
            base_metric_value = base_profit_loss

        # 4. Execute Sensitivity Grid
        grid_points: list[SensitivityGridPoint] = []
        variable_metrics: dict[str, list[dict[str, Any]]] = {
            "mortality": [],
            "discount_rate": [],
            "lapse": [],
            "expense": [],
        }

        for var_key, specs in shock_specs.items():
            for raw_val, label, override_dict in specs:
                # If Base case shock
                if label == "Base":
                    bel = base_bel
                    csm = base_csm
                    pl = base_profit_loss
                else:
                    eval_res = self.scenario_service.evaluate_model_with_overrides(base_model, override_dict)
                    bel = round(float(eval_res["bel"]), 2)
                    csm = round(float(eval_res["csm"]), 2)
                    pl = round(float(eval_res["profit_loss"]), 2)

                if target_metric == "bel":
                    metric_val = bel
                elif target_metric == "csm":
                    metric_val = csm
                else:
                    metric_val = pl

                abs_change = round(metric_val - base_metric_value, 2)
                denom = max(1.0, abs(base_metric_value))
                pct_change = round((abs_change / denom) * 100.0, 2)

                point = SensitivityGridPoint(
                    variable=var_key,
                    variable_label=VARIABLE_LABELS[var_key],
                    shock_label=label,
                    shock_value=raw_val,
                    resulting_metric=metric_val,
                    absolute_change=abs_change,
                    percentage_change=pct_change,
                    bel=bel,
                    csm=csm,
                    profit_loss=pl,
                )
                grid_points.append(point)
                variable_metrics[var_key].append({
                    "shock_label": label,
                    "shock_value": raw_val,
                    "metric_value": metric_val,
                    "abs_change": abs_change,
                    "bel": bel,
                    "csm": csm,
                    "pl": pl,
                })

        # 5. Calculate "Top Valuation Drivers"
        drivers_raw: list[dict[str, Any]] = []
        for var_key, records in variable_metrics.items():
            metric_vals = [r["metric_value"] for r in records]
            min_m = min(metric_vals)
            max_m = max(metric_vals)
            swing = round(max_m - min_m, 2)
            denom = max(1.0, abs(base_metric_value))
            swing_pct = round((swing / denom) * 100.0, 2)
            max_abs_change = round(max(abs(r["abs_change"]) for r in records), 2)

            # Determine most adverse / favorable shock
            if target_metric == "bel":
                # For BEL, highest liability is most adverse; lowest liability is most favorable
                adverse_rec = max(records, key=lambda r: r["metric_value"])
                favorable_rec = min(records, key=lambda r: r["metric_value"])
            else:
                # For CSM and Profit, lowest margin/profit is most adverse; highest is most favorable
                adverse_rec = min(records, key=lambda r: r["metric_value"])
                favorable_rec = max(records, key=lambda r: r["metric_value"])

            drivers_raw.append({
                "variable": var_key,
                "variable_label": VARIABLE_LABELS[var_key],
                "swing": swing,
                "swing_pct": swing_pct,
                "max_abs_change": max_abs_change,
                "min_metric": round(min_m, 2),
                "max_metric": round(max_m, 2),
                "most_adverse_shock": adverse_rec["shock_label"],
                "most_favorable_shock": favorable_rec["shock_label"],
            })

        # Rank assumptions in descending order of absolute swing
        drivers_raw.sort(key=lambda d: d["swing"], reverse=True)
        drivers: list[SensitivityDriverItem] = [
            SensitivityDriverItem(
                rank=idx + 1,
                variable=d["variable"],
                variable_label=d["variable_label"],
                swing=d["swing"],
                swing_pct=d["swing_pct"],
                max_abs_change=d["max_abs_change"],
                min_metric=d["min_metric"],
                max_metric=d["max_metric"],
                most_adverse_shock=d["most_adverse_shock"],
                most_favorable_shock=d["most_favorable_shock"],
            )
            for idx, d in enumerate(drivers_raw)
        ]

        # 6. Reproducibility & Result Persistence
        analysis_id = f"sens-{uuid.uuid4().hex[:8]}"
        exec_time = time.time()
        run_meta_dict = {
            "engine_version": "1.0.0",
            "execution_time": exec_time,
            "valuation_type": "Sensitivity",
            "analysis_id": analysis_id,
            "base_model_id": base_model["id"],
            "base_model_name": base_model["name"],
            "target_metric": target_metric,
            "base_metric_value": base_metric_value,
            "base_bel": base_bel,
            "base_csm": base_csm,
            "base_profit_loss": base_profit_loss,
            "top_driver": drivers[0].variable_label if drivers else None,
            "top_driver_swing": drivers[0].swing if drivers else None,
            "shocks_evaluated": {
                k: [pt.shock_label for pt in grid_points if pt.variable == k]
                for k in ["mortality", "discount_rate", "lapse", "expense"]
            },
        }

        job = job_manager.create_job(
            total_paths=len(grid_points),
            run_metadata=run_meta_dict,
            original_request={
                "base_model_id": base_model["id"],
                "target_metric": target_metric,
                "analysis_id": analysis_id,
            },
        )

        response = SensitivityAnalysisResponse(
            analysis_id=analysis_id,
            base_model_id=base_model["id"],
            base_model_name=base_model["name"],
            target_metric=target_metric,
            base_metric_value=base_metric_value,
            base_bel=base_bel,
            base_csm=base_csm,
            base_profit_loss=base_profit_loss,
            drivers=drivers,
            grid_points=grid_points,
            job_id=job.job_id,
            created_at=exec_time,
            reproducibility=run_meta_dict,
        )

        # Update persistent job record
        stmt = (
            update(job_manager.jobs_table)
            .where(job_manager.jobs_table.c.job_id == job.job_id)
            .values(
                status="COMPLETED",
                progress=100.0,
                completed_paths=len(grid_points),
                result=json.dumps(response.model_dump()),
                updated_at=exec_time,
            )
        )
        with job_manager.engine.begin() as conn:
            conn.execute(stmt)

        return response


sensitivity_service = SensitivityService()
