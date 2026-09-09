"""
Level premium calculation via the equivalence principle.

Provides the ``LevelPremiumCalculator`` class which computes annual net
level premiums for standard life insurance products using the equivalence
principle:

    P · äₓ:h̅|  =  NSP

where:
- P   = annual level premium
- äₓ:h̅| = APV of premium annuity-due for h years
- NSP = net single premium (APV of benefits)
- h   = premium paying term (= coverage term for ordinary, < term for limited pay)

The result is returned as a structured ``PremiumResult`` with full breakdown.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from actuary_engine.models.contracts import PolicyContract, ProductType
from actuary_engine.domain.tables.commutation import CommutationFunctions


class PremiumResult(BaseModel):
    """Structured result of a level premium calculation.

    Contains the annual premium, its component APVs, and metadata
    about the policy for traceability and downstream reporting.

    Attributes:
        annual_premium: Annual net level premium.
        nsp: Net Single Premium (APV of benefits).
        annuity_factor: APV of premium annuity-due (äₓ:h̅| or äx).
        benefit_premium_ratio: NSP / annuity_factor (= annual_premium).
        product_type: Insurance product type.
        issue_age: Age at policy issue.
        term: Coverage term (None for whole life).
        premium_paying_term: Premium payment period.
        sum_assured: Face amount.
    """

    annual_premium: float = Field(description="Annual net level premium.")
    nsp: float = Field(description="Net single premium (APV of benefits).")
    annuity_factor: float = Field(description="APV of premium annuity-due.")
    benefit_premium_ratio: float = Field(
        description="NSP / annuity_factor — should equal annual_premium."
    )
    product_type: ProductType
    issue_age: int
    term: Optional[int] = None
    premium_paying_term: Optional[int] = None
    sum_assured: float = 1.0

    model_config = {"frozen": True}


class LevelPremiumCalculator:
    """Annual net level premium calculator.

    Uses the equivalence principle to determine the annual premium that
    equates the present value of future premiums to the present value
    of future benefits. Supports ordinary and limited-pay structures.

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

    def annual_premium_term(
        self,
        x: int,
        n: int,
        face: float = 1.0,
        premium_term: Optional[int] = None,
    ) -> PremiumResult:
        """Annual net premium for n-year term insurance.

        P = face × (Mx - M_{x+n}) / (Nx - N_{x+h})

        where h = premium_term or n.

        Args:
            x: Issue age.
            n: Coverage term in years.
            face: Face amount.
            premium_term: Premium paying term (default = n).

        Returns:
            PremiumResult with full breakdown.
        """
        h = premium_term if premium_term is not None else n
        self._validate_premium_term(h, n)

        nsp = face * self.commutation.term_insurance(x, n)
        annuity = self.commutation.temp_annuity_due(x, h)
        annual_p = nsp / annuity

        return PremiumResult(
            annual_premium=annual_p,
            nsp=nsp,
            annuity_factor=annuity,
            benefit_premium_ratio=annual_p,
            product_type=ProductType.TERM,
            issue_age=x,
            term=n,
            premium_paying_term=h,
            sum_assured=face,
        )

    def annual_premium_whole_life(
        self,
        x: int,
        face: float = 1.0,
        premium_term: Optional[int] = None,
    ) -> PremiumResult:
        """Annual net premium for whole life insurance.

        Ordinary: P = face × Mx / Nx
        Limited-pay (h years): P = face × Mx / (Nx - N_{x+h})

        Args:
            x: Issue age.
            face: Face amount.
            premium_term: Premium paying term (None = for life).

        Returns:
            PremiumResult with full breakdown.
        """
        nsp = face * self.commutation.whole_life_insurance(x)

        if premium_term is not None:
            annuity = self.commutation.temp_annuity_due(x, premium_term)
        else:
            annuity = self.commutation.whole_life_annuity_due(x)

        annual_p = nsp / annuity

        return PremiumResult(
            annual_premium=annual_p,
            nsp=nsp,
            annuity_factor=annuity,
            benefit_premium_ratio=annual_p,
            product_type=ProductType.WHOLE_LIFE,
            issue_age=x,
            term=None,
            premium_paying_term=premium_term,
            sum_assured=face,
        )

    def annual_premium_endowment(
        self,
        x: int,
        n: int,
        face: float = 1.0,
        premium_term: Optional[int] = None,
    ) -> PremiumResult:
        """Annual net premium for n-year endowment insurance.

        P = face × (Mx - M_{x+n} + D_{x+n}) / (Nx - N_{x+h})

        where h = premium_term or n.

        Args:
            x: Issue age.
            n: Coverage term in years.
            face: Face amount.
            premium_term: Premium paying term (default = n).

        Returns:
            PremiumResult with full breakdown.
        """
        h = premium_term if premium_term is not None else n
        self._validate_premium_term(h, n)

        nsp = face * self.commutation.endowment_insurance(x, n)
        annuity = self.commutation.temp_annuity_due(x, h)
        annual_p = nsp / annuity

        return PremiumResult(
            annual_premium=annual_p,
            nsp=nsp,
            annuity_factor=annuity,
            benefit_premium_ratio=annual_p,
            product_type=ProductType.ENDOWMENT,
            issue_age=x,
            term=n,
            premium_paying_term=h,
            sum_assured=face,
        )

    def annual_premium_pure_endowment(
        self,
        x: int,
        n: int,
        face: float = 1.0,
        premium_term: Optional[int] = None,
    ) -> PremiumResult:
        """Annual net premium for n-year pure endowment.

        P = face × D_{x+n} / (Nx - N_{x+h})

        Args:
            x: Issue age.
            n: Term in years.
            face: Face amount.
            premium_term: Premium paying term (default = n).

        Returns:
            PremiumResult with full breakdown.
        """
        h = premium_term if premium_term is not None else n
        self._validate_premium_term(h, n)

        nsp = face * self.commutation.pure_endowment(x, n)
        annuity = self.commutation.temp_annuity_due(x, h)
        annual_p = nsp / annuity

        return PremiumResult(
            annual_premium=annual_p,
            nsp=nsp,
            annuity_factor=annuity,
            benefit_premium_ratio=annual_p,
            product_type=ProductType.PURE_ENDOWMENT,
            issue_age=x,
            term=n,
            premium_paying_term=h,
            sum_assured=face,
        )

    def price_contract(self, contract: PolicyContract) -> PremiumResult:
        """Compute annual level premium for a PolicyContract.

        Dispatches to the appropriate pricing method based on the
        contract's product type.

        Args:
            contract: A fully specified PolicyContract.

        Returns:
            PremiumResult with full breakdown.

        Raises:
            ValueError: If the product type is unsupported.
        """
        contract.validate_against_table(self.commutation.table)

        x = contract.issue_age
        face = contract.sum_assured
        n = contract.term
        h = contract.premium_paying_term

        if contract.product_type == ProductType.TERM:
            assert n is not None
            return self.annual_premium_term(x, n, face, h)
        elif contract.product_type == ProductType.WHOLE_LIFE:
            return self.annual_premium_whole_life(x, face, h)
        elif contract.product_type == ProductType.ENDOWMENT:
            assert n is not None
            return self.annual_premium_endowment(x, n, face, h)
        elif contract.product_type == ProductType.PURE_ENDOWMENT:
            assert n is not None
            return self.annual_premium_pure_endowment(x, n, face, h)
        else:
            raise ValueError(f"Unsupported product type: {contract.product_type}")

    @staticmethod
    def _validate_premium_term(h: int, n: int) -> None:
        """Validate premium paying term.

        Args:
            h: Premium paying term.
            n: Coverage term.

        Raises:
            ValueError: If h > n or h ≤ 0.
        """
        if h <= 0:
            raise ValueError(f"Premium paying term must be positive. Got {h}.")
        if h > n:
            raise ValueError(
                f"Premium paying term ({h}) cannot exceed coverage term ({n})."
            )

    def __repr__(self) -> str:
        return f"LevelPremiumCalculator(commutation={self.commutation!r})"
