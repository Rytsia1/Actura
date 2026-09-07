"""
Stochastic Valuation & Monte Carlo Risk Metrics Engine.

Provides:
- ``RiskMetricsResult``: Container for scenario BEL distributions, quantiles (VaR),
  and tail-risk measures (CVaR / Expected Shortfall).
- ``StochasticValuationEngine``: High-performance vectorized Monte Carlo engine
  coupling the Vasicek Economic Scenario Generator, dynamic policyholder lapse
  behavior, and mortality tables. Supports batch/chunked vectorized execution with
  real-time progress callbacks for asynchronous WebSockets.

Mathematical Risk Measures:
    VaR_α (Value at Risk):
        VaR_α = inf { x ∈ ℝ : P(BEL ≤ x) ≥ α }

    CVaR_α / CTE_α (Conditional Value at Risk / Tail Value at Risk):
        CVaR_α = E[ BEL | BEL ≥ VaR_α ]
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any, Optional

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from actuary_engine.models.assumptions import ExpenseAssumption, LapseAssumption
from actuary_engine.models.contracts import PolicyContract, ProductType
from actuary_engine.stochastic.dynamic_lapse import DynamicLapseModel
from actuary_engine.stochastic.esg import VasicekESG
from actuary_engine.tables.mortality_table import MortalityTable


class RiskMetricsResult(BaseModel):
    """Aggregated quantitative risk metrics from stochastic simulation.

    Attributes:
        mean_bel: Expected (mean) Best Estimate Liability across all scenarios.
        std_bel: Sample standard deviation of scenario BELs.
        var_95: Value at Risk at the 95% confidence level (95th percentile).
        var_99: Value at Risk at the 99% confidence level (99th percentile).
        cvar_95: Conditional Value at Risk / CTE at 95% (mean of worst 5% outcomes).
        cvar_99: Conditional Value at Risk / CTE at 99% (mean of worst 1% outcomes).
        min_bel: Best-case scenario liability (minimum).
        max_bel: Worst-case scenario liability (maximum).
        percentiles: Dictionary of selected percentiles (50%, 75%, 90%, 95%, 99%, 99.5%).
        scenario_bel: Full 1D array of scenario BELs (length = n_scenarios).
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    mean_bel: float = Field(..., description="Mean Best Estimate Liability.")
    std_bel: float = Field(..., description="Standard deviation of liability.")
    var_95: float = Field(..., description="Value at Risk (95% percentile).")
    var_99: float = Field(..., description="Value at Risk (99% percentile).")
    cvar_95: float = Field(..., description="Conditional Value at Risk (95%).")
    cvar_99: float = Field(..., description="Conditional Value at Risk (99%).")
    min_bel: float = Field(..., description="Minimum scenario BEL.")
    max_bel: float = Field(..., description="Maximum scenario BEL.")
    percentiles: dict[str, float] = Field(default_factory=dict)
    scenario_bel: np.ndarray = Field(..., description="Array of all scenario BEL values.")

    def summary(self) -> pd.DataFrame:
        """Return a formatted summary DataFrame of key risk statistics."""
        data = {
            "Metric": [
                "Mean BEL",
                "Std Dev (BEL)",
                "Min BEL",
                "Median (50%)",
                "75th Percentile",
                "90th Percentile",
                "VaR 95%",
                "VaR 99%",
                "CVaR 95% (CTE 95)",
                "CVaR 99% (CTE 99)",
                "Max BEL",
            ],
            "Value": [
                self.mean_bel,
                self.std_bel,
                self.min_bel,
                self.percentiles.get("50%", np.nan),
                self.percentiles.get("75%", np.nan),
                self.percentiles.get("90%", np.nan),
                self.var_95,
                self.var_99,
                self.cvar_95,
                self.cvar_99,
                self.max_bel,
            ],
        }
        return pd.DataFrame(data)


