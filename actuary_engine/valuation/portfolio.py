"""
High-Performance Seriatim Batch Portfolio Valuation Engine.

Vectorized matrix operations and parallel multi-core execution for evaluating
thousands of policyholder contracts simultaneously.

Computes:
- Portfolio Present Value of Future Benefits (PVFB).
- Portfolio Present Value of Future Premiums (PVFP).
- Portfolio Present Value of Future Expenses (PVFE).
- Portfolio Best Estimate Liability (BEL).
- Annual cash flow waterfall and reserve trajectories.
- Multi-dimensional cohort breakdowns (Age, Product Type, Duration).
"""

from __future__ import annotations

import io
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from typing import Any, Optional, Union, cast

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from actuary_engine.models.assumptions import ExpenseAssumption, InterestAssumption, LapseAssumption
from actuary_engine.models.contracts import ProductType
from actuary_engine.domain.tables.mortality_table import MortalityTable


class PortfolioSummary(BaseModel):
    """Aggregated portfolio valuation results and segment breakdowns."""

    total_policies: int = Field(..., description="Total active policies evaluated.")
    total_sum_assured: float = Field(..., description="Total face amount of coverage.")
    total_pvfb: float = Field(..., description="Total Present Value of Future Benefits.")
    total_pvfp: float = Field(..., description="Total Present Value of Future Premiums.")
    total_pvfe: float = Field(..., description="Total Present Value of Future Expenses.")
    total_bel: float = Field(..., description="Total Best Estimate Liability (PVFB + PVFE - PVFP).")
    annual_cash_flows: list[dict[str, Any]] = Field(..., description="Annual aggregate cash flows.")
    product_breakdown: dict[str, dict[str, Any]] = Field(..., description="Metrics by product type.")
    age_breakdown: dict[str, dict[str, Any]] = Field(..., description="Metrics by age bracket.")
    duration_breakdown: dict[str, dict[str, Any]] = Field(..., description="Metrics by duration band.")


