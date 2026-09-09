"""
Deterministic cash flow projection engine.

Provides the ``CashFlowProjector`` class which generates year-by-year
expected cash flow projections for a single life insurance policy under
deterministic assumptions. Outputs a pandas DataFrame with columns for
survivors, deaths, premium income, death benefits, maturity benefits,
net cash flow, and present value of net cash flow.

The projector validates the equivalence principle by checking that the
sum of PV(net cash flows) ≈ 0 for a correctly priced policy.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from actuary_engine.models.assumptions import InterestAssumption
from actuary_engine.models.contracts import PolicyContract, ProductType
from actuary_engine.domain.tables.mortality_table import MortalityTable


class CashFlowProjector:
    """Deterministic expected cash flow projector for life insurance.

    Projects year-by-year expected cash flows for a single policy,
    including premium income (beginning-of-year) and benefit outgo
    (end-of-year for death, maturity at term end).

    Cash flows are computed on an expected (probability-weighted) basis
    per unit of the initial cohort.

    Attributes:
        table: Mortality table.
        interest: Interest rate assumption.
    """

    __slots__ = ("table", "interest")

    def __init__(
        self,
        table: MortalityTable,
        interest: InterestAssumption,
    ) -> None:
        """Initialize projector with mortality and interest assumptions.

        Args:
            table: A parsed MortalityTable.
            interest: Interest rate assumption.
        """
        self.table = table
        self.interest = interest

    def project(
        self,
        contract: PolicyContract,
        annual_premium: float,
        projection_years: Optional[int] = None,
    ) -> pd.DataFrame:
        """Project expected cash flows for a policy.

        Generates a DataFrame with one row per policy year containing:
        - year: Policy year (0-indexed, year 0 = issue year)
        - age: Attained age at beginning of year
        - survivors: Expected proportion of original cohort alive at BOY
        - deaths: Expected proportion dying during the year
        - premium_income: Annual premium × survivors (BOY payment)
        - death_benefit: Sum assured × deaths (EOY payment)
        - maturity_benefit: Sum assured × survivors at maturity (endowment only)
        - net_cash_flow: premium_income - death_benefit - maturity_benefit
        - discount_factor: v^t for the year
        - pv_net_cash_flow: net_cash_flow × discount_factor

        Args:
            contract: Policy contract specification.
            annual_premium: Annual level premium amount.
            projection_years: Number of years to project. Defaults to
                the coverage term (or ω - x for whole life).

        Returns:
            DataFrame with projected cash flows.
        """
        contract.validate_against_table(self.table)

        x = contract.issue_age
        face = contract.sum_assured
        v = self.interest.discount_factor

        # Determine projection horizon
        if projection_years is not None:
            if projection_years <= 0:
                raise ValueError(f"projection_years must be positive. Got {projection_years}.")
            if x + projection_years > self.table.max_age:
                raise ValueError(
                    f"Projection horizon {x} + {projection_years} = {x + projection_years} "
                    f"exceeds mortality table maximum age {self.table.max_age} ({self.table.name})."
                )
            n = projection_years
        elif contract.term is not None:
            n = contract.term
        else:
            # Whole life: project to omega
            n = self.table.omega - x

        # Premium paying term
        h = contract.effective_premium_term
        if h is None:
            h = n  # Pay for the full projection period

        # ────────────────────────────────────────────────────────
        # Vectorized computation of all cash flow components
        # ────────────────────────────────────────────────────────

        years = np.arange(n, dtype=np.int64)
        ages = x + years

        # Survival probabilities: ₜpₓ for t = 0, 1, ..., n-1 (BOY survivors)
        tpx_boy = self.table.tpx_vector(x, n)  # length n+1: t=0..n

        # BOY survivors (proportion alive at start of each year)
        survivors = tpx_boy[:n]  # t = 0, 1, ..., n-1

        # Deaths during each year: ₜpₓ · qₓ₊ₜ
        x_idx = x - self.table.min_age
        qx_during = self.table.qx[x_idx : x_idx + n]
        deaths = survivors * qx_during

        # Premium income (BOY): P × survivors, but only during premium-paying period
        premium_mask = (years < h).astype(np.float64)
        premium_income = annual_premium * survivors * premium_mask

        # Death benefit (EOY): face × deaths — but NOT for pure endowment
        if contract.product_type == ProductType.PURE_ENDOWMENT:
            death_benefit = np.zeros(n, dtype=np.float64)
        else:
            death_benefit = face * deaths

        # Maturity benefit: only for endowment/pure endowment at year n
        maturity_benefit = np.zeros(n, dtype=np.float64)
        if contract.product_type in (ProductType.ENDOWMENT, ProductType.PURE_ENDOWMENT):
            if contract.term is not None and n >= contract.term:
                # Maturity benefit paid at end of year n (= beginning of year n+1)
                # to survivors at that point: ₙpₓ
                # We attribute this to the last year
                maturity_benefit[contract.term - 1] = face * tpx_boy[contract.term]

        # Net cash flow: premiums in - benefits out
        net_cf = premium_income - death_benefit - maturity_benefit

        # Discount factors: v^(t+0.5) for mid-year approx or v^t for BOY premium
        # We use standard convention:
        #   - Premium at BOY: discount by v^t
        #   - Death benefit at EOY: discount by v^(t+1)
        #   - Maturity at end of term: discount by v^n
        # For the net CF, we discount premium by v^t and benefits by v^(t+1)
        discount_prem = v ** years
        discount_benefit = v ** (years + 1)

        pv_premium = premium_income * discount_prem
        pv_death = death_benefit * discount_benefit
        pv_maturity = np.zeros(n, dtype=np.float64)
        if contract.product_type in (ProductType.ENDOWMENT, ProductType.PURE_ENDOWMENT):
            if contract.term is not None and n >= contract.term:
                t_mat = contract.term
                pv_maturity[t_mat - 1] = maturity_benefit[t_mat - 1] * (v ** t_mat)

        pv_net_cf = pv_premium - pv_death - pv_maturity

        # ────────────────────────────────────────────────────────
        # Build DataFrame
        # ────────────────────────────────────────────────────────

        df = pd.DataFrame(
            {
                "year": years,
                "age": ages,
                "survivors": survivors,
                "deaths": deaths,
                "premium_income": premium_income,
                "death_benefit": death_benefit,
                "maturity_benefit": maturity_benefit,
                "net_cash_flow": net_cf,
                "pv_premium": pv_premium,
                "pv_death_benefit": pv_death,
                "pv_maturity_benefit": pv_maturity,
                "pv_net_cash_flow": pv_net_cf,
            }
        )

        return df

    def validate_equivalence(
        self,
        contract: PolicyContract,
        annual_premium: float,
        tolerance: float = 1e-6,
    ) -> tuple[bool, float]:
        """Validate the equivalence principle for a priced policy.

        Checks that Σ PV(net cash flows) ≈ 0, which must hold when
        the annual premium is correctly computed via the equivalence
        principle.

        Args:
            contract: Policy contract.
            annual_premium: The annual premium to validate.
            tolerance: Acceptable absolute deviation from zero.

        Returns:
            Tuple of (is_valid, pv_sum) where is_valid is True if
            |pv_sum| < tolerance.
        """
        df = self.project(contract, annual_premium)
        pv_sum = float(df["pv_net_cash_flow"].sum())
        return abs(pv_sum) < tolerance, pv_sum

    def __repr__(self) -> str:
        return (
            f"CashFlowProjector(table='{self.table.name}', "
            f"i={self.interest.annual_rate:.4%})"
        )