class StochasticValuationEngine:
    """Vectorized Monte Carlo liability valuation and risk engine.

    Integrates:
    1. Vasicek ESG for short-rate scenario simulation and stochastic discounting.
    2. Mortality table decrement rollout.
    3. Dynamic interest-rate-sensitive policyholder lapses.
    4. Expense cash flows (acquisition, maintenance, per-policy).
    5. Quantitative tail risk metrics (VaR & CVaR).
    6. Chunked execution with real-time asynchronous progress hooks.

    Attributes:
        table: Mortality table.
        esg: Economic Scenario Generator instance.
        expense: Optional expense loading assumptions.
        dynamic_lapse: Optional dynamic lapse model (S-curve).
        base_lapse: Optional static baseline lapse assumptions.
    """

    __slots__ = ("table", "esg", "expense", "dynamic_lapse", "base_lapse")

    def __init__(
        self,
        table: MortalityTable,
        esg: VasicekESG,
        expense: Optional[ExpenseAssumption] = None,
        dynamic_lapse: Optional[DynamicLapseModel] = None,
        base_lapse: Optional[LapseAssumption] = None,
    ) -> None:
        """Initialize stochastic valuation engine.

        Args:
            table: Mortality table instance.
            esg: VasicekESG economic scenario generator.
            expense: Optional expense loading assumptions.
            dynamic_lapse: Optional dynamic interest-rate-sensitive lapse model.
            base_lapse: Optional static baseline lapse assumptions.
        """
        self.table = table
        self.esg = esg
        self.expense = expense or ExpenseAssumption()
        self.dynamic_lapse = dynamic_lapse
        self.base_lapse = base_lapse

    def _simulate_batch(
        self,
        contract: PolicyContract,
        gross_premium: float,
        n_batch: int,
        seed: Optional[int] = None,
        surrender_values: Optional[np.ndarray] = None,
        dt: float = 1.0,
        compounding: str = "continuous",
    ) -> tuple[np.ndarray, np.ndarray]:
        """Vectorized execution of a single batch of Monte Carlo paths.

        Returns:
            Tuple of (scenario_bel_array of shape (n_batch,), short_rates_matrix of shape (n_batch, n+1))
        """
        contract.validate_against_table(self.table)

        x = contract.issue_age
        face = contract.sum_assured
        ptype = contract.product_type
        n = contract.term if contract.term is not None else (self.table.omega - x)
        h = contract.effective_premium_term if contract.effective_premium_term is not None else n

        # 1. Economic Scenarios & Discount Factors
        short_rates = self.esg.simulate_paths(
            n_scenarios=n_batch,
            n_years=n,
            dt=dt,
            method="exact",
            seed=seed,
        )

        discount_matrix = self.esg.compute_discount_factors(
            short_rates, dt=dt, compounding=compounding
        )
        disc_boy = discount_matrix[:, :n]
        disc_eoy = discount_matrix[:, 1:n + 1]

        # 2. Decrements
        years = np.arange(n, dtype=np.int64)

        if self.dynamic_lapse is not None:
            market_rates_during = short_rates[:, :n]
            if self.base_lapse is not None:
                base_vec = np.array([self.base_lapse.get_rate(int(t) + 1) for t in years])
                w_indep = self.dynamic_lapse.compute_lapse_rates(market_rates_during, base_vec)
            else:
                w_indep = self.dynamic_lapse.compute_lapse_rates(market_rates_during)
        elif self.base_lapse is not None:
            base_vec = np.array([self.base_lapse.get_rate(int(t) + 1) for t in years])
            w_indep = np.broadcast_to(base_vec, (n_batch, n))
        else:
            w_indep = np.zeros((n_batch, n), dtype=np.float64)

        x_idx = x - self.table.min_age
        q_indep_vec = self.table.qx[x_idx: x_idx + n]
        q_indep = np.broadcast_to(q_indep_vec, (n_batch, n))

        q_dep = q_indep * (1.0 - w_indep / 2.0)
        w_dep = w_indep * (1.0 - q_indep / 2.0)
        p_survival_step = np.clip(1.0 - q_dep - w_dep, 0.0, 1.0)

        inforce = np.empty((n_batch, n), dtype=np.float64)
        inforce[:, 0] = 1.0
        if n > 1:
            inforce[:, 1:] = np.cumprod(p_survival_step[:, :-1], axis=1)

        # 3. Cash Flow Components
        prem_mask = (years < h).astype(np.float64)
        prem_income = gross_premium * inforce * prem_mask

        if ptype == ProductType.PURE_ENDOWMENT:
            death_claims = np.zeros((n_batch, n), dtype=np.float64)
        else:
            death_claims = face * inforce * q_dep

        if surrender_values is not None:
            cv = np.asarray(surrender_values, dtype=np.float64)
            if len(cv) < n:
                cv = np.pad(cv, (0, n - len(cv)), constant_values=0.0)
            cv_mat = np.broadcast_to(cv[:n], (n_batch, n))
            lapse_payouts = cv_mat * inforce * w_dep
        else:
            lapse_payouts = np.zeros((n_batch, n), dtype=np.float64)

        if ptype in (ProductType.ENDOWMENT, ProductType.PURE_ENDOWMENT):
            survivors_at_mat = inforce[:, -1] * p_survival_step[:, -1]
            maturity_payout = face * survivors_at_mat
        else:
            maturity_payout = np.zeros(n_batch, dtype=np.float64)

        exp = self.expense
        pct_rate = np.where(
            years == 0,
            exp.percent_of_premium_first,
            exp.percent_of_premium_renewal,
        )
        pct_exp = prem_income * pct_rate

        per_pol_rate = np.where(
            years == 0,
            exp.per_policy_first,
            exp.per_policy_renewal,
        )
        per_pol_exp = inforce * per_pol_rate
        total_exp = pct_exp + per_pol_exp

        # 4. Present Value Net Liabilities
        pv_prem = np.sum(prem_income * disc_boy, axis=1)
        pv_death = np.sum(death_claims * disc_eoy, axis=1)
        pv_lapse = np.sum(lapse_payouts * disc_eoy, axis=1)
        pv_exp = np.sum(total_exp * disc_boy, axis=1)
        pv_maturity = maturity_payout * disc_eoy[:, -1]

        scenario_bel = pv_death + pv_lapse + pv_maturity + pv_exp - pv_prem
        return scenario_bel, short_rates

    def _aggregate_metrics(self, scenario_bel: np.ndarray) -> RiskMetricsResult:
        """Compute summary statistics, VaR, and CVaR from an array of scenario BELs."""
        n_scenarios = len(scenario_bel)
        mean_bel = float(np.mean(scenario_bel))
        std_bel = float(np.std(scenario_bel, ddof=1)) if n_scenarios > 1 else 0.0
        min_bel = float(np.min(scenario_bel))
        max_bel = float(np.max(scenario_bel))

        var_95 = float(np.percentile(scenario_bel, 95.0))
        var_99 = float(np.percentile(scenario_bel, 99.0))

        tail_95 = scenario_bel[scenario_bel >= var_95]
        cvar_95 = float(np.mean(tail_95)) if len(tail_95) > 0 else var_95

        tail_99 = scenario_bel[scenario_bel >= var_99]
        cvar_99 = float(np.mean(tail_99)) if len(tail_99) > 0 else var_99

        percentiles_dict = {
            "50%": float(np.percentile(scenario_bel, 50.0)),
            "75%": float(np.percentile(scenario_bel, 75.0)),
            "90%": float(np.percentile(scenario_bel, 90.0)),
            "95%": var_95,
            "99%": var_99,
            "99.5%": float(np.percentile(scenario_bel, 99.5)),
        }

        return RiskMetricsResult(
            mean_bel=mean_bel,
            std_bel=std_bel,
            var_95=var_95,
            var_99=var_99,
            cvar_95=cvar_95,
            cvar_99=cvar_99,
            min_bel=min_bel,
            max_bel=max_bel,
            percentiles=percentiles_dict,
            scenario_bel=scenario_bel,
        )

    def run_simulation(
        self,
        contract: PolicyContract,
        gross_premium: float,
        n_scenarios: int = 2000,
        seed: Optional[int] = None,
        surrender_values: Optional[np.ndarray] = None,
        dt: float = 1.0,
        compounding: str = "continuous",
    ) -> RiskMetricsResult:
        """Run path-dependent Monte Carlo simulation of policy liabilities.

        Args:
            contract: Policy contract specification.
            gross_premium: Annual gross premium paid by policyholder.
            n_scenarios: Number of Monte Carlo scenario paths (default 2000).
            seed: Optional random seed for reproducible runs.
            surrender_values: Optional 1D array of cash surrender values by duration.
            dt: Time step size in years (default 1.0 for annual).
            compounding: Discount compounding model ('continuous' or 'discrete').

        Returns:
            RiskMetricsResult containing distribution statistics and scenario array.
        """
        if n_scenarios <= 0:
            raise ValueError(f"n_scenarios must be positive. Got {n_scenarios}.")

        scenario_bel, _ = self._simulate_batch(
            contract=contract,
            gross_premium=gross_premium,
            n_batch=n_scenarios,
            seed=seed,
            surrender_values=surrender_values,
            dt=dt,
            compounding=compounding,
        )

        return self._aggregate_metrics(scenario_bel)

    async def evaluate_liability_distribution_async(
        self,
        contract: PolicyContract,
        gross_premium: float,
        n_scenarios: int = 10000,
        chunk_size: int = 1000,
        seed: Optional[int] = None,
        surrender_values: Optional[np.ndarray] = None,
        dt: float = 1.0,
        compounding: str = "continuous",
        progress_callback: Optional[Callable[[int, int, dict[str, Any]], Coroutine[Any, Any, None]]] = None,
    ) -> tuple[RiskMetricsResult, np.ndarray]:
        """Execute large-scale Monte Carlo simulation in vectorized batches with real-time progress callbacks.

        Args:
            contract: Policy contract.
            gross_premium: Annual gross premium.
            n_scenarios: Total number of scenarios (e.g. 10,000+).
            chunk_size: Vectorized batch size per iteration (default 1000).
            seed: Master random seed.
            surrender_values: Surrender values schedule.
            dt: Time step.
            compounding: Compounding method.
            progress_callback: Optional async callback (completed_paths, total_paths, partial_summary).

        Returns:
            Tuple of (RiskMetricsResult, all_short_rates_sample_matrix)
        """
        if n_scenarios <= 0:
            raise ValueError(f"n_scenarios must be positive. Got {n_scenarios}.")

        all_bels: list[np.ndarray] = []
        sample_rates: list[np.ndarray] = []
        completed = 0
        current_seed = seed

        # Number of chunks
        n_chunks = int(np.ceil(n_scenarios / chunk_size))

        for chunk_idx in range(n_chunks):
            current_batch_size = min(chunk_size, n_scenarios - completed)
            batch_seed = (current_seed + chunk_idx * 1000) if current_seed is not None else None

            # Execute batch synchronously in thread or loop
            batch_bel, batch_rates = self._simulate_batch(
                contract=contract,
                gross_premium=gross_premium,
                n_batch=current_batch_size,
                seed=batch_seed,
                surrender_values=surrender_values,
                dt=dt,
                compounding=compounding,
            )

            all_bels.append(batch_bel)
            if len(sample_rates) < 15:
                sample_rates.append(batch_rates[: min(15 - len(sample_rates), current_batch_size)])

            completed += current_batch_size

            # Broadcast progress to callback
            if progress_callback is not None:
                partial_concatenated = np.concatenate(all_bels)
                partial_mean = float(np.mean(partial_concatenated))
                partial_var95 = float(np.percentile(partial_concatenated, 95.0))
                partial_metrics = {
                    "mean_bel": round(partial_mean, 2),
                    "var_95": round(partial_var95, 2),
                }
                await progress_callback(completed, n_scenarios, partial_metrics)
                # Yield control to event loop so WebSockets can broadcast smoothly
                await asyncio.sleep(0.001)

        full_scenario_bel = np.concatenate(all_bels)
        final_result = self._aggregate_metrics(full_scenario_bel)
        combined_samples = np.vstack(sample_rates) if sample_rates else np.empty((0, 0))

        return final_result, combined_samples

    def evaluate_liability_distribution_sync(
        self,
        contract: PolicyContract,
        gross_premium: float,
        n_scenarios: int = 10000,
        chunk_size: int = 1000,
        seed: Optional[int] = None,
        surrender_values: Optional[np.ndarray] = None,
        dt: float = 1.0,
        compounding: str = "continuous",
        progress_queue: Optional[Any] = None,
    ) -> tuple[RiskMetricsResult, np.ndarray]:
        """Execute large-scale Monte Carlo simulation synchronously with queue-based progress.

        Args:
            contract: Policy contract.
            gross_premium: Annual gross premium.
            n_scenarios: Total number of scenarios (e.g. 10,000+).
            chunk_size: Vectorized batch size per iteration (default 1000).
            seed: Master random seed.
            surrender_values: Surrender values schedule.
            dt: Time step.
            compounding: Compounding method.
            progress_queue: Optional multiprocessing.Queue to put (completed, total, partial_summary).

        Returns:
            Tuple of (RiskMetricsResult, all_short_rates_sample_matrix)
        """
        if n_scenarios <= 0:
            raise ValueError(f"n_scenarios must be positive. Got {n_scenarios}.")

        all_bels: list[np.ndarray] = []
        sample_rates: list[np.ndarray] = []
        completed = 0
        current_seed = seed

        # Number of chunks
        n_chunks = int(np.ceil(n_scenarios / chunk_size))

        for chunk_idx in range(n_chunks):
            current_batch_size = min(chunk_size, n_scenarios - completed)
            batch_seed = (current_seed + chunk_idx * 1000) if current_seed is not None else None

            batch_bel, batch_rates = self._simulate_batch(
                contract=contract,
                gross_premium=gross_premium,
                n_batch=current_batch_size,
                seed=batch_seed,
                surrender_values=surrender_values,
                dt=dt,
                compounding=compounding,
            )

            all_bels.append(batch_bel)
            if len(sample_rates) < 15:
                sample_rates.append(batch_rates[: min(15 - len(sample_rates), current_batch_size)])

            completed += current_batch_size

            # Broadcast progress to queue
            if progress_queue is not None:
                partial_concatenated = np.concatenate(all_bels)
                partial_mean = float(np.mean(partial_concatenated))
                partial_var95 = float(np.percentile(partial_concatenated, 95.0))
                partial_metrics = {
                    "mean_bel": round(partial_mean, 2),
                    "var_95": round(partial_var95, 2),
                }
                # Put progress event on queue
                progress_queue.put({
                    "completed": completed,
                    "total": n_scenarios,
                    "partial_metrics": partial_metrics
                })

        full_scenario_bel = np.concatenate(all_bels)
        final_result = self._aggregate_metrics(full_scenario_bel)
        combined_samples = np.vstack(sample_rates) if sample_rates else np.empty((0, 0))

        return final_result, combined_samples

    def __repr__(self) -> str:
        return (
            f"StochasticValuationEngine(table='{self.table.name}', "
            f"esg={self.esg!r}, dynamic_lapse={self.dynamic_lapse is not None})"
        )