class PortfolioValuationEngine:
    """Vectorized Seriatim Batch Valuation Engine for Life Insurance Portfolios.

    Attributes:
        table: Mortality table instance.
        interest: Interest rate assumption.
        expense: Expense loading assumption.
        lapse: Policyholder lapse assumption.
    """

    __slots__ = ("table", "interest", "expense", "lapse")

    def __init__(
        self,
        table: MortalityTable,
        interest: Optional[InterestAssumption] = None,
        expense: Optional[ExpenseAssumption] = None,
        lapse: Optional[LapseAssumption] = None,
    ) -> None:
        self.table = table
        self.interest = interest or InterestAssumption(annual_rate=0.05)
        self.expense = expense or ExpenseAssumption(
            percent_of_premium_first=0.35,
            percent_of_premium_renewal=0.05,
            per_policy_first=200.0,
            per_policy_renewal=20.0,
        )
        self.lapse = lapse or LapseAssumption(flat_annual_rate=0.03)

    def load_portfolio_df(self, source: Union[pd.DataFrame, str, bytes, io.IOBase]) -> pd.DataFrame:
        """Parse and normalize input portfolio data into a standardized DataFrame.

        Supported columns:
        - policy_id (str / int)
        - issue_age (int)
        - term_years (int, optional for whole life)
        - sum_assured (float)
        - gross_premium (float)
        - product_type (str: 'term', 'endowment', 'whole_life', 'pure_endowment')
        - policy_duration_years (int, default 0)
        - premium_paying_term (int, optional)
        - gender (str, optional)
        """
        if isinstance(source, pd.DataFrame):
            df = source.copy()
        elif isinstance(source, bytes):
            df = pd.read_csv(io.BytesIO(source))
        elif isinstance(source, str):
            if "\n" in source or "," in source:
                df = pd.read_csv(io.StringIO(source))
            else:
                df = pd.read_csv(source)
        elif isinstance(source, (io.StringIO, io.BytesIO)):
            df = pd.read_csv(source)
        else:
            df = pd.read_csv(cast(Any, source))

        # Normalize column names
        df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")

        # Required columns validation
        required_cols = {"issue_age", "sum_assured", "gross_premium"}
        missing = required_cols - set(df.columns)
        if missing:
            raise ValueError(f"Portfolio data missing required columns: {missing}")

        # Provide defaults for optional columns
        if "policy_id" not in df.columns:
            df["policy_id"] = [f"POL-{i+1:06d}" for i in range(len(df))]
        else:
            df["policy_id"] = df["policy_id"].astype(str)

        if "product_type" not in df.columns:
            df["product_type"] = "term"
        else:
            df["product_type"] = df["product_type"].astype(str).str.lower().str.strip()

        if "policy_duration_years" not in df.columns:
            if "duration" in df.columns:
                df["policy_duration_years"] = df["duration"]
            else:
                df["policy_duration_years"] = 0
        df["policy_duration_years"] = df["policy_duration_years"].fillna(0).astype(int)

        if "term_years" not in df.columns:
            if "term" in df.columns:
                df["term_years"] = df["term"]
            else:
                df["term_years"] = 20

        # Fill missing terms for whole life
        whole_life_mask = df["product_type"] == "whole_life"
        df.loc[whole_life_mask, "term_years"] = (
            self.table.omega - df.loc[whole_life_mask, "issue_age"]
        )
        df["term_years"] = df["term_years"].fillna(20).astype(int)

        if "premium_paying_term" not in df.columns:
            df["premium_paying_term"] = df["term_years"]
        df["premium_paying_term"] = df["premium_paying_term"].fillna(df["term_years"]).astype(int)

        # Attained Age & Remaining Horizon
        issue_age_arr = df["issue_age"].to_numpy(dtype=np.int64)
        pol_dur_arr = df["policy_duration_years"].to_numpy(dtype=np.int64)
        term_years_arr = df["term_years"].to_numpy(dtype=np.int64)
        prem_term_arr = df["premium_paying_term"].to_numpy(dtype=np.int64)

        df["attained_age"] = np.asarray(issue_age_arr + pol_dur_arr, dtype=np.int64)
        df["remaining_term"] = np.asarray(np.maximum(0, term_years_arr - pol_dur_arr), dtype=np.int64)
        df["remaining_prem_term"] = np.asarray(
            np.maximum(0, np.minimum(term_years_arr - pol_dur_arr, prem_term_arr - pol_dur_arr)),
            dtype=np.int64,
        )

        # Validate ages and terms against the mortality table (the source of truth)
        min_age = self.table.min_age
        max_age = self.table.max_age
        table_name = self.table.name

        under_age_mask = issue_age_arr < min_age
        if under_age_mask.any():
            bad_row = df[under_age_mask].iloc[0]
            raise ValueError(
                f"Policy '{bad_row['policy_id']}': issue age ({bad_row['issue_age']}) is below "
                f"mortality table minimum age {min_age} ({table_name})."
            )

        over_age_mask = issue_age_arr > max_age
        if over_age_mask.any():
            bad_row = df[over_age_mask].iloc[0]
            raise ValueError(
                f"Policy '{bad_row['policy_id']}': issue age ({bad_row['issue_age']}) exceeds "
                f"mortality table maximum age {max_age} ({table_name})."
            )

        attained_over_mask = (issue_age_arr + pol_dur_arr) > max_age
        if attained_over_mask.any():
            bad_row = df[attained_over_mask].iloc[0]
            raise ValueError(
                f"Policy '{bad_row['policy_id']}': attained age ({bad_row['issue_age'] + bad_row['policy_duration_years']}) "
                f"exceeds mortality table maximum age {max_age} ({table_name})."
            )

        # For finite term products, validate maturity horizon does not exceed table.max_age
        non_whole_life = df["product_type"] != "whole_life"
        exceed_term_mask = non_whole_life & ((issue_age_arr + term_years_arr) > max_age)
        if exceed_term_mask.any():
            bad_row = df[exceed_term_mask].iloc[0]
            raise ValueError(
                f"Policy '{bad_row['policy_id']}': issue_age ({bad_row['issue_age']}) + term ({bad_row['term_years']}) = "
                f"{bad_row['issue_age'] + bad_row['term_years']} exceeds mortality table maximum age "
                f"(omega) of {max_age} ({table_name})."
            )

        # Validate premium paying term does not exceed table.max_age
        exceed_prem_term_mask = (issue_age_arr + prem_term_arr) > max_age
        if exceed_prem_term_mask.any():
            bad_row = df[exceed_prem_term_mask].iloc[0]
            raise ValueError(
                f"Policy '{bad_row['policy_id']}': issue_age ({bad_row['issue_age']}) + premium_paying_term ({bad_row['premium_paying_term']}) = "
                f"{bad_row['issue_age'] + bad_row['premium_paying_term']} exceeds mortality table maximum age "
                f"(omega) of {max_age} ({table_name})."
            )

        return df

    def evaluate_portfolio(self, df: pd.DataFrame) -> tuple[pd.DataFrame, PortfolioSummary]:
        """Vectorized seriatim batch valuation across all policyholder contracts.

        Args:
            df: Normalized portfolio DataFrame.

        Returns:
            Tuple of (seriatim_results_df, portfolio_summary).
        """
        n_policies = len(df)
        if n_policies == 0:
            raise ValueError("Cannot evaluate empty portfolio.")

        # ────────────────────────────────────────────────────────
        # 1. Setup Vectorized Array Dimensions
        # ────────────────────────────────────────────────────────
        rem_terms = df["remaining_term"].to_numpy(dtype=np.int64)
        rem_prem_terms = df["remaining_prem_term"].to_numpy(dtype=np.int64)
        attained_ages = df["attained_age"].to_numpy(dtype=np.int64)
        durations = df["policy_duration_years"].to_numpy(dtype=np.int64)
        faces = df["sum_assured"].to_numpy(dtype=np.float64)
        gross_prems = df["gross_premium"].to_numpy(dtype=np.float64)
        ptypes = df["product_type"].to_numpy(dtype=str)

        max_horizon = int(np.max(rem_terms))
        if max_horizon <= 0:
            max_horizon = 1

        years = np.arange(max_horizon, dtype=np.int64)  # (T,)
        v = self.interest.discount_factor

        # ────────────────────────────────────────────────────────
        # 2. Vectorized Decrement Matrices (N, T)
        # ────────────────────────────────────────────────────────
        # Active horizon mask: True where t < rem_terms[i]
        active_mask = years[np.newaxis, :] < rem_terms[:, np.newaxis]  # (N, T)
        prem_mask = years[np.newaxis, :] < rem_prem_terms[:, np.newaxis]  # (N, T)

        # Attained age grid: (N, T)
        age_grid = attained_ages[:, np.newaxis] + years[np.newaxis, :]
        age_grid_clipped = np.clip(age_grid, self.table.min_age, self.table.omega)
        age_indices = age_grid_clipped - self.table.min_age

        # Vectorized qx mortality lookup
        qx_table = self.table.qx
        qx_indep = qx_table[age_indices]  # (N, T)

        # Vectorized lapse rate lookup
        pol_duration_grid = durations[:, np.newaxis] + years[np.newaxis, :] + 1  # 1-indexed duration
        wx_indep = self._vectorized_lapse_lookup(pol_duration_grid)  # (N, T)

        # UDD dependent rates
        qx_dep = qx_indep * (1.0 - wx_indep / 2.0)
        wx_dep = wx_indep * (1.0 - qx_indep / 2.0)

        # Step survival factor: 1 - q_dep - w_dep
        p_step = np.clip(1.0 - qx_dep - wx_dep, 0.0, 1.0)
        # Inactive cells set to 1.0 to avoid affecting cumprod
        p_step_masked = np.where(active_mask, p_step, 1.0)

        # In-force cohort rollout: L[:, 0] = 1.0; L[:, t] = prod(p_step[:, :t])
        inforce_matrix = np.empty((n_policies, max_horizon), dtype=np.float64)
        inforce_matrix[:, 0] = 1.0
        if max_horizon > 1:
            inforce_matrix[:, 1:] = np.cumprod(p_step_masked[:, :-1], axis=1)

        # Zero out inactive cells
        inforce_matrix = np.where(active_mask, inforce_matrix, 0.0)

        # ────────────────────────────────────────────────────────
        # 3. Vectorized Cash Flow Matrices (N, T)
        # ────────────────────────────────────────────────────────
        # Premium Income (BOY)
        prem_income = np.where(prem_mask, gross_prems[:, np.newaxis] * inforce_matrix, 0.0)

        # Death Claims (EOY)
        is_pure_endow = (ptypes == "pure_endowment")[:, np.newaxis]
        death_claims = np.where(active_mask, faces[:, np.newaxis] * inforce_matrix * qx_dep, 0.0)
        death_claims = np.where(is_pure_endow, 0.0, death_claims)  # (N, T)

        # Maturity Benefit (EOY of terminal year n_i - 1)
        maturity_benefits = np.zeros((n_policies, max_horizon), dtype=np.float64)
        is_endow = np.isin(ptypes, ["endowment", "pure_endowment"])

        terminal_t = rem_terms - 1
        valid_term_mask = np.logical_and.reduce((terminal_t >= 0, terminal_t < max_horizon, is_endow))

        if np.any(valid_term_mask):
            valid_indices = np.where(valid_term_mask)[0]
            valid_t = terminal_t[valid_indices]
            survivors_at_mat = (
                inforce_matrix[valid_indices, valid_t] * p_step[valid_indices, valid_t]
            )
            maturity_benefits[valid_indices, valid_t] = faces[valid_indices] * survivors_at_mat

        # Expenses (BOY)
        pct_rate = np.where(
            (durations[:, np.newaxis] + years[np.newaxis, :]) == 0,
            self.expense.percent_of_premium_first,
            self.expense.percent_of_premium_renewal,
        )
        per_pol_rate = np.where(
            (durations[:, np.newaxis] + years[np.newaxis, :]) == 0,
            self.expense.per_policy_first,
            self.expense.per_policy_renewal,
        )
        expenses = (prem_income * pct_rate) + np.where(active_mask, inforce_matrix * per_pol_rate, 0.0)

        # ────────────────────────────────────────────────────────
        # 4. Vectorized Discounting & Present Values
        # ────────────────────────────────────────────────────────
        disc_boy = v ** years  # (T,)
        disc_eoy = v ** (years + 1)  # (T,)

        pvfp_per_policy = np.sum(prem_income * disc_boy[np.newaxis, :], axis=1)
        pv_death_per_policy = np.sum(death_claims * disc_eoy[np.newaxis, :], axis=1)
        pv_mat_per_policy = np.sum(maturity_benefits * disc_eoy[np.newaxis, :], axis=1)
        pvfb_per_policy = pv_death_per_policy + pv_mat_per_policy
        pvfe_per_policy = np.sum(expenses * disc_boy[np.newaxis, :], axis=1)
        bel_per_policy = pvfb_per_policy + pvfe_per_policy - pvfp_per_policy

        # Attach seriatim results to DataFrame
        res_df = df.assign(
            pvfb=np.asarray(np.round(pvfb_per_policy, 2), dtype=np.float64),
            pvfp=np.asarray(np.round(pvfp_per_policy, 2), dtype=np.float64),
            pvfe=np.asarray(np.round(pvfe_per_policy, 2), dtype=np.float64),
            bel=np.asarray(np.round(bel_per_policy, 2), dtype=np.float64),
        )

        # ────────────────────────────────────────────────────────
        # 5. Annual Aggregate Waterfall
        # ────────────────────────────────────────────────────────
        agg_prem = np.sum(prem_income, axis=0)
        agg_death = np.sum(death_claims, axis=0)
        agg_mat = np.sum(maturity_benefits, axis=0)
        agg_exp = np.sum(expenses, axis=0)
        agg_outgo = agg_death + agg_mat + agg_exp
        agg_net_cf = agg_outgo - agg_prem
        agg_pv_net = agg_net_cf * disc_eoy

        annual_cash_flows = []
        for t in range(max_horizon):
            annual_cash_flows.append({
                "year": t + 1,
                "premium_income": round(float(agg_prem[t]), 2),
                "death_claims": round(float(agg_death[t]), 2),
                "maturity_benefits": round(float(agg_mat[t]), 2),
                "total_expenses": round(float(agg_exp[t]), 2),
                "net_liability_cf": round(float(agg_net_cf[t]), 2),
                "pv_net_liability": round(float(agg_pv_net[t]), 2),
            })

        # ────────────────────────────────────────────────────────
        # 6. Segment Breakdown Analytics
        # ────────────────────────────────────────────────────────
        # By Product Type
        prod_breakdown: dict[str, dict[str, Any]] = {}
        for ptype, group in res_df.groupby("product_type"):
            prod_breakdown[str(ptype)] = {
                "count": int(len(group)),
                "sum_assured": round(float(group["sum_assured"].sum()), 2),
                "pvfb": round(float(group["pvfb"].sum()), 2),
                "pvfp": round(float(group["pvfp"].sum()), 2),
                "pvfe": round(float(group["pvfe"].sum()), 2),
                "bel": round(float(group["bel"].sum()), 2),
            }

        # By Age Bracket (<30, 30-44, 45-59, 60+)
        age_bins = [0, 30, 45, 60, 150]
        age_labels = ["<30", "30-44", "45-59", "60+"]
        res_df["age_bracket"] = pd.cut(
            res_df["attained_age"], bins=age_bins, labels=age_labels, right=False
        )
        age_breakdown = {}
        for label, group in res_df.groupby("age_bracket", observed=False):
            age_breakdown[str(label)] = {
                "count": int(len(group)),
                "sum_assured": round(float(group["sum_assured"].sum()), 2),
                "bel": round(float(group["bel"].sum()), 2),
            }

        # By Duration Band (0-4, 5-9, 10-19, 20+)
        dur_bins = [0, 5, 10, 20, 150]
        dur_labels = ["0-4 yrs", "5-9 yrs", "10-19 yrs", "20+ yrs"]
        res_df["duration_band"] = pd.cut(
            res_df["policy_duration_years"], bins=dur_bins, labels=dur_labels, right=False
        )
        duration_breakdown = {}
        for label, group in res_df.groupby("duration_band", observed=False):
            duration_breakdown[str(label)] = {
                "count": int(len(group)),
                "sum_assured": round(float(group["sum_assured"].sum()), 2),
                "bel": round(float(group["bel"].sum()), 2),
            }

        summary = PortfolioSummary(
            total_policies=n_policies,
            total_sum_assured=round(float(faces.sum()), 2),
            total_pvfb=round(float(pvfb_per_policy.sum()), 2),
            total_pvfp=round(float(pvfp_per_policy.sum()), 2),
            total_pvfe=round(float(pvfe_per_policy.sum()), 2),
            total_bel=round(float(bel_per_policy.sum()), 2),
            annual_cash_flows=annual_cash_flows,
            product_breakdown=prod_breakdown,
            age_breakdown=age_breakdown,
            duration_breakdown=duration_breakdown,
        )

        return res_df, summary

    def _vectorized_lapse_lookup(self, durations_2d: np.ndarray) -> np.ndarray:
        """Look up lapse rates for a 2D array of 1-indexed policy durations."""
        rates = np.zeros_like(durations_2d, dtype=np.float64)
        if self.lapse.duration_rates:
            for dur_idx, rate in enumerate(self.lapse.duration_rates, start=1):
                rates = np.where(durations_2d == dur_idx, rate, rates)
            max_dur = len(self.lapse.duration_rates)
            rates = np.where(durations_2d > max_dur, self.lapse.flat_annual_rate, rates)
        else:
            rates.fill(self.lapse.flat_annual_rate)
        return rates

    @staticmethod
    def generate_synthetic_portfolio(n_policies: int = 1000, seed: int = 42) -> pd.DataFrame:
        """Generate a realistic synthetic life insurance portfolio DataFrame for benchmarking."""
        rng = np.random.default_rng(seed)

        product_types = rng.choice(
            ["term", "endowment", "whole_life", "pure_endowment"],
            size=n_policies,
            p=[0.50, 0.30, 0.15, 0.05],
        )
        issue_ages = rng.integers(20, 65, size=n_policies)
        terms = rng.choice([10, 15, 20, 25, 30], size=n_policies)
        durations = rng.integers(0, 8, size=n_policies)
        # Ensure duration < term
        durations = np.minimum(durations, terms - 1)

        sums_assured = rng.choice(
            [100_000, 250_000, 500_000, 1_000_000, 2_000_000],
            size=n_policies,
            p=[0.25, 0.35, 0.25, 0.10, 0.05],
        )

        # Approximate gross premium per thousand face amount based on age and term
        rates_per_k = (issue_ages / 10.0) * (20.0 / terms) * (1.5 if product_types[0] == "endowment" else 0.8)
        gross_premiums = np.round((sums_assured / 1000.0) * rates_per_k * rng.uniform(0.9, 1.1, size=n_policies), 2)
        gross_premiums = np.maximum(50.0, gross_premiums)

        genders = rng.choice(["M", "F"], size=n_policies)
        policy_ids = [f"POL-{i+1:06d}" for i in range(n_policies)]

        return pd.DataFrame({
            "policy_id": policy_ids,
            "product_type": product_types,
            "issue_age": issue_ages,
            "policy_duration_years": durations,
            "term_years": terms,
            "sum_assured": sums_assured,
            "gross_premium": gross_premiums,
            "gender": genders,
        })
