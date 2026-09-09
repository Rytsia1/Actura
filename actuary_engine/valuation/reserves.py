"""
Prospective and retrospective reserve computation.

Provides the ``ReserveCalculator`` class which computes net premium policy
reserves at any duration t for standard life insurance products using two
independent approaches:

1. **Prospective method** (ₜV_pro):
   ₜV = APV(future benefits) - APV(future premiums)
   Uses commutation functions evaluated at attained age x+t.

2. **Retrospective method** (ₜV_retro):
   ₜV = [APV(past premiums) - APV(past claims)] accumulated to time t
   Uses the accumulation factor 1/ₜEx = Dx / D_{x+t}.

Under **net premium valuation** (no expenses, no lapses), the prospective
and retrospective reserves are mathematically identical. The calculator
provides automated assertions to verify this invariant.

Reserve profiles are returned as structured pandas DataFrames suitable for
visualization (reserve waterfall charts, reserve trajectories).

Mathematical Reference:
- Term Life:      ₜV = (M_{x+t} - M_{x+n}) / D_{x+t}  -  P · (N_{x+t} - N_{x+n}) / D_{x+t}
- Endowment:      ₜV = (M_{x+t} - M_{x+n} + D_{x+n}) / D_{x+t}  -  P · (N_{x+t} - N_{x+n}) / D_{x+t}
- Whole Life:     ₜV = M_{x+t} / D_{x+t}  -  P · N_{x+t} / D_{x+t}
- Boundary:       ₀V = 0 (always), ₙV = 0 (term), ₙV = S (endowment)
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from actuary_engine.models.contracts import PolicyContract, ProductType
from actuary_engine.domain.tables.commutation import CommutationFunctions


class ReserveCalculator:
    """Net premium reserve calculator using commutation functions.

    Computes prospective and retrospective reserves for life insurance
    policies at arbitrary durations. Validates the fundamental identity
    ₜV_pro ≡ ₜV_retro under net premium assumptions.

    Attributes:
        commutation: Pre-computed commutation function table.
    """

    __slots__ = ("commutation",)

    def __init__(self, commutation: CommutationFunctions) -> None:
        """Initialize with a commutation function table.

        Args:
            commutation: Pre-computed CommutationFunctions instance.
        """
        self.commutation = commutation

    # ────────────────────────────────────────────────────────────
    # Core: Prospective Reserve at duration t
    # ────────────────────────────────────────────────────────────

    def prospective_reserve(
        self,
        x: int,
        t: int,
        n: Optional[int],
        annual_premium: float,
        face: float = 1.0,
        product_type: ProductType = ProductType.TERM,
    ) -> float:
        """Compute net premium prospective reserve ₜV at duration t.

        ₜV = APV(future benefits @ x+t) - APV(future premiums @ x+t)

        For term insurance (n-year):
            ₜV = face · A¹_{x+t:n-t} - P · ä_{x+t:n-t}

        For endowment insurance (n-year):
            ₜV = face · A_{x+t:n-t} - P · ä_{x+t:n-t}

        For whole life:
            ₜV = face · A_{x+t} - P · ä_{x+t}

        Args:
            x: Issue age.
            t: Duration (policy year, 0-indexed; t=0 is at issue).
            n: Coverage term (None for whole life).
            annual_premium: Annual net level premium.
            face: Face amount (sum assured).
            product_type: Product type for benefit structure.

        Returns:
            Net premium reserve at duration t.

        Raises:
            ValueError: If t < 0 or t > n (for finite-term products).
        """
        self._validate_duration(t, n, x)
        comm = self.commutation

        if n is not None and t == n:
            # Terminal reserve
            if product_type == ProductType.ENDOWMENT:
                return face  # Maturity benefit payable
            else:
                return 0.0  # Term ends, no further liability

        if t == 0:
            return 0.0  # At issue, reserve is zero under net premium valuation

        attained_age = x + t

        if product_type == ProductType.WHOLE_LIFE:
            # APV future benefits = face · A_{x+t}
            apv_benefits = face * comm.whole_life_insurance(attained_age)
            # APV future premiums = P · ä_{x+t}
            apv_premiums = annual_premium * comm.whole_life_annuity_due(attained_age)

        elif product_type == ProductType.TERM:
            assert n is not None
            remaining = n - t
            # APV future benefits = face · A¹_{x+t:n-t}
            apv_benefits = face * comm.term_insurance(attained_age, remaining)
            # APV future premiums = P · ä_{x+t:n-t}
            apv_premiums = annual_premium * comm.temp_annuity_due(attained_age, remaining)

        elif product_type == ProductType.ENDOWMENT:
            assert n is not None
            remaining = n - t
            # APV future benefits = face · A_{x+t:n-t}
            apv_benefits = face * comm.endowment_insurance(attained_age, remaining)
            # APV future premiums = P · ä_{x+t:n-t}
            apv_premiums = annual_premium * comm.temp_annuity_due(attained_age, remaining)

        elif product_type == ProductType.PURE_ENDOWMENT:
            assert n is not None
            remaining = n - t
            # APV future benefits = face · ₙ₋ₜE_{x+t}
            apv_benefits = face * comm.pure_endowment(attained_age, remaining)
            # APV future premiums = P · ä_{x+t:n-t}
            apv_premiums = annual_premium * comm.temp_annuity_due(attained_age, remaining)

        else:
            raise ValueError(f"Unsupported product type: {product_type}")

        return apv_benefits - apv_premiums

    # ────────────────────────────────────────────────────────────
    # Core: Retrospective Reserve at duration t
    # ────────────────────────────────────────────────────────────

    def retrospective_reserve(
        self,
        x: int,
        t: int,
        n: Optional[int],
        annual_premium: float,
        face: float = 1.0,
        product_type: ProductType = ProductType.TERM,
    ) -> float:
        """Compute net premium retrospective reserve ₜV_retro at duration t.

        ₜV_retro = [APV_0(past premiums) - APV_0(past benefits)] / ₜEx
                 = [P · ä_{x:t} - face · (cost of past insurance)] · Dx / D_{x+t}

        The accumulation factor 1/ₜEx = Dx / D_{x+t} "rolls up" past
        present values to current-duration values.

        For term insurance:
            Past benefit cost = face · A¹_{x:t} = face · (Mx - M_{x+t}) / Dx

        For endowment insurance (no maturity has occurred yet for t < n):
            Past benefit cost = face · A¹_{x:t} = face · (Mx - M_{x+t}) / Dx

        For whole life:
            Past benefit cost = face · A¹_{x:t} (term component over [0, t])

        Args:
            x: Issue age.
            t: Duration (policy year).
            n: Coverage term (None for whole life).
            annual_premium: Annual net level premium.
            face: Face amount.
            product_type: Product type.

        Returns:
            Retrospective net premium reserve at duration t.
        """
        self._validate_duration(t, n, x)
        comm = self.commutation

        if t == 0:
            return 0.0

        if n is not None and t == n:
            if product_type == ProductType.ENDOWMENT:
                return face
            else:
                return 0.0

        # Accumulation factor: Dx / D_{x+t}
        accum = comm.get_Dx(x) / comm.get_Dx(x + t)

        # APV_0 of past premiums: P · ä_{x:t} = P · (Nx - N_{x+t}) / Dx
        apv_past_premiums = annual_premium * comm.temp_annuity_due(x, t)

        # APV_0 of past benefits: death claims from age x to x+t
        # Pure endowment has NO death benefit, so past claims = 0
        if product_type == ProductType.PURE_ENDOWMENT:
            apv_past_benefits = 0.0
        else:
            # For term, endowment, whole life: past death claims
            # (no maturity payment has occurred yet if t < n)
            apv_past_benefits = face * comm.term_insurance(x, t)

        # Retrospective: accumulate the net to duration t
        reserve = (apv_past_premiums - apv_past_benefits) * accum

        return reserve

    # ────────────────────────────────────────────────────────────
    # Reserve Profile: Full trajectory over policy lifetime
    # ────────────────────────────────────────────────────────────

    def reserve_profile(
        self,
        contract: PolicyContract,
        annual_premium: float,
        method: str = "prospective",
    ) -> pd.DataFrame:
        """Compute reserve trajectory over the entire policy lifetime.

        Returns a DataFrame with one row per duration t = 0, 1, ..., n
        containing the reserve value and related quantities.

        Args:
            contract: Policy contract specification.
            annual_premium: Annual net level premium.
            method: 'prospective', 'retrospective', or 'both'.

        Returns:
            DataFrame with columns:
            - duration: Policy year t (0 to n).
            - age: Attained age x + t.
            - reserve_prospective: ₜV (prospective), if requested.
            - reserve_retrospective: ₜV (retrospective), if requested.
        """
        contract.validate_against_table(self.commutation.table)

        x = contract.issue_age
        n = contract.term
        face = contract.sum_assured
        ptype = contract.product_type

        # Determine max duration
        if n is not None:
            max_t = n
        else:
            # Whole life: compute up to omega - x
            max_t = self.commutation.table.omega - x

        durations = np.arange(max_t + 1, dtype=np.int64)
        ages = x + durations

        data: dict[str, list[float] | np.ndarray] = {
            "duration": durations,
            "age": ages,
        }

        if method in ("prospective", "both"):
            reserves_pro = np.array([
                self.prospective_reserve(x, int(t), n, annual_premium, face, ptype)
                for t in durations
            ])
            data["reserve_prospective"] = reserves_pro

        if method in ("retrospective", "both"):
            reserves_retro = np.array([
                self.retrospective_reserve(x, int(t), n, annual_premium, face, ptype)
                for t in durations
            ])
            data["reserve_retrospective"] = reserves_retro

        return pd.DataFrame(data)

    # ────────────────────────────────────────────────────────────
    # Validation: Prospective ≡ Retrospective
    # ────────────────────────────────────────────────────────────

    def validate_prospective_equals_retrospective(
        self,
        contract: PolicyContract,
        annual_premium: float,
        tolerance: float = 1e-6,
    ) -> tuple[bool, pd.DataFrame]:
        """Validate that ₜV_pro ≡ ₜV_retro for all durations.

        Under net premium valuation (no expenses, no lapses), the
        prospective and retrospective methods must produce identical
        reserves. This is a fundamental actuarial identity.

        Args:
            contract: Policy contract.
            annual_premium: Net annual level premium.
            tolerance: Maximum acceptable absolute difference.

        Returns:
            Tuple of (all_match, comparison_df) where comparison_df
            has columns: duration, reserve_prospective, reserve_retrospective,
            absolute_difference.
        """
        df = self.reserve_profile(contract, annual_premium, method="both")

        df["absolute_difference"] = np.abs(
            df["reserve_prospective"] - df["reserve_retrospective"]
        )

        all_match = bool((df["absolute_difference"] < tolerance).all())

        return all_match, df

    # ────────────────────────────────────────────────────────────
    # Recurrence relation: ₜ₊₁V = (ₜV + P) · (1+i) - q_{x+t} · (S - ₜ₊₁V)
    # ────────────────────────────────────────────────────────────

    def reserve_by_recurrence(
        self,
        contract: PolicyContract,
        annual_premium: float,
    ) -> pd.DataFrame:
        """Compute reserves using the recursive Fackler formula.

        The recurrence relation for net premium reserves:
            (ₜV + P) · (1 + i) = q_{x+t} · S + p_{x+t} · ₜ₊₁V

        Rearranged (forward recursion):
            ₜ₊₁V = [(ₜV + Pₜ) · (1 + i) - q_{x+t} · S] / p_{x+t}

        where Pₜ = P if t < h (premium-paying period), else 0.

        This provides an independent computation method that avoids
        commutation functions entirely.

        For endowment: S includes both death benefit and maturity benefit.
        For term: S is the death benefit only.

        Args:
            contract: Policy contract specification.
            annual_premium: Annual net level premium.

        Returns:
            DataFrame with columns: duration, age, reserve_recurrence.
        """
        x = contract.issue_age
        n = contract.term
        face = contract.sum_assured
        i = self.commutation.interest.annual_rate
        table = self.commutation.table
        ptype = contract.product_type

        h = contract.effective_premium_term
        if n is not None:
            max_t = n
        else:
            max_t = table.omega - x

        if h is None:
            h = max_t

        reserves = np.zeros(max_t + 1, dtype=np.float64)
        # ₀V = 0
        reserves[0] = 0.0

        # Terminal condition for backward check (not used in forward)
        # Forward: start from ₀V and compute forward

        for t in range(max_t):
            # Premium at time t
            P_t = annual_premium if t < h else 0.0

            # Mortality at attained age
            qx_t = table.get_qx(x + t)
            px_t = 1.0 - qx_t

            # Net amount at risk
            if ptype == ProductType.ENDOWMENT and t == max_t - 1:
                # Last year of endowment: death benefit AND maturity benefit = face
                # (ₜV + P)(1+i) = q · face + p · face
                # ₙV = face regardless (maturity)
                reserves[t + 1] = ((reserves[t] + P_t) * (1.0 + i) - qx_t * face) / px_t
            elif ptype == ProductType.PURE_ENDOWMENT and t == max_t - 1:
                # Pure endowment: no death benefit, maturity = face
                reserves[t + 1] = ((reserves[t] + P_t) * (1.0 + i)) / px_t
            elif ptype == ProductType.PURE_ENDOWMENT:
                # Pure endowment intermediate: no death benefit
                reserves[t + 1] = ((reserves[t] + P_t) * (1.0 + i)) / px_t
            else:
                # Standard: death benefit = face
                reserves[t + 1] = ((reserves[t] + P_t) * (1.0 + i) - qx_t * face) / px_t

        durations = np.arange(max_t + 1, dtype=np.int64)
        return pd.DataFrame({
            "duration": durations,
            "age": x + durations,
            "reserve_recurrence": reserves,
        })

    # ────────────────────────────────────────────────────────────
    # Contract-level convenience methods
    # ────────────────────────────────────────────────────────────

    def reserve_at(
        self,
        contract: PolicyContract,
        annual_premium: float,
        t: int,
        method: str = "prospective",
    ) -> float:
        """Compute reserve at a specific duration for a contract.

        Args:
            contract: Policy contract.
            annual_premium: Annual net level premium.
            t: Duration.
            method: 'prospective' or 'retrospective'.

        Returns:
            Reserve value at duration t.
        """
        x = contract.issue_age
        n = contract.term
        face = contract.sum_assured
        ptype = contract.product_type

        if method == "prospective":
            return self.prospective_reserve(x, t, n, annual_premium, face, ptype)
        elif method == "retrospective":
            return self.retrospective_reserve(x, t, n, annual_premium, face, ptype)
        else:
            raise ValueError(f"Method must be 'prospective' or 'retrospective', got '{method}'.")

    # ────────────────────────────────────────────────────────────
    # Validation helpers
    # ────────────────────────────────────────────────────────────

    def _validate_duration(self, t: int, n: Optional[int], x: Optional[int] = None) -> None:
        """Validate duration is within valid range and table bounds.

        Args:
            t: Duration.
            n: Coverage term (None for whole life).
            x: Optional issue age.

        Raises:
            ValueError: If t is out of range or exceeds mortality table bounds.
        """
        if t < 0:
            raise ValueError(f"Duration t must be non-negative. Got {t}.")
        if n is not None and t > n:
            raise ValueError(
                f"Duration t = {t} exceeds coverage term n = {n}."
            )
        if x is not None and x + t > self.commutation._max_age:
            raise ValueError(
                f"Duration t = {t} from issue age {x} (attained age {x + t}) "
                f"exceeds mortality table maximum age {self.commutation._max_age} ({self.commutation.table.name})."
            )

    def __repr__(self) -> str:
        return f"ReserveCalculator(commutation={self.commutation!r})"