def compute_quantile_trajectory(
    path_matrix: np.ndarray,
    percentiles: tuple[float, ...] = (5.0, 25.0, 50.0, 75.0, 95.0),
) -> dict[str, list[float]]:
    """Compute cross-sectional quantiles at each timestep for a 2D path matrix (n_scenarios x n_timesteps).

    Args:
        path_matrix: 2D numpy array of shape (n_scenarios, n_timesteps).
        percentiles: Tuple of percentile levels (5, 25, 50, 75, 95).

    Returns:
        Dictionary with keys 'p5', 'p25', 'p50', 'p75', 'p95', each containing a list of floats.
    """
    if path_matrix.ndim != 2 or path_matrix.shape[0] == 0 or path_matrix.shape[1] == 0:
        return {"p5": [], "p25": [], "p50": [], "p75": [], "p95": []}

    q_matrix = np.percentile(path_matrix, percentiles, axis=0)

    return {
        "p5": [round(float(v), 5) for v in q_matrix[0]],
        "p25": [round(float(v), 5) for v in q_matrix[1]],
        "p50": [round(float(v), 5) for v in q_matrix[2]],
        "p75": [round(float(v), 5) for v in q_matrix[3]],
        "p95": [round(float(v), 5) for v in q_matrix[4]],
    }


