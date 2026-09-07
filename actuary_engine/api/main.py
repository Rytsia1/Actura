"""
FastAPI application layer for the Actuarial Valuation & Risk Engine.

Provides REST and WebSocket endpoints for:
- Health check & mortality table metadata (/api/v1/health, /api/v1/tables)
- Dynamic mortality table file upload & registry (/api/v1/tables/upload)
- Deterministic life insurance valuation (/api/v1/valuation/deterministic)
- Stochastic Monte Carlo valuation with Vasicek ESG (/api/v1/valuation/stochastic)
- Asynchronous large-scale simulation dispatch (/api/v1/valuation/stochastic/async)
- Polling status endpoint (/api/v1/valuation/stochastic/status/{job_id})
- Bidirectional WebSocket progress streaming (/ws/simulations/{job_id})
- Seriatim batch portfolio valuations (/api/v1/valuation/portfolio/csv)
"""

from __future__ import annotations

import asyncio
import io
import logging
from collections.abc import Callable, Coroutine
from typing import Any, Optional, Union

import numpy as np
import pandas as pd
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from concurrent.futures import ProcessPoolExecutor
import multiprocessing
import queue

from actuary_engine.api.worker import _cpu_worker_task
from actuary_engine.api.job_manager import JobStatus, job_manager
from actuary_engine.api.schemas import (
    AsyncJobCreateResponse,
    AsyncJobStatusResponse,
    DeterministicValuationRequest,
    DeterministicValuationResponse,
    ESGModelType,
    ESGSimulationRequest,
    ESGSimulationResponse,
    IFRS17ValuationRequest,
    IFRS17ValuationResponse,
    LeeCarterForecastRequest,
    LeeCarterForecastResponse,
    PortfolioValuationJSONRequest,
    PortfolioValuationResponse,
    QuantileTrajectory,
    SensitivityRequest,
    SensitivityResponse,
    StochasticValuationRequest,
    StochasticValuationResponse,
    StressTestRequest,
    StressTestResponse,
    ContractGraphPayload,
    SimulateGraphResponse,
    TableListItem,
    TableUploadResponse,
    TerminalDistribution,
    ValidationResult,
    ValidationIssue,
    ValidationSeverity,
)
from actuary_engine.curves.yield_curve import MarketYieldCurve
from actuary_engine.models.assumptions import ExpenseAssumption, InterestAssumption, LapseAssumption
from actuary_engine.models.contracts import PolicyContract, ProductType
from actuary_engine.pricing.premium import LevelPremiumCalculator
from actuary_engine.stochastic.dynamic_lapse import DynamicLapseModel
from actuary_engine.stochastic.esg import VasicekESG, VasicekParams
from actuary_engine.stochastic.esg_advanced import CIRModel, CIRParams, HullWhite1FModel
from actuary_engine.stochastic.lee_carter import LeeCarterModel
from actuary_engine.stochastic.monte_carlo import (
    StochasticValuationEngine,
    compute_quantile_trajectory,
    compute_terminal_distribution,
    sample_representative_paths,
)
from actuary_engine.tables.commutation import CommutationFunctions
from actuary_engine.tables.mortality_table import MortalityTable
from actuary_engine.tables.parsers import TableParsingError, parse_mortality_file
from actuary_engine.tables.registry import TableMetadata, table_registry
from actuary_engine.valuation.graph_parser import ContractGraphSimulator
from actuary_engine.valuation.gpv import GrossPremiumValuation
from actuary_engine.valuation.ifrs17 import IFRS17Engine
from actuary_engine.valuation.portfolio import PortfolioSummary, PortfolioValuationEngine
from actuary_engine.valuation.reserves import ReserveCalculator
from actuary_engine.valuation.sensitivity import SensitivityEngine
from actuary_engine.valuation.blueprint_validator import BlueprintValidator

logger = logging.getLogger("actuary_engine.api")

process_pool_executor = ProcessPoolExecutor(max_workers=2)

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    process_pool_executor.shutdown(wait=True)

# Initialize FastAPI App
app = FastAPI(
    title="Actuarial Valuation & Risk Engine API",
    version="0.3.0",
    description="Production-grade API for life insurance liabilities, dynamic mortality tables, reserves, and Monte Carlo risk analytics with WebSockets.",
    lifespan=lifespan,
)

# Configure CORS for Vue 3 frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "*",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/v1/health")
def health_check() -> dict[str, Any]:
    """Health check endpoint."""
    soa_table = table_registry.get_table("soa_ilt")
    return {
        "status": "healthy",
        "service": "actuary-engine-api",
        "table": soa_table.name,
        "omega": str(soa_table.omega),
        "registered_tables_count": len(table_registry.list_tables()),
    }


# ────────────────────────────────────────────────────────────
# Mortality Table Registry & Upload Endpoints
# ────────────────────────────────────────────────────────────

@app.get("/api/v1/tables", response_model=list[TableListItem])
def list_mortality_tables() -> list[TableListItem]:
    """List all registered mortality tables (both default and custom uploaded)."""
    return [
        TableListItem(
            table_id=m.table_id,
            name=m.name,
            description=m.description,
            min_age=m.min_age,
            max_age=m.max_age,
            omega=m.omega,
            radix=m.radix,
            is_builtin=m.is_builtin,
            sample_qx=m.sample_qx,
        )
        for m in table_registry.list_tables()
    ]


