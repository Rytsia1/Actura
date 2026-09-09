"""
Commutation function computation.

Provides the ``CommutationFunctions`` class which computes the classical
actuarial commutation columns (Dx, Nx, Cx, Mx) from a mortality table
and interest rate assumption. All computations use vectorized NumPy
operations — in particular, the cumulative sums Nx and Mx are computed
via reverse cumsum for O(n) efficiency.

These commutation values are the building blocks for pricing life insurance
products (Ax), life annuities (äx), and level premiums via the equivalence
principle.
"""

from __future__ import annotations

import numpy as np

from actuary_engine.models.assumptions import InterestAssumption
from actuary_engine.domain.tables.mortality_table import MortalityTable


class CommutationFunctions:
    """Vectorized commutation function table.

    Computes and stores the four standard commutation columns on
    initialization:

    - Dx = v^x · lx       (discounted survivors)
    - Cx = v^(x+1) · dx   (discounted deaths)
    - Nx = Σ Dk for k ≥ x (reverse cumulative sum of Dx)
    - Mx = Σ Ck for k ≥ x (reverse cumulative sum of Cx)

    All arrays are indexed relative to the mortality table's minimum age.

    Attributes:
        table: Source mortality table.
        interest: Interest rate assumption.
        Dx: Discounted survivors array.
        Cx: Discounted deaths array.
        Nx: Cumulative Dx array (from right).
        Mx: Cumulative Cx array (from right).
    """

    __slots__ = ("table", "interest", "Dx", "Cx", "Nx", "Mx", "_min_age", "_max_age")

    def __init__(self, table: MortalityTable, interest: InterestAssumption) -> None:
        """Initialize commutation functions from a mortality table and interest rate.

        All four commutation columns are computed eagerly on construction
        using fully vectorized NumPy operations.

        Args:
            table: A parsed MortalityTable instance.
            interest: An InterestAssumption with the annual effective rate.
        """
        self.table = table
        self.interest = interest
        self._min_age = table.min_age
        self._max_age = table.max_age

        v = interest.discount_factor
        ages = table.ages.astype(np.float64)

        # Dx = v^x · lx  (indexed 0..num_ages-1, maps to min_age..max_age)
        # Note: lx has num_ages+1 elements; we use lx[0:num_ages] for ages min_age..max_age
        lx = table.lx[:-1]  # lx at ages min_age through max_age
        self.Dx = (v ** ages) * lx

        # Cx = v^(x+1) · dx  (indexed 0..num_ages-1)
        self.Cx = (v ** (ages + 1.0)) * table.dx

        # Nx = Σ_{k=x}^{ω} D_k  — computed via reverse cumulative sum
        self.Nx = np.cumsum(self.Dx[::-1])[::-1].copy()

        # Mx = Σ_{k=x}^{ω} C_k  — computed via reverse cumulative sum
        self.Mx = np.cumsum(self.Cx[::-1])[::-1].copy()

    def _idx(self, age: int) -> int:
        """Convert absolute age to array index.

        Args:
            age: Absolute age.

        Returns:
            Array index.

        Raises:
            ValueError: If age is out of range.
        """
        idx = age - self._min_age
        if idx < 0 or idx >= len(self.Dx):
            raise ValueError(
                f"Age {age} is out of range [{self._min_age}, {self._max_age}]."
            )
        return idx

    # ────────────────────────────────────────────────────────────
    # Direct column accessors
    # ────────────────────────────────────────────────────────────

    def get_Dx(self, x: int) -> float:
        """Get Dx at age x."""
        return float(self.Dx[self._idx(x)])

    def get_Nx(self, x: int) -> float:
        """Get Nx at age x."""
        return float(self.Nx[self._idx(x)])

    def get_Cx(self, x: int) -> float:
        """Get Cx at age x."""
        return float(self.Cx[self._idx(x)])

    def get_Mx(self, x: int) -> float:
        """Get Mx at age x."""
        return float(self.Mx[self._idx(x)])

    # ────────────────────────────────────────────────────────────
    # Insurance present values (APV of benefits)
    # ────────────────────────────────────────────────────────────

    def whole_life_insurance(self, x: int) -> float:
        """Net single premium for whole life insurance Ax.

        Ax = Mx / Dx

        Args:
            x: Issue age.

        Returns:
            APV of a whole life insurance of 1 payable at end of year of death.
        """
        return self.get_Mx(x) / self.get_Dx(x)

    def term_insurance(self, x: int, n: int) -> float:
        """Net single premium for n-year term insurance A¹ₓ:n̅|.

        A¹ₓ:n̅| = (Mx - M_{x+n}) / Dx

        Args:
            x: Issue age.
            n: Term in years.

        Returns:
            APV of an n-year term insurance of 1.
        """
        self._validate_term(x, n)
        return (self.get_Mx(x) - self.get_Mx(x + n)) / self.get_Dx(x)

    def pure_endowment(self, x: int, n: int) -> float:
        """Net single premium for n-year pure endowment ₙEx.

        ₙEx = D_{x+n} / Dx

        Args:
            x: Issue age.
            n: Term in years.

        Returns:
            APV of 1 payable at age x+n if alive.
        """
        self._validate_term(x, n)
        return self.get_Dx(x + n) / self.get_Dx(x)

    def endowment_insurance(self, x: int, n: int) -> float:
        """Net single premium for n-year endowment insurance Aₓ:n̅|.

        Aₓ:n̅| = A¹ₓ:n̅| + ₙEx = (Mx - M_{x+n} + D_{x+n}) / Dx

        Args:
            x: Issue age.
            n: Term in years.

        Returns:
            APV of an n-year endowment insurance of 1.
        """
        self._validate_term(x, n)
        Dx_val = self.get_Dx(x)
        return (self.get_Mx(x) - self.get_Mx(x + n) + self.get_Dx(x + n)) / Dx_val

    # ────────────────────────────────────────────────────────────
    # Annuity present values (APV of annuity payments)
    # ────────────────────────────────────────────────────────────

    def whole_life_annuity_due(self, x: int) -> float:
        """APV of whole life annuity-due äx.

        äx = Nx / Dx

        Args:
            x: Age.

        Returns:
            APV of an annuity-due of 1 per year payable for life.
        """
        return self.get_Nx(x) / self.get_Dx(x)

    def temp_annuity_due(self, x: int, n: int) -> float:
        """APV of n-year temporary annuity-due äₓ:n̅|.

        äₓ:n̅| = (Nx - N_{x+n}) / Dx

        Args:
            x: Age.
            n: Term in years.

        Returns:
            APV of an annuity-due of 1 per year for n years.
        """
        self._validate_term(x, n)
        return (self.get_Nx(x) - self.get_Nx(x + n)) / self.get_Dx(x)

    def whole_life_annuity_immediate(self, x: int) -> float:
        """APV of whole life annuity-immediate ax.

        ax = äx - 1 = (Nx / Dx) - 1

        Args:
            x: Age.

        Returns:
            APV of an annuity-immediate of 1 per year payable for life.
        """
        return self.whole_life_annuity_due(x) - 1.0

    def temp_annuity_immediate(self, x: int, n: int) -> float:
        """APV of n-year temporary annuity-immediate aₓ:n̅|.

        aₓ:n̅| = äₓ:n̅| - 1 + ₙEx

        Args:
            x: Age.
            n: Term in years.

        Returns:
            APV of an annuity-immediate of 1 per year for n years.
        """
        return self.temp_annuity_due(x, n) - 1.0 + self.pure_endowment(x, n)

    # ────────────────────────────────────────────────────────────
    # Validation
    # ────────────────────────────────────────────────────────────

    def _validate_age(self, x: int) -> None:
        """Validate that age x is within the table range."""
        if x < self._min_age:
            raise ValueError(
                f"Age {x} is below table minimum {self._min_age} ({self.table.name})."
            )
        if x > self._max_age:
            raise ValueError(
                f"Age {x} exceeds table maximum {self._max_age} ({self.table.name})."
            )

    def _validate_term(self, x: int, n: int) -> None:
        """Validate that age x + n is within the table range.

        Args:
            x: Issue age.
            n: Term in years.

        Raises:
            ValueError: If n ≤ 0 or x + n exceeds the table.
        """
        if n <= 0:
            raise ValueError(f"Term n must be positive. Got {n}.")
        self._validate_age(x)
        if x + n > self._max_age:
            raise ValueError(
                f"Age x + n = {x + n} exceeds table maximum {self._max_age} ({self.table.name})."
            )

    def __repr__(self) -> str:
        return (
            f"CommutationFunctions(table='{self.table.name}', "
            f"i={self.interest.annual_rate:.4%}, "
            f"ages=[{self._min_age}..{self._max_age}])"
        )