def compute_terminal_distribution(
    terminal_values: np.ndarray,
    bins: int = 40,
) -> dict[str, Any]:
    """Compute statistical moments, tail risk metrics, and histogram binning for terminal liabilities.

    Args:
        terminal_values: 1D array of scenario outcomes.
        bins: Number of histogram bins.

    Returns:
        Dictionary with bin_edges, counts, mean, std, skewness, var_95, cvar_95, var_99, cvar_99.
    """
    if len(terminal_values) == 0:
        return {
            "bin_edges": [],
            "counts": [],
            "mean": 0.0,
            "std": 0.0,
            "skewness": 0.0,
            "var_95": 0.0,
            "cvar_95": 0.0,
            "var_99": 0.0,
            "cvar_99": 0.0,
        }

    arr = np.asarray(terminal_values, dtype=np.float64)
    counts, bin_edges = np.histogram(arr, bins=bins)

    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0

    if std > 1e-12:
        skewness = float(np.mean(((arr - mean) / std) ** 3))
    else:
        skewness = 0.0

    var_95 = float(np.percentile(arr, 95.0))
    var_99 = float(np.percentile(arr, 99.0))

    tail_95 = arr[arr >= var_95]
    cvar_95 = float(np.mean(tail_95)) if len(tail_95) > 0 else var_95

    tail_99 = arr[arr >= var_99]
    cvar_99 = float(np.mean(tail_99)) if len(tail_99) > 0 else var_99

    return {
        "bin_edges": [round(float(e), 2) for e in bin_edges],
        "counts": [int(c) for c in counts],
        "mean": round(mean, 2),
        "std": round(std, 2),
        "skewness": round(skewness, 4),
        "var_95": round(var_95, 2),
        "cvar_95": round(cvar_95, 2),
        "var_99": round(var_99, 2),
        "cvar_99": round(cvar_99, 2),
    }