@app.get("/api/v1/tables/soa_ilt")
def get_soa_ilt_info() -> dict[str, object]:
    """Retrieve metadata and sample mortality rates for SOA Illustrative Life Table."""
    table = table_registry.get_table("soa_ilt")
    sample_ages = [20, 30, 40, 50, 60, 70, 80, 90, 100]
    sample_qx = {f"q{age}": round(table.get_tqx(age, 1), 6) for age in sample_ages}
    return {
        "name": table.name,
        "min_age": table.min_age,
        "max_age": table.max_age,
        "omega": table.omega,
        "radix": table.radix,
        "sample_qx": sample_qx,
    }


@app.get("/api/v1/tables/{table_id}")
def get_table_info(table_id: str) -> dict[str, object]:
    """Retrieve metadata for a specific mortality table by ID."""
    try:
        table = table_registry.get_table(table_id)
        meta = table_registry.get_metadata(table_id)
        return meta.model_dump()
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.post("/api/v1/tables/upload", response_model=TableUploadResponse)
async def upload_mortality_table(
    file: UploadFile = File(..., description="Mortality table file (CSV, TSV, or SOA XTbML format)."),
    table_name: Optional[str] = Form(None, description="Custom display name for the table."),
    table_description: Optional[str] = Form("", description="Optional notes or source citation."),
) -> TableUploadResponse:
    """Upload, parse, validate, and register a custom mortality table in the registry."""
    try:
        contents = await file.read()
        filename = file.filename or "custom_table.csv"
        parsed_table = parse_mortality_file(
            filename=filename,
            content=contents,
            name=table_name,
        )

        clean_id = (table_name or filename).lower().strip().replace(" ", "_").replace(".", "_")
        clean_id = "".join(c for c in clean_id if c.isalnum() or c == "_")
        if not clean_id:
            clean_id = f"custom_table_{len(table_registry.list_tables())}"

        meta = table_registry.register_table(
            table_id=clean_id,
            table=parsed_table,
            description=table_description or f"Custom uploaded table from {filename}",
            is_builtin=False,
        )

        return TableUploadResponse(
            status="success",
            table_id=meta.table_id,
            table_name=meta.name,
            min_age=meta.min_age,
            max_age=meta.max_age,
            rows_count=parsed_table.num_ages,
            is_builtin=meta.is_builtin,
            sample_qx=meta.sample_qx,
        )
    except TableParsingError as e:
        raise HTTPException(status_code=400, detail=f"Table validation error: {e}") from e
    except Exception as e:
        logger.exception("Mortality table upload failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Upload processing failed: {e}") from e


