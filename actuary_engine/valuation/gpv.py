"""
Gross Premium Valuation (GPV) and Best Estimate Liability (BEL) engine.

Provides the ``GrossPremiumValuation`` class which computes policy liabilities
under realistic assumptions including:

- **Acquisition expenses (alpha):** First-year percentage-of-premium loading
- **Maintenance expenses (beta):** Renewal percentage-of-premium loading
- **Per-policy expenses (gamma):** Flat per-policy expenses (first-year and renewal)
- **Lapse/surrender decrements (wₜ):** Duration-dependent policyholder behavior

The GPV produces a full multi-decrement cash flow rollout where the in-force
population is projected under three decrements: death, lapse, and survival.

Key outputs:
- **Best Estimate Liability (BEL):** PV of future benefits + expenses - premiums
- **Gross premium reserve profile:** Duration-by-duration liability trajectory
- **Cash flow waterfall DataFrame:** Detailed year-by-year breakdown

Mathematical Framework:
    BEL = Σₜ vᵗ⁺¹ [ qₓ₊ₜ · (1 - wₜ/2) · S + wₜ · (1 - qₓ₊ₜ/2) · CVₜ ]
        + Σₜ vᵗ [ βₜ · Pₜ + γₜ ] · ₜpₓᵃᵖ
        - Σₜ vᵗ · Pₜ · ₜpₓᵃᵖ

where ₜpₓᵃᵖ = "all-peril" survival (mortality + lapses combined).
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from actuary_engine.models.assumptions import (
    ExpenseAssumption,
    InterestAssumption,
    LapseAssumption,
)
from actuary_engine.models.contracts import PolicyContract, ProductType
from actuary_engine.domain.tables.mortality_table import MortalityTable
from actuary_engine.valuation._kernels import _rollback_gpv_kernel


class GrossPremiumValuation:
    """Gross premium valuation engine with multi-decrement projections.

    Projects cash flows under realistic assumptions including expenses
    and policyholder lapse behavior, producing BEL (Best Estimate Liability)
    and gross premium reserve profiles.

    Attributes:
        table: Mortality table.
        interest: Interest rate assumption.
        expense: Expense loading assumptions.
        lapse: Lapse/surrender assumptions.
    """

    __slots__ = ("table", "interest", "expense", "lapse")

    def __init__(
        self,
        table: MortalityTable,
        interest: InterestAssumption,
        expense: Optional[ExpenseAssumption] = None,
        lapse: Optional[LapseAssumption] = None,
    ) -> None:
        """Initialize GPV engine.

        Args:
            table: A parsed MortalityTable.
            interest: Interest rate assumption.
            expense: Expense loading (default: no expenses).
            lapse: Lapse/surrender rates (default: no lapses).
        """
        self.table = table
        self.interest = interest
        self.expense = expense or ExpenseAssumption()
        self.lapse = lapse or LapseAssumption()

    def project(
        self,
        contract: PolicyContract,
        gross_premium: float,
        surrender_values: Optional[np.ndarray] = None,
    ) -> pd.DataFrame:
        """Project gross premium cash flows under multi-decrement assumptions.

        Produces a year-by-year DataFrame with columns for:
        - In-force population under combined mortality + lapse decrements
        - Expected death claims, lapse payouts, maturity benefits
        - Expense cash flows (acquisition, maintenance, per-policy)
        - Premium income
        - Net liability cash flow and its present value

        The "independent rates" approach is used for combining decrements:
            Dependent death rate:  qₓ₊ₜᵈ = qₓ₊ₜ · (1 - wₜ/2)
            Dependent lapse rate:  wₜᵈ   = wₜ   · (1 - qₓ₊ₜ/2)
            ₜpₓᵃᵖ (all-peril survival) = ∏ (1 - qₖᵈ - wₖᵈ)

        Args:
            contract: Policy contract specification.
            gross_premium: Annual gross premium.
            surrender_values: Optional array of surrender values by duration
                (length = n). Defaults to zero (no surrender value).

        Returns:
            DataFrame with detailed cash flow projections.
        """
        contract.validate_against_table(self.table)

        x = contract.issue_age
        face = contract.sum_assured
        v = self.interest.discount_factor
        ptype = contract.product_type

        # Projection horizon
        n = contract.term
        if n is None:
            n = self.table.omega - x
        max_t = n

        # Premium paying term
        h = contract.effective_premium_term
        if h is None:
            h = max_t

        # Surrender values (default: zero)
        if surrender_values is not None:
            cv = np.asarray(surrender_values, dtype=np.float64)
            if len(cv) < max_t:
                cv = np.pad(cv, (0, max_t - len(cv)), constant_values=0.0)
        else:
            cv = np.zeros(max_t, dtype=np.float64)

        # ────────────────────────────────────────────────────────
        # Build decrement arrays
        # ────────────────────────────────────────────────────────

        years = np.arange(max_t, dtype=np.int64)
        ages = x + years

        # Independent mortality rates
        x_idx = x - self.table.min_age
        qx_indep = self.table.qx[x_idx: x_idx + max_t].copy()

        # Independent lapse rates
        wx_indep = np.array(
            [self.lapse.get_rate(int(t) + 1) for t in years],
            dtype=np.float64,
        )

        # Dependent rates (UDD approximation for double decrement)
        qx_dep = qx_indep * (1.0 - wx_indep / 2.0)
        wx_dep = wx_indep * (1.0 - qx_indep / 2.0)

        # All-peril survival: ₜpₓᵃᵖ (in-force at BOY of each year)
        survival_factor = 1.0 - qx_dep - wx_dep
        inforce_boy = np.empty(max_t, dtype=np.float64)
        inforce_boy[0] = 1.0
        for t in range(1, max_t):
            inforce_boy[t] = inforce_boy[t - 1] * survival_factor[t - 1]

        # ────────────────────────────────────────────────────────
        # Cash flow components
        # ────────────────────────────────────────────────────────

        # Deaths during each year (EOY)
        deaths = inforce_boy * qx_dep
        death_claims = np.zeros(max_t, dtype=np.float64)
        if ptype != ProductType.PURE_ENDOWMENT:
            death_claims = face * deaths

        # Lapses during each year
        lapses = inforce_boy * wx_dep
        lapse_payouts = cv * lapses  # Surrender value × lapse count

        # Maturity benefit at end of term
        maturity_benefit = np.zeros(max_t, dtype=np.float64)
        if ptype in (ProductType.ENDOWMENT, ProductType.PURE_ENDOWMENT):
            # Survivors at end of last year
            survivors_at_maturity = inforce_boy[max_t - 1] * survival_factor[max_t - 1]
            maturity_benefit[max_t - 1] = face * survivors_at_maturity

        # Premium income (BOY, only during premium-paying period)
        premium_mask = (years < h).astype(np.float64)
        premium_income = gross_premium * inforce_boy * premium_mask

        # ────────────────────────────────────────────────────────
        # Expense cash flows
        # ────────────────────────────────────────────────────────

        exp = self.expense

        # Percentage-of-premium expenses
        pct_expense_rate = np.where(
            years == 0,
            exp.percent_of_premium_first,
            exp.percent_of_premium_renewal,
        )
        pct_expense = premium_income * pct_expense_rate

        # Per-policy expenses
        per_policy_rate = np.where(
            years == 0,
            exp.per_policy_first,
            exp.per_policy_renewal,
        )
        per_policy_expense = inforce_boy * per_policy_rate

        total_expense = pct_expense + per_policy_expense

        # ────────────────────────────────────────────────────────
        # Net liability cash flow
        # ────────────────────────────────────────────────────────

        # Outgo: benefits + expenses
        total_outgo = death_claims + lapse_payouts + maturity_benefit + total_expense

        # Net CF from insurer perspective: outgo - premium income
        # Positive = liability (insurer must pay more than it receives)
        net_liability_cf = total_outgo - premium_income

        # Present values
        discount_boy = v ** years        # BOY discounting
        discount_eoy = v ** (years + 1)  # EOY discounting

        # Benefits are EOY, premiums and expenses are BOY
        pv_premium = premium_income * discount_boy
        pv_death_claims = death_claims * discount_eoy
        pv_lapse_payouts = lapse_payouts * discount_eoy
        pv_maturity = maturity_benefit * discount_eoy
        pv_expense = total_expense * discount_boy
        pv_net_liability = (
            pv_death_claims + pv_lapse_payouts + pv_maturity + pv_expense - pv_premium
        )

        # ────────────────────────────────────────────────────────
        # Build DataFrame
        # ────────────────────────────────────────────────────────

        return pd.DataFrame({
            "year": years,
            "age": ages,
            "inforce_boy": inforce_boy,
            "qx_independent": qx_indep,
            "wx_independent": wx_indep,
            "qx_dependent": qx_dep,
            "wx_dependent": wx_dep,
            "deaths": deaths,
            "lapses": lapses,
            "death_claims": death_claims,
            "lapse_payouts": lapse_payouts,
            "maturity_benefit": maturity_benefit,
            "premium_income": premium_income,
            "pct_expense": pct_expense,
            "per_policy_expense": per_policy_expense,
            "total_expense": total_expense,
            "total_outgo": total_outgo,
            "net_liability_cf": net_liability_cf,
            "pv_premium": pv_premium,
            "pv_death_claims": pv_death_claims,
            "pv_lapse_payouts": pv_lapse_payouts,
            "pv_maturity": pv_maturity,
            "pv_expense": pv_expense,
            "pv_net_liability": pv_net_liability,
        })

    def best_estimate_liability(
        self,
        contract: PolicyContract,
        gross_premium: float,
        surrender_values: Optional[np.ndarray] = None,
    ) -> float:
        """Compute the Best Estimate Liability (BEL).

        BEL = Σ PV(net liability cash flows)
            = PV(benefits + expenses) - PV(premiums)

        A positive BEL means the insurer holds an unfunded liability;
        a negative BEL means premiums exceed expected obligations (profit).

        Args:
            contract: Policy contract.
            gross_premium: Annual gross premium.
            surrender_values: Optional surrender value schedule.

        Returns:
            Best Estimate Liability.
        """
        df = self.project(contract, gross_premium, surrender_values)
        return float(df["pv_net_liability"].sum())

    def gross_reserve_profile(
        self,
        contract: PolicyContract,
        gross_premium: float,
        surrender_values: Optional[np.ndarray] = None,
    ) -> pd.DataFrame:
        """Compute gross premium reserve trajectory.

        The gross premium reserve at duration t is the BEL of the remaining
        future cash flows, computed by truncating the projection to start
        at duration t.

        For efficiency, this computes reserves as the reverse-cumulative
        sum of PV net liability flows, re-accumulated to each duration.

        Args:
            contract: Policy contract.
            gross_premium: Annual gross premium.
            surrender_values: Optional surrender value schedule.

        Returns:
            DataFrame with columns: duration, age, gross_reserve.
        """
        df = self.project(contract, gross_premium, surrender_values)
        v = self.interest.discount_factor
        n = len(df)

        # Gross reserve at each duration t:
        # ₜV_gross = Σ_{k=t}^{n-1} PV_{t}(net liability CF at k)
        # = Σ_{k=t}^{n-1} net_liability_cf[k] · v^{k-t} (re-discount to time t)
        #
        # Efficient: compute reverse cumsum of PV flows, then re-accumulate

        pv_net = df["pv_net_liability"].values

        # Reserve at time t = (Σ_{k≥t} PV_0(net_liability[k])) / v^t
        # = (Σ_{k≥t} PV_0(net_liability[k])) · (1+i)^t
        reverse_cumsum = np.cumsum(pv_net[::-1])[::-1]
        # Prepend the total BEL and compute at each BOY
        # Reserve at t=0 is the full BEL
        # Reserve at t=n is 0 (or face for endowment maturity, but that's captured)

        i_rate = self.interest.annual_rate
        accumulation = (1.0 + i_rate) ** np.arange(n)

        gross_reserves_during = reverse_cumsum * accumulation

        # Add terminal reserve (t = n)
        x = contract.issue_age
        durations = np.arange(n + 1, dtype=np.int64)
        ages = x + durations

        gross_reserves = np.empty(n + 1, dtype=np.float64)
        gross_reserves[:n] = gross_reserves_during
        gross_reserves[n] = 0.0  # Terminal (after all CFs settled)

        return pd.DataFrame({
            "duration": durations,
            "age": ages,
            "gross_reserve": gross_reserves,
        })

    def rollback_reserve_profile(
        self,
        contract: PolicyContract,
        gross_premium: float,
        surrender_values: Optional[np.ndarray] = None,
    ) -> pd.DataFrame:
        """Compute gross premium reserve trajectory using JIT-compiled backward induction.

        Uses ``_rollback_gpv_kernel`` to eliminate Python loop overhead via C-speed JIT execution.

        Args:
            contract: Policy contract.
            gross_premium: Annual gross premium.
            surrender_values: Optional surrender value schedule.

        Returns:
            DataFrame with columns: duration, age, gross_reserve.
        """
        df = self.project(contract, gross_premium, surrender_values)
        v = self.interest.discount_factor
        n = len(df)

        safe_death_claims = np.asarray(df["death_claims"].to_numpy(dtype=np.float64), dtype=np.float64)
        safe_lapse_payouts = np.asarray(df["lapse_payouts"].to_numpy(dtype=np.float64), dtype=np.float64)
        safe_maturity_benefits = np.asarray(df["maturity_benefit"].to_numpy(dtype=np.float64), dtype=np.float64)
        safe_expenses = np.asarray(df["total_expense"].to_numpy(dtype=np.float64), dtype=np.float64)
        safe_premiums = np.asarray(df["premium_income"].to_numpy(dtype=np.float64), dtype=np.float64)
        safe_qx_dep = np.asarray(df["qx_dependent"].to_numpy(dtype=np.float64), dtype=np.float64)
        safe_wx_dep = np.asarray(df["wx_dependent"].to_numpy(dtype=np.float64), dtype=np.float64)

        # JIT kernel rollback backward induction
        reserves = _rollback_gpv_kernel(
            death_claims=safe_death_claims,
            lapse_payouts=safe_lapse_payouts,
            maturity_benefits=safe_maturity_benefits,
            expenses=safe_expenses,
            premiums=safe_premiums,
            qx_dep=safe_qx_dep,
            wx_dep=safe_wx_dep,
            discount_v=float(v),
            max_t=int(n),
        )

        x = contract.issue_age
        durations = np.arange(n + 1, dtype=np.int64)
        ages = x + durations

        return pd.DataFrame({
            "duration": durations,
            "age": ages,
            "gross_reserve": reserves,
        })

    def __repr__(self) -> str:
        return (
            f"GrossPremiumValuation(table='{self.table.name}', "
            f"i={self.interest.annual_rate:.4%}, "
            f"expense={self.expense!r}, lapse={self.lapse!r})"
        )
