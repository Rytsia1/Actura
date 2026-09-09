"""
Annuity pricing via commutation functions.

Provides the ``AnnuityPricer`` class which computes actuarial present values
(APVs) of life annuities — both due (beginning-of-period) and immediate
(end-of-period), in whole-life and temporary variants.

Standard actuarial notation:
- äx     = whole life annuity-due
- äₓ:n̅|  = n-year temporary annuity-due
- ax     = whole life annuity-immediate = äx - 1
- aₓ:n̅|  = n-year temporary annuity-immediate = äₓ:n̅| - 1 + ₙEx
"""

from __future__ import annotations

from actuary_engine.domain.tables.commutation import CommutationFunctions


class AnnuityPricer:
    """Life annuity present value calculator.

    Wraps a ``CommutationFunctions`` instance to compute APVs of
    annuity payments. All methods return the present value of an
    annuity of 1 per period — multiply by the actual payment amount
    for non-unit annuities.

    Attributes:
        commutation: The underlying commutation function table.
    """

    __slots__ = ("commutation",)

    def __init__(self, commutation: CommutationFunctions) -> None:
        """Initialize with a commutation function table.

        Args:
            commutation: Pre-computed commutation functions.
        """
        self.commutation = commutation

    # ────────────────────────────────────────────────────────────
    # Annuity-Due (payments at beginning of period)
    # ────────────────────────────────────────────────────────────

    def whole_life_due(self, x: int) -> float:
        """APV of whole life annuity-due äx.

        äx = Nx / Dx

        Args:
            x: Age at which annuity begins.

        Returns:
            Present value of annuity-due of 1 per year for life.
        """
        return self.commutation.whole_life_annuity_due(x)

    def temporary_due(self, x: int, n: int) -> float:
        """APV of n-year temporary annuity-due äₓ:n̅|.

        äₓ:n̅| = (Nx - N_{x+n}) / Dx

        Args:
            x: Starting age.
            n: Duration in years.

        Returns:
            Present value of annuity-due of 1 per year for n years.
        """
        return self.commutation.temp_annuity_due(x, n)

    # ────────────────────────────────────────────────────────────
    # Annuity-Immediate (payments at end of period)
    # ────────────────────────────────────────────────────────────

    def whole_life_immediate(self, x: int) -> float:
        """APV of whole life annuity-immediate ax.

        ax = äx - 1

        Args:
            x: Age at which annuity begins.

        Returns:
            Present value of annuity-immediate of 1 per year for life.
        """
        return self.commutation.whole_life_annuity_immediate(x)

    def temporary_immediate(self, x: int, n: int) -> float:
        """APV of n-year temporary annuity-immediate aₓ:n̅|.

        aₓ:n̅| = äₓ:n̅| - 1 + ₙEx

        Args:
            x: Starting age.
            n: Duration in years.

        Returns:
            Present value of annuity-immediate of 1 per year for n years.
        """
        return self.commutation.temp_annuity_immediate(x, n)

    # ────────────────────────────────────────────────────────────
    # Deferred annuities
    # ────────────────────────────────────────────────────────────

    def deferred_whole_life_due(self, x: int, u: int) -> float:
        """APV of u-year deferred whole life annuity-due.

        u|äx = N_{x+u} / Dx

        Args:
            x: Current age.
            u: Deferral period in years.

        Returns:
            Present value of deferred whole life annuity-due of 1.
        """
        return self.commutation.get_Nx(x + u) / self.commutation.get_Dx(x)

    def deferred_temporary_due(self, x: int, u: int, n: int) -> float:
        """APV of u-year deferred n-year temporary annuity-due.

        u|äₓ:n̅| = (N_{x+u} - N_{x+u+n}) / Dx

        Args:
            x: Current age.
            u: Deferral period in years.
            n: Payment period in years.

        Returns:
            Present value of deferred temporary annuity-due of 1.
        """
        Dx = self.commutation.get_Dx(x)
        Nxu = self.commutation.get_Nx(x + u)
        Nxun = self.commutation.get_Nx(x + u + n)
        return (Nxu - Nxun) / Dx

    def __repr__(self) -> str:
        return f"AnnuityPricer(commutation={self.commutation!r})"
