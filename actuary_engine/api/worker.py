import multiprocessing
import numpy as np
from typing import Any, Dict

from actuary_engine.api.schemas import StochasticValuationRequest, StochasticValuationResponse, QuantileTrajectory, TerminalDistribution
from actuary_engine.models.assumptions import ExpenseAssumption, InterestAssumption
from actuary_engine.models.contracts import PolicyContract
from actuary_engine.pricing.premium import LevelPremiumCalculator
from actuary_engine.stochastic.dynamic_lapse import DynamicLapseModel
from actuary_engine.stochastic.esg import VasicekESG
from actuary_engine.stochastic.monte_carlo import (
    StochasticValuationEngine,
    compute_quantile_trajectory,
    compute_terminal_distribution,
    sample_representative_paths,
)
from actuary_engine.tables.commutation import CommutationFunctions
from actuary_engine.tables.mortality_table import MortalityTable


def _cpu_worker_task(request_dict: dict[str, Any], table_dict: dict[str, Any], progress_queue: multiprocessing.Queue) -> dict[str, Any]:
    """Top-level synchronous function executed by ProcessPoolExecutor."""
    request = StochasticValuationRequest(**request_dict)
    
    # Reconstruct table object
    table_kwargs = {k: v for k, v in table_dict.items() if k in ('ages', 'qx', 'name', 'radix')}
    if 'ages' in table_kwargs:
        table_kwargs['ages'] = np.array(table_kwargs['ages'], dtype=np.int64)
    if 'qx' in table_kwargs:
        table_kwargs['qx'] = np.array(table_kwargs['qx'], dtype=np.float64)
    
    table = MortalityTable(**table_kwargs)

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
    stoch_res, _ = engine.evaluate_liability_distribution_sync(
        contract=contract,
        gross_premium=gross_premium,
        n_scenarios=request.n_scenarios,
        chunk_size=chunk_size,
        seed=request.seed,
        progress_queue=progress_queue,
    )

    # Analytics for short rates
    n_years = contract.term if contract.term is not None else (table.omega - contract.issue_age)
    rates_paths = esg.simulate_paths(
        n_scenarios=min(2500, request.n_scenarios),
        n_years=n_years,
        dt=1.0,
        method="exact",
        seed=request.seed,
    )

    quantiles_dict = compute_quantile_trajectory(rates_paths)
    quantiles_obj = QuantileTrajectory(**quantiles_dict)

    term_dist_dict = compute_terminal_distribution(stoch_res.scenario_bel, bins=40)
    term_dist_obj = TerminalDistribution(**term_dist_dict)

    sample_paths = sample_representative_paths(rates_paths, max_paths=15)

    timesteps = list(range(rates_paths.shape[1]))

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

    fan_chart_rates = []
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

    histogram_data = []
    bin_edges = term_dist_dict["bin_edges"]
    counts = term_dist_dict["counts"]
    for i in range(len(counts)):
        histogram_data.append({
            "bin_start": bin_edges[i],
            "bin_end": bin_edges[i + 1],
            "bin_mid": round(float((bin_edges[i] + bin_edges[i + 1]) / 2.0), 2),
            "count": counts[i],
        })

    result = StochasticValuationResponse(
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
    return result.model_dump()