@app.delete("/api/v1/tables/{table_id}")
def delete_mortality_table(table_id: str) -> dict[str, str]:
    """Delete a custom registered mortality table."""
    try:
        deleted = table_registry.delete_table(table_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Table '{table_id}' not found.")
        return {"status": "success", "message": f"Table '{table_id}' deleted successfully."}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ────────────────────────────────────────────────────────────
# Valuation Endpoints
# ────────────────────────────────────────────────────────────

@app.post("/api/v1/valuation/deterministic", response_model=DeterministicValuationResponse)
def evaluate_deterministic(request: DeterministicValuationRequest) -> DeterministicValuationResponse:
    """Run deterministic valuation computing net level premiums, prospective/retrospective reserves, and GPV rollout."""
    try:
        table = table_registry.get_table(request.table_id or "soa_ilt")
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    try:
        eff_term = None if request.product_type == ProductType.WHOLE_LIFE else request.term
        contract = PolicyContract(
            product_type=request.product_type,
            issue_age=request.issue_age,
            term=eff_term,
            sum_assured=request.sum_assured,
            premium_paying_term=request.premium_paying_term,
        )
        contract.validate_against_table(table)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    try:
        interest = InterestAssumption(annual_rate=request.interest_rate)
        comm = CommutationFunctions(table, interest)
        prem_calc = LevelPremiumCalculator(comm)

        # 1. Net Level Premium Pricing & Equivalence
        prem_res = prem_calc.price_contract(contract)
        net_premium = prem_res.annual_premium
        nsp = prem_res.nsp
        annuity_factor = prem_res.annuity_factor

        # 2. Derive gross premium if not explicitly supplied (default 20% loading)
        gross_premium = request.gross_premium if request.gross_premium is not None else net_premium * 1.20

        # 3. Reserve Calculation (Prospective & Retrospective)
        res_calc = ReserveCalculator(comm)
        net_res_df = res_calc.reserve_profile(contract, annual_premium=net_premium, method="both")

        # 4. Gross Premium Valuation (GPV)
        expense = request.expense or ExpenseAssumption(
            percent_of_premium_first=0.35,
            percent_of_premium_renewal=0.05,
            per_policy_first=200.0,
            per_policy_renewal=20.0,
        )
        lapse = request.lapse or LapseAssumption(flat_annual_rate=0.03)

        gpv_engine = GrossPremiumValuation(
            table=table,
            interest=interest,
            expense=expense,
            lapse=lapse,
        )

        gpv_cf_df = gpv_engine.project(contract, gross_premium=gross_premium)
        bel = gpv_engine.best_estimate_liability(contract, gross_premium=gross_premium)
        gpv_res_df = gpv_engine.gross_reserve_profile(contract, gross_premium=gross_premium)

        # Merge reserve trajectories into JSON-friendly format
        merged_res = net_res_df.merge(gpv_res_df[["duration", "gross_reserve"]], on="duration", how="left")
        reserve_profile_data = []
        for _, row in merged_res.iterrows():
            reserve_profile_data.append({
                "duration": int(row["duration"]),
                "age": int(row["age"]),
                "reserve_prospective": round(float(row["reserve_prospective"]), 2),
                "reserve_retrospective": round(float(row["reserve_retrospective"]), 2),
                "gross_reserve": round(float(row.get("gross_reserve", 0.0)), 2),
            })

        # Prepare cash flow breakdown
        cash_flows = []
        for _, row in gpv_cf_df.iterrows():
            cash_flows.append({
                "year": int(row["year"]),
                "age": int(row["age"]),
                "inforce_boy": round(float(row["inforce_boy"]), 6),
                "premium_income": round(float(row["premium_income"]), 2),
                "death_claims": round(float(row["death_claims"]), 2),
                "maturity_benefit": round(float(row["maturity_benefit"]), 2),
                "total_expense": round(float(row["total_expense"]), 2),
                "net_liability_cf": round(float(row["net_liability_cf"]), 2),
                "pv_net_liability": round(float(row["pv_net_liability"]), 2),
            })

        return DeterministicValuationResponse(
            product_type=contract.product_type.value,
            issue_age=contract.issue_age,
            term=contract.term,
            sum_assured=contract.sum_assured,
            annual_net_premium=round(net_premium, 2),
            annual_gross_premium=round(gross_premium, 2),
            nsp=round(nsp, 2),
            annuity_factor=round(annuity_factor, 4),
            bel=round(bel, 2),
            table_id=request.table_id or "soa_ilt",
            table_name=table.name,
            reserve_profile=reserve_profile_data,
            cash_flows=cash_flows,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


async def _compute_stochastic_valuation_core(
    request: StochasticValuationRequest,
    progress_callback: Optional[Callable[[int, int, dict[str, Any]], Coroutine[Any, Any, None]]] = None,
) -> StochasticValuationResponse:
    """Internal helper to compute stochastic Monte Carlo valuation with chunking and fan chart analytics."""
    table = table_registry.get_table(request.table_id or "soa_ilt")

    contract = PolicyContract(
        product_type=request.product_type,
        issue_age=request.issue_age,
        term=request.term,
        sum_assured=request.sum_assured,
        premium_paying_term=request.premium_paying_term,
    )

    if request.gross_premium is not None:
        gross_premium = request.gross_premium
    else:
        comm = CommutationFunctions(table, InterestAssumption(annual_rate=request.vasicek.r0))
        calc = LevelPremiumCalculator(comm)
        prem_res = calc.price_contract(contract)
        gross_premium = prem_res.annual_premium * 1.25

    esg = VasicekESG(params=request.vasicek, seed=request.seed)
    dyn_lapse = DynamicLapseModel(params=request.dynamic_lapse) if request.dynamic_lapse is not None else None

    expense = request.expense or ExpenseAssumption(
        percent_of_premium_first=0.35,
        percent_of_premium_renewal=0.05,
        per_policy_first=200.0,
        per_policy_renewal=20.0,
    )

    engine = StochasticValuationEngine(
        table=table,
        esg=esg,
        expense=expense,
        dynamic_lapse=dyn_lapse,
    )

    chunk_size = min(1000, max(250, request.n_scenarios // 10))
    stoch_res, bel_dist = await engine.evaluate_liability_distribution_async(
        contract=contract,
        gross_premium=gross_premium,
        n_scenarios=request.n_scenarios,
        chunk_size=chunk_size,
        seed=request.seed,
        progress_callback=progress_callback,
    )

    # Fan chart analytics for short rates
    n_years = contract.term if contract.term is not None else (table.omega - contract.issue_age)
    rates_paths = esg.simulate_paths(
        n_scenarios=min(2500, request.n_scenarios),
        n_years=n_years,
        dt=1.0,
        method="exact",
        seed=request.seed,
    )

    # 1. Server-side quantile extraction across projection timesteps
    quantiles_dict = compute_quantile_trajectory(rates_paths)
    quantiles_obj = QuantileTrajectory(**quantiles_dict)

    # 2. Server-side terminal distribution and histogram binning (40 bins)
    term_dist_dict = compute_terminal_distribution(stoch_res.scenario_bel, bins=40)
    term_dist_obj = TerminalDistribution(**term_dist_dict)

    # 3. Compressed representative sample traces (max 15 paths)
    sample_paths = sample_representative_paths(rates_paths, max_paths=15)

    timesteps: list[Union[int, str]] = list(range(rates_paths.shape[1]))

    # Summary KPI dictionary
    summary_kpis = {
        "mean_bel": round(stoch_res.mean_bel, 2),
        "std_bel": round(stoch_res.std_bel, 2),
        "min_bel": round(stoch_res.min_bel, 2),
        "max_bel": round(stoch_res.max_bel, 2),
        "var_95": round(stoch_res.var_95, 2),
        "var_99": round(stoch_res.var_99, 2),
        "cvar_95": round(stoch_res.cvar_95, 2),
        "cvar_99": round(stoch_res.cvar_99, 2),
        "skewness": term_dist_dict["skewness"],
    }

    # Backward-compatible fan_chart_rates and liability_histogram format
    fan_chart_rates: list[dict[str, object]] = []
    for t in range(rates_paths.shape[1]):
        col = rates_paths[:, t]
        fan_chart_rates.append({
            "year": t,
            "p5": round(float(np.percentile(col, 5)), 5),
            "p25": round(float(np.percentile(col, 25)), 5),
            "p50": round(float(np.percentile(col, 50)), 5),
            "p75": round(float(np.percentile(col, 75)), 5),
            "p95": round(float(np.percentile(col, 95)), 5),
            "mean": round(float(np.mean(col)), 5),
        })

    histogram_data: list[dict[str, object]] = []
    bin_edges = term_dist_dict["bin_edges"]
    counts = term_dist_dict["counts"]
    for i in range(len(counts)):
        histogram_data.append({
            "bin_start": bin_edges[i],
            "bin_end": bin_edges[i + 1],
            "bin_mid": round(float((bin_edges[i] + bin_edges[i + 1]) / 2.0), 2),
            "count": counts[i],
        })

    return StochasticValuationResponse(
        timesteps=timesteps,
        quantiles=quantiles_obj,
        terminal_distribution=term_dist_obj,
        sample_paths=sample_paths,
        summary_kpis=summary_kpis,
        mean_bel=round(stoch_res.mean_bel, 2),
        std_bel=round(stoch_res.std_bel, 2),
        min_bel=round(stoch_res.min_bel, 2),
        max_bel=round(stoch_res.max_bel, 2),
        var_95=round(stoch_res.var_95, 2),
        var_99=round(stoch_res.var_99, 2),
        cvar_95=round(stoch_res.cvar_95, 2),
        cvar_99=round(stoch_res.cvar_99, 2),
        percentiles={k: round(v, 2) for k, v in stoch_res.percentiles.items()},
        fan_chart_rates=fan_chart_rates,
        liability_histogram=histogram_data,
    )


@app.post("/api/v1/valuation/stochastic", response_model=StochasticValuationResponse)
async def evaluate_stochastic(request: StochasticValuationRequest) -> StochasticValuationResponse:
    """Synchronous endpoint for Level 4 Monte Carlo liability valuation and tail risk analytics."""
    try:
        return await _compute_stochastic_valuation_core(request)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Stochastic valuation failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Valuation error: {e}") from e


# ────────────────────────────────────────────────────────────
# Asynchronous Simulation Pipeline & WebSocket Streaming
# ────────────────────────────────────────────────────────────

async def _run_async_simulation_task(job_id: str, request: StochasticValuationRequest) -> None:
    """Background task orchestrating chunked simulation execution and state updates."""
    job_manager.set_processing(job_id)

    try:
        table = table_registry.get_table(request.table_id or "soa_ilt")
        table_dict = {
            "ages": table.ages.tolist(),
            "qx": table.qx.tolist(),
            "name": table.name,
            "radix": table.radix
        }
        request_dict = request.model_dump()
        
        m = multiprocessing.Manager()
        progress_queue = m.Queue()

        async def _poll_progress():
            while True:
                try:
                    msg = progress_queue.get_nowait()
                    await job_manager.update_progress(
                        job_id=job_id,
                        completed_paths=msg["completed"],
                        total_paths=msg["total"],
                        partial_metrics=msg["partial_metrics"]
                    )
                except queue.Empty:
                    await asyncio.sleep(0.1)

        poll_task = asyncio.create_task(_poll_progress())

        loop = asyncio.get_running_loop()
        final_res_dict = await loop.run_in_executor(
            process_pool_executor,
            _cpu_worker_task,
            request_dict,
            table_dict,
            progress_queue
        )

        poll_task.cancel()
        await job_manager.set_completed(job_id, final_res_dict)
    except Exception as e:
        logger.exception("Async simulation job %s failed: %s", job_id, e)
        try:
            poll_task.cancel()
        except Exception:
            pass
        await job_manager.set_failed(job_id, str(e))


@app.post("/api/v1/valuation/stochastic/async", response_model=AsyncJobCreateResponse, status_code=202)
async def start_async_simulation(
    request: StochasticValuationRequest,
    background_tasks: BackgroundTasks,
) -> AsyncJobCreateResponse:
    """Enqueue a large-scale stochastic Monte Carlo simulation in the background."""
    try:
        table = table_registry.get_table(request.table_id or "soa_ilt")
        contract = PolicyContract(
            product_type=request.product_type,
            issue_age=request.issue_age,
            term=request.term,
            sum_assured=request.sum_assured,
            premium_paying_term=request.premium_paying_term,
        )
        contract.validate_against_table(table)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    job = job_manager.create_job(total_paths=request.n_scenarios)
    background_tasks.add_task(_run_async_simulation_task, job.job_id, request)

    return AsyncJobCreateResponse(
        job_id=job.job_id,
        status="QUEUED",
        total_paths=job.total_paths,
        ws_endpoint=f"/ws/simulations/{job.job_id}",
    )


@app.get("/api/v1/valuation/stochastic/status/{job_id}", response_model=AsyncJobStatusResponse)
def get_simulation_status(job_id: str) -> AsyncJobStatusResponse:
    """Poll the status and progress of an asynchronous simulation task."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Simulation job '{job_id}' not found.")

    res_obj = None
    if job.result:
        res_obj = StochasticValuationResponse(**job.result)

    return AsyncJobStatusResponse(
        job_id=job.job_id,
        status=job.status.value,
        progress=round(job.progress, 1),
        completed_paths=job.completed_paths,
        total_paths=job.total_paths,
        partial_metrics=job.partial_metrics,
        result=res_obj,
        error=job.error,
    )


@app.websocket("/ws/simulations/{job_id}")
async def websocket_simulation_progress(websocket: WebSocket, job_id: str) -> None:
    """Bidirectional WebSocket connection broadcasting incremental progress and final simulation results."""
    await websocket.accept()

    job = job_manager.get_job(job_id)
    if not job:
        await websocket.send_json({
            "type": "ERROR",
            "job_id": job_id,
            "status": "FAILED",
            "error": f"Job '{job_id}' not found.",
        })
        await websocket.close()
        return

    # If already completed or failed prior to connection
    if job.status == JobStatus.COMPLETED:
        await websocket.send_json({
            "type": "COMPLETE",
            "job_id": job_id,
            "status": "COMPLETED",
            "percent": 100.0,
            "completed_paths": job.total_paths,
            "total_paths": job.total_paths,
            "data": job.result,
        })
        await websocket.close()
        return
    elif job.status == JobStatus.FAILED:
        await websocket.send_json({
            "type": "ERROR",
            "job_id": job_id,
            "status": "FAILED",
            "error": job.error or "Simulation failed.",
        })
        await websocket.close()
        return

    queue = job_manager.subscribe(job_id)
    try:
        while True:
            event = await asyncio.wait_for(queue.get(), timeout=120.0)
            await websocket.send_json(event)
            if event.get("type") in ("COMPLETE", "ERROR"):
                break
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except asyncio.TimeoutError:
        try:
            await websocket.send_json({
                "type": "ERROR",
                "job_id": job_id,
                "error": "Simulation WebSocket timed out after 120s of inactivity.",
            })
        except Exception:
            pass
    finally:
        job_manager.unsubscribe(job_id, queue)
        try:
            await websocket.close()
        except Exception:
            pass


# ────────────────────────────────────────────────────────────
# Portfolio Batch Valuation Endpoints
# ────────────────────────────────────────────────────────────

@app.post("/api/v1/valuation/portfolio/csv", response_model=PortfolioValuationResponse)
async def evaluate_portfolio_csv(
    file: UploadFile = File(..., description="CSV file containing seriatim policyholder records."),
    interest_rate: float = Form(0.05, description="Annual effective discount rate."),
    table_id: str = Form("soa_ilt", description="Mortality table ID."),
    expense_percent_first: float = Form(0.35, description="First-year acquisition expense % of premium."),
    expense_percent_renewal: float = Form(0.05, description="Renewal maintenance expense % of premium."),
    expense_per_policy_first: float = Form(200.0, description="First-year per-policy expense ($)."),
    expense_per_policy_renewal: float = Form(20.0, description="Renewal per-policy expense ($)."),
    flat_lapse_rate: float = Form(0.03, description="Flat annual policyholder lapse rate."),
) -> PortfolioValuationResponse:
    """Evaluate an entire portfolio of life insurance policies via multipart CSV file upload."""
    try:
        table = table_registry.get_table(table_id or "soa_ilt")
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    try:
        contents = await file.read()
        engine = PortfolioValuationEngine(
            table=table,
            interest=InterestAssumption(annual_rate=interest_rate),
            expense=ExpenseAssumption(
                percent_of_premium_first=expense_percent_first,
                percent_of_premium_renewal=expense_percent_renewal,
                per_policy_first=expense_per_policy_first,
                per_policy_renewal=expense_per_policy_renewal,
            ),
            lapse=LapseAssumption(flat_annual_rate=flat_lapse_rate),
        )

        df = engine.load_portfolio_df(contents)
        res_df, summary = engine.evaluate_portfolio(df)

        sample_records: list[dict[str, Any]] = [
            {str(k): v for k, v in r.items()}
            for r in res_df.head(25)[
                ["policy_id", "product_type", "issue_age", "policy_duration_years", "term_years", "sum_assured", "gross_premium", "pvfb", "pvfp", "pvfe", "bel"]
            ].to_dict(orient="records")
        ]

        return PortfolioValuationResponse(
            total_policies=summary.total_policies,
            total_sum_assured=summary.total_sum_assured,
            total_pvfb=summary.total_pvfb,
            total_pvfp=summary.total_pvfp,
            total_pvfe=summary.total_pvfe,
            total_bel=summary.total_bel,
            annual_cash_flows=summary.annual_cash_flows,
            product_breakdown=summary.product_breakdown,
            age_breakdown=summary.age_breakdown,
            duration_breakdown=summary.duration_breakdown,
            sample_seriatim=sample_records,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Portfolio CSV valuation failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Portfolio processing error: {e}") from e


@app.post("/api/v1/valuation/portfolio", response_model=PortfolioValuationResponse)
def evaluate_portfolio_json(request: PortfolioValuationJSONRequest) -> PortfolioValuationResponse:
    """Evaluate a portfolio of life insurance policies provided as JSON records."""
    try:
        table = table_registry.get_table(request.table_id or "soa_ilt")
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    try:
        engine = PortfolioValuationEngine(
            table=table,
            interest=InterestAssumption(annual_rate=request.interest_rate),
            expense=request.expense or ExpenseAssumption(
                percent_of_premium_first=0.35,
                percent_of_premium_renewal=0.05,
                per_policy_first=200.0,
                per_policy_renewal=20.0,
            ),
            lapse=request.lapse or LapseAssumption(flat_annual_rate=0.03),
        )

        raw_records = [p.model_dump() for p in request.policies]
        raw_df = pd.DataFrame(raw_records)
        df = engine.load_portfolio_df(raw_df)
        res_df, summary = engine.evaluate_portfolio(df)

        sample_records: list[dict[str, Any]] = [
            {str(k): v for k, v in r.items()}
            for r in res_df.head(25)[
                ["policy_id", "product_type", "issue_age", "policy_duration_years", "term_years", "sum_assured", "gross_premium", "pvfb", "pvfp", "pvfe", "bel"]
            ].to_dict(orient="records")
        ]

        return PortfolioValuationResponse(
            total_policies=summary.total_policies,
            total_sum_assured=summary.total_sum_assured,
            total_pvfb=summary.total_pvfb,
            total_pvfp=summary.total_pvfp,
            total_pvfe=summary.total_pvfe,
            total_bel=summary.total_bel,
            annual_cash_flows=summary.annual_cash_flows,
            product_breakdown=summary.product_breakdown,
            age_breakdown=summary.age_breakdown,
            duration_breakdown=summary.duration_breakdown,
            sample_seriatim=sample_records,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Portfolio JSON valuation failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Portfolio processing error: {e}") from e


@app.get("/api/v1/valuation/portfolio/sample_csv")
def download_sample_portfolio_csv(n_policies: int = 1000) -> Response:
    """Generate and return a downloadable synthetic CSV portfolio for testing."""
    df = PortfolioValuationEngine.generate_synthetic_portfolio(n_policies=min(n_policies, 50000), seed=42)
    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False)
    csv_bytes = csv_buffer.getvalue().encode("utf-8")

    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=sample_portfolio_{n_policies}.csv"},
    )


# ────────────────────────────────────────────────────────────
# Lee-Carter Stochastic Mortality Forecast Endpoint
# ────────────────────────────────────────────────────────────

@app.post("/api/v1/mortality/lee-carter/forecast", response_model=LeeCarterForecastResponse)
def forecast_lee_carter_mortality(request: LeeCarterForecastRequest) -> LeeCarterForecastResponse:
    """Fit Lee-Carter stochastic mortality model and project future longevity improvement rates."""
    table_id = request.table_id or "soa_ilt"
    try:
        table = table_registry.get_table(table_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=f"Mortality table '{table_id}' not found.") from e

    try:
        ages = np.arange(table.min_age, table.omega, dtype=np.int64)
        historical_years = np.arange(request.base_year - 30, request.base_year, dtype=np.int64)

        # Generate mortality surface calibrated to table
        m_matrix = LeeCarterModel.generate_synthetic_historical_matrix(
            ages=ages,
            years=historical_years,
            base_table=table,
            annual_improvement=request.annual_improvement,
            seed=request.seed or 42,
        )

        model = LeeCarterModel()
        fit_result = model.fit(m_matrix, ages, historical_years)
        summary = model.forecast_summary(
            n_ahead=request.n_ahead,
            n_scenarios=request.n_scenarios,
            seed=request.seed or 42,
        )

        return LeeCarterForecastResponse(
            table_id=table_id,
            table_name=table.name,
            fit=fit_result.model_dump(),
            forecast=summary.model_dump(),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Lee-Carter forecasting failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Lee-Carter modeling error: {e}") from e


# ────────────────────────────────────────────────────────────
# IFRS 17 / PSAK 117 Valuation Endpoint
# ────────────────────────────────────────────────────────────

@app.post("/api/v1/valuation/ifrs17", response_model=IFRS17ValuationResponse)
def evaluate_ifrs17(request: IFRS17ValuationRequest) -> IFRS17ValuationResponse:
    """Evaluate IFRS 17 / PSAK 117 General Measurement Model (BBA) valuation."""
    table_id = request.table_id or "soa_ilt"
    try:
        table = table_registry.get_table(table_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=f"Mortality table '{table_id}' not found.") from e

    try:
        contract = PolicyContract(
            product_type=request.product_type,
            issue_age=request.issue_age,
            term=request.term,
            sum_assured=request.sum_assured,
            premium_paying_term=request.premium_paying_term,
        )
        contract.validate_against_table(table)
        interest = InterestAssumption(annual_rate=request.interest_rate)
        expense = request.expense or ExpenseAssumption()
        lapse = request.lapse or LapseAssumption()

        engine = IFRS17Engine(
            table=table,
            interest=interest,
            expense=expense,
            lapse=lapse,
            ra_ratio=request.ra_ratio,
        )

        val_result = engine.evaluate(
            contract=contract,
            gross_premium=request.gross_premium,
        )

        return IFRS17ValuationResponse(
            table_id=table_id,
            table_name=table.name,
            product_type=request.product_type,
            initial_balance=val_result.initial_balance.model_dump(),
            balance_sheet_schedule=val_result.balance_sheet_schedule,
            income_statement_schedule=val_result.income_statement_schedule,
            total_insurance_revenue=val_result.total_insurance_revenue,
            total_csm_released=val_result.total_csm_released,
            total_service_expenses=val_result.total_service_expenses,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("IFRS 17 valuation failed: %s", e)
        raise HTTPException(status_code=500, detail=f"IFRS 17 valuation error: {e}") from e


# ────────────────────────────────────────────────────────────
# Advanced ESG Simulation Endpoint (Hull-White 1F & CIR)
# ────────────────────────────────────────────────────────────

@app.post("/api/v1/esg/simulate", response_model=ESGSimulationResponse)
def simulate_esg_paths(request: ESGSimulationRequest) -> ESGSimulationResponse:
    """Generate multi-factor stochastic short-rate paths and compare with market discount curves."""
    try:
        # 1. Resolve / Construct Market Yield Curve
        if request.custom_yield_points and len(request.custom_yield_points) > 0:
            tenors = np.array([p["tenor"] for p in request.custom_yield_points], dtype=np.float64)
            rates = np.array([p["rate"] for p in request.custom_yield_points], dtype=np.float64)
            curve = MarketYieldCurve(tenors, rates, method="spline")
        elif request.benchmark_curve == "SOVEREIGN_SUN":
            curve = MarketYieldCurve.from_sovereign_sun()
        elif request.benchmark_curve == "FLAT":
            curve = MarketYieldCurve.from_flat_rate(request.r0 or 0.05)
        else:
            curve = MarketYieldCurve.from_us_treasury()

        n_steps = round(request.n_years / request.dt)
        time_grid = np.linspace(0.0, request.n_years, n_steps + 1).round(3).tolist()

        feller_ok = None
        feller_rat = None

        # 2. Simulate according to model choice
        if request.model_type == ESGModelType.HULL_WHITE_1F:
            hw_model = HullWhite1FModel(
                yield_curve=curve,
                a=request.a or 0.10,
                sigma=request.sigma or 0.015,
            )
            rate_paths = hw_model.simulate_paths(
                n_years=request.n_years,
                n_scenarios=request.n_scenarios,
                dt=request.dt,
                seed=request.seed,
            )
            df_paths = hw_model.discount_factor_paths(rate_paths, dt=request.dt)

        elif request.model_type == ESGModelType.CIR:
            cir_params = CIRParams(
                r0=request.r0 or float(curve.spot_rate(0.0)),
                kappa=request.kappa or 0.20,
                theta=request.theta or 0.05,
                sigma=request.sigma or 0.03,
            )
            feller_ok = cir_params.is_feller_satisfied
            feller_rat = round(cir_params.feller_ratio, 2)

            cir_model = CIRModel(
                r0=cir_params.r0,
                kappa=cir_params.kappa,
                theta=cir_params.theta,
                sigma=cir_params.sigma,
            )
            rate_paths = cir_model.simulate_paths(
                n_years=request.n_years,
                n_scenarios=request.n_scenarios,
                dt=request.dt,
                seed=request.seed,
            )
            df_paths = cir_model.discount_factor_paths(rate_paths, dt=request.dt)

        else:  # VASICEK
            v_params = VasicekParams(
                r0=request.r0 or float(curve.spot_rate(0.0)),
                kappa=request.a or 0.20,
                theta=request.theta or 0.05,
                sigma=request.sigma or 0.015,
            )
            v_esg = VasicekESG(v_params, seed=request.seed)
            rate_paths = v_esg.simulate_paths(
                n_scenarios=request.n_scenarios,
                n_years=request.n_years,
                dt=request.dt,
                method="exact",
            )
            df_paths = v_esg.discount_factor_paths(rate_paths, dt=request.dt)

        # 3. Calculate fan chart statistics
        fan_chart_rates = []
        for t_idx, t_val in enumerate(time_grid):
            col = rate_paths[:, t_idx]
            fan_chart_rates.append({
                "year": t_val,
                "p5": round(float(np.percentile(col, 5)), 5),
                "p25": round(float(np.percentile(col, 25)), 5),
                "p50": round(float(np.percentile(col, 50)), 5),
                "p75": round(float(np.percentile(col, 75)), 5),
                "p95": round(float(np.percentile(col, 95)), 5),
                "mean": round(float(np.mean(col)), 5),
            })

        sample_paths = np.round(rate_paths[:10, :], 5).tolist()

        # 4. Market vs Simulated Discount Factors
        t_arr = np.array(time_grid, dtype=np.float64)
        zero_prices = np.asarray(curve.zero_price(t_arr), dtype=np.float64)
        market_dfs = np.round(zero_prices, 5).tolist()
        sim_dfs = np.round(np.mean(df_paths, axis=0), 5).tolist()
        mae = float(np.mean(np.abs(np.array(market_dfs) - np.array(sim_dfs))))

        return ESGSimulationResponse(
            model_type=request.model_type.value,
            n_scenarios=request.n_scenarios,
            n_years=request.n_years,
            dt=request.dt,
            time_grid=time_grid,
            fan_chart_rates=fan_chart_rates,
            sample_paths=sample_paths,
            market_discount_factors=market_dfs,
            simulated_discount_factors=sim_dfs,
            pricing_error_mae=round(mae, 5),
            feller_condition_satisfied=feller_ok,
            feller_ratio=feller_rat,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("ESG simulation failed: %s", e)
        raise HTTPException(status_code=500, detail=f"ESG simulation error: {e}") from e


# ────────────────────────────────────────────────────────────
# Stress Testing & Tornado Sensitivity Endpoint
# ────────────────────────────────────────────────────────────

@app.post("/api/v1/valuation/sensitivity/tornado", response_model=SensitivityResponse)
def evaluate_sensitivity_tornado(request: SensitivityRequest) -> SensitivityResponse:
    """Run systematic multi-factor stress testing and Tornado sensitivity analysis."""
    table_id = request.table_id or "soa_ilt"
    try:
        table = table_registry.get_table(table_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Mortality table '{table_id}' not found.") from None

    try:
        contract = PolicyContract(
            product_type=request.product_type,
            issue_age=request.issue_age,
            term=request.term,
            sum_assured=request.sum_assured,
            premium_paying_term=request.premium_paying_term,
        )
        contract.validate_against_table(table)
        interest = InterestAssumption(annual_rate=request.interest_rate)
        expense = request.expense or ExpenseAssumption()
        lapse = request.lapse or LapseAssumption()

        engine = SensitivityEngine(
            table=table,
            interest=interest,
            expense=expense,
            lapse=lapse,
        )

        report = engine.run_tornado_analysis(
            contract=contract,
            gross_premium=request.gross_premium,
        )

        return SensitivityResponse(
            table_id=table_id,
            table_name=table.name,
            product_type=request.product_type,
            sum_assured=request.sum_assured,
            baseline=report.baseline.model_dump(),
            tornado_items=[item.model_dump() for item in report.tornado_items],
            combined_scenarios=[sc.model_dump() for sc in report.combined_scenarios],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Sensitivity analysis failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Sensitivity analysis error: {e}") from e


@app.post("/api/v1/valuation/stress-test", response_model=StressTestResponse)
def evaluate_stress_test_sliders(request: StressTestRequest) -> StressTestResponse:
    """Run real-time interactive stress testing with custom slider shocks."""
    base_assump = request.base_assumptions or {}
    table_id = base_assump.get("table_id") or request.table_id or "soa_ilt"
    try:
        table = table_registry.get_table(table_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Mortality table '{table_id}' not found.") from None

    try:
        prod_type = base_assump.get("product_type") or request.product_type
        issue_age = int(base_assump.get("issue_age") or request.issue_age)
        term = base_assump.get("term") if "term" in base_assump else request.term
        sum_assured = float(base_assump.get("sum_assured") or request.sum_assured)
        prem_term = base_assump.get("premium_paying_term") or request.premium_paying_term
        interest_rate = float(base_assump.get("interest_rate") or request.interest_rate)
        gross_prem = base_assump.get("gross_premium") if "gross_premium" in base_assump else request.gross_premium

        contract = PolicyContract(
            product_type=prod_type,
            issue_age=issue_age,
            term=term,
            sum_assured=sum_assured,
            premium_paying_term=prem_term,
        )
        contract.validate_against_table(table)
        interest = InterestAssumption(annual_rate=interest_rate)
        expense = request.expense or ExpenseAssumption()
        lapse = request.lapse or LapseAssumption()

        engine = SensitivityEngine(
            table=table,
            interest=interest,
            expense=expense,
            lapse=lapse,
        )

        shocks_dict = request.shocks.model_dump() if hasattr(request.shocks, "model_dump") else dict(request.shocks)
        res = engine.run_realtime_stress_test(
            contract=contract,
            shocks=shocks_dict,
            gross_premium=gross_prem,
        )

        return StressTestResponse(
            table_id=table_id,
            table_name=table.name,
            product_type=str(prod_type),
            sum_assured=sum_assured,
            baseline_reserve=res["baseline_reserve"],
            stressed_reserve=res["stressed_reserve"],
            delta_reserve=res["delta_reserve"],
            delta_pct=res["delta_pct"],
            effective_duration=res["effective_duration"],
            dv01=res["dv01"],
            effective_convexity=res["effective_convexity"],
            shocks_applied=res["shocks_applied"],
            tornado_data=res["tornado_data"],
            reserve_trajectory=res["reserve_trajectory"],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Real-time stress test valuation failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Stress test valuation error: {e}") from e


@app.post("/api/v1/contracts/validate-graph", response_model=ValidationResult)
def validate_contract_graph(payload: ContractGraphPayload) -> ValidationResult:
    """Run full actuarial validation suite against the visual blueprint."""
    validator = BlueprintValidator(table_lookup=table_registry)
    return validator.validate(payload)


@app.post("/api/v1/contracts/simulate-graph", response_model=SimulateGraphResponse)
def simulate_contract_graph(payload: ContractGraphPayload) -> SimulateGraphResponse:
    """Evaluate a visual node-based contract logic blueprint into deterministic actuarial projections."""
    try:
        # Pre-execution validation guard
        validator = BlueprintValidator(table_lookup=table_registry)
        validation_result = validator.validate(payload)
        
        if not validation_result.is_valid:
            # Reconstruct the issues into a readable string or return the JSON payload
            error_details = [i.model_dump() for i in validation_result.issues if i.severity == ValidationSeverity.ERROR]
            raise HTTPException(status_code=400, detail={"message": "Blueprint validation failed.", "errors": error_details})

        simulator = ContractGraphSimulator(table_lookup=table_registry)
        return simulator.simulate(payload)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Contract graph simulation failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Graph simulation error: {e}") from e