def sample_representative_paths(
    path_matrix: np.ndarray,
    max_paths: int = 15,
) -> list[list[float]]:
    """Sample a compressed representative subset of paths (median, extreme min, extreme max, stratified).

    Args:
        path_matrix: 2D numpy array of paths (n_scenarios, n_timesteps).
        max_paths: Maximum number of representative traces to return.

    Returns:
        List of representative float paths.
    """
    n_scenarios = len(path_matrix)
    if n_scenarios == 0:
        return []
    if n_scenarios <= max_paths:
        return [[round(float(v), 5) for v in path] for path in path_matrix]

    terminal_vals = path_matrix[:, -1]
    sorted_indices = np.argsort(terminal_vals)

    # Evenly spaced quantiles across the sorted paths
    quantile_positions = np.linspace(0, n_scenarios - 1, max_paths).round().astype(int)
    unique_positions = sorted(list(set(quantile_positions)))

    selected_indices = [int(sorted_indices[pos]) for pos in unique_positions]
    if len(selected_indices) < max_paths:
        for idx in sorted_indices:
            if int(idx) not in selected_indices:
                selected_indices.append(int(idx))
            if len(selected_indices) == max_paths:
                break

    return [[round(float(v), 5) for v in path_matrix[idx]] for idx in selected_indices]


