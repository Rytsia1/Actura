"""
Insurance pricing via commutation functions.

Provides the ``InsurancePricer`` class which computes Net Single Premiums
(NSPs) for standard life insurance products — term, whole life, endowment,
and pure endowment — using pre-computed commutation function tables.

All pricing follows the classical actuarial present value approach:
NSP = APV(benefits) = face_amount × Ax (or variant).
"""

from __future__ import annotations

from typing import Optional

from actuary_engine.models.contracts import PolicyContract, ProductType
from actuary_engine.domain.tables.commutation import CommutationFunctions


class InsurancePricer:
    """Net Single Premium calculator for life insurance products.

    Wraps a ``CommutationFunctions`` instance to compute present values
    of death and survival benefits for arbitrary face amounts.

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

    def nsp_term(self, x: int, n: int, face: float = 1.0) -> float:
        """NSP for n-year term insurance.

        NSP = face × A¹ₓ:n̅| = face × (Mx - M_{x+n}) / Dx

        Args:
            x: Issue age.
            n: Coverage term in years.
            face: Face amount (sum assured).

        Returns:
            Net single premium for term insurance.
        """
        return face * self.commutation.term_insurance(x, n)

    def nsp_whole_life(self, x: int, face: float = 1.0) -> float:
        """NSP for whole life insurance.

        NSP = face × Ax = face × Mx / Dx

        Args:
            x: Issue age.
            face: Face amount.

        Returns:
            Net single premium for whole life insurance.
        """
        return face * self.commutation.whole_life_insurance(x)

    def nsp_endowment(self, x: int, n: int, face: float = 1.0) -> float:
        """NSP for n-year endowment insurance.

        NSP = face × Aₓ:n̅| = face × (Mx - M_{x+n} + D_{x+n}) / Dx

        Args:
            x: Issue age.
            n: Coverage term in years.
            face: Face amount.

        Returns:
            Net single premium for endowment insurance.
        """
        return face * self.commutation.endowment_insurance(x, n)

    def nsp_pure_endowment(self, x: int, n: int, face: float = 1.0) -> float:
        """NSP for n-year pure endowment.

        NSP = face × ₙEx = face × D_{x+n} / Dx

        Args:
            x: Issue age.
            n: Term in years.
            face: Face amount.

        Returns:
            Net single premium for pure endowment.
        """
        return face * self.commutation.pure_endowment(x, n)

    def price_contract(self, contract: PolicyContract) -> float:
        """Compute NSP for a PolicyContract.

        Dispatches to the appropriate pricing method based on the
        contract's product type.

        Args:
            contract: A fully specified PolicyContract.

        Returns:
            Net single premium for the contract.

        Raises:
            ValueError: If the product type is unsupported.
        """
        contract.validate_against_table(self.commutation.table)

        x = contract.issue_age
        face = contract.sum_assured
        n = contract.term

        if contract.product_type == ProductType.TERM:
            assert n is not None
            return self.nsp_term(x, n, face)
        elif contract.product_type == ProductType.WHOLE_LIFE:
            return self.nsp_whole_life(x, face)
        elif contract.product_type == ProductType.ENDOWMENT:
            assert n is not None
            return self.nsp_endowment(x, n, face)
        elif contract.product_type == ProductType.PURE_ENDOWMENT:
            assert n is not None
            return self.nsp_pure_endowment(x, n, face)
        else:
            raise ValueError(f"Unsupported product type: {contract.product_type}")

    def __repr__(self) -> str:
        return f"InsurancePricer(commutation={self.commutation!r})"
