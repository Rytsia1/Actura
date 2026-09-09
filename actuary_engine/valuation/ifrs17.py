"""
IFRS 17 / PSAK 117 Insurance Contracts Valuation Engine.

Implements the General Measurement Model (GMM / Building Block Approach - BBA):
1. Best Estimate Liability (BEL) - Discounted probability-weighted fulfillment cash flows
2. Risk Adjustment for Non-Financial Risk (RA) - Cost-of-capital or quantile technique
3. Contractual Service Margin (CSM) - Unearned future profit recognized over coverage units
4. Loss Component (LC) - Immediate P&L recognition for onerous contracts

Mathematical formulation:
    LRC_t = BEL_t + RA_t + CSM_t
    FCF_0 = BEL_0 + RA_0
    If FCF_0 < 0: CSM_0 = -FCF_0, LC_0 = 0 (Profitable cohort)
    If FCF_0 >= 0: CSM_0 = 0, LC_0 = FCF_0 (Onerous cohort)
    CSM_{t+1} = (CSM_t * (1 + i) +/- Delta) * (1 - CU_t / Total_Remaining_CU_t)
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from actuary_engine.models.assumptions import (
    ExpenseAssumption,
    InterestAssumption,
    LapseAssumption,
)
from actuary_engine.models.contracts import PolicyContract, ProductType
from actuary_engine.domain.pricing.premium import LevelPremiumCalculator
from actuary_engine.domain.tables.commutation import CommutationFunctions
from actuary_engine.domain.tables.mortality_table import MortalityTable
from actuary_engine.valuation.gpv import GrossPremiumValuation


class IFRS17CohortClassification(str, Enum):
    """IFRS 17 profitability classification groups at initial recognition."""

    PROFITABLE = "PROFITABLE"
    NO_SIGNIFICANT_RISK_OF_BECOMING_ONEROUS = "NO_SIGNIFICANT_RISK_OF_BECOMING_ONEROUS"
    ONEROUS = "ONEROUS"


class IFRS17InitialBalance(BaseModel):
    """Fulfillment cash flows and initial balance sheet position at t=0."""

    pv_future_benefits: float = Field(..., description="Present value of future death/maturity/lapse claims (PVFB_0).")
    pv_future_expenses: float = Field(..., description="Present value of future maintenance & acquisition expenses (PVFE_0).")
    pv_future_premiums: float = Field(..., description="Present value of future gross premium inflows (PVFP_0).")
    bel_0: float = Field(..., description="Initial Best Estimate Liability (PVFB + PVFE - PVFP).")
    ra_0: float = Field(..., description="Initial Risk Adjustment for non-financial risk.")
    fcf_0: float = Field(..., description="Initial Fulfillment Cash Flows (BEL_0 + RA_0).")
    csm_0: float = Field(..., description="Initial Contractual Service Margin (unearned profit).")
    loss_component_0: float = Field(..., description="Initial Loss Component recognized immediately in P&L for onerous groups.")
    classification: IFRS17CohortClassification = Field(..., description="IFRS 17 cohort profitability group.")
    profitability_margin: float = Field(..., description="Net margin as percentage of PV gross premiums.")
    initial_lrc: float = Field(..., description="Total Liability for Remaining Coverage at t=0.")


class IFRS17ValuationResult(BaseModel):
    """Comprehensive multi-year IFRS 17 General Measurement Model valuation output."""

    initial_balance: IFRS17InitialBalance
    balance_sheet_schedule: list[dict[str, Any]] = Field(
        ..., description="Year-by-year LRC trajectory (BEL, RA, CSM, LC, Total LRC)."
    )
    income_statement_schedule: list[dict[str, Any]] = Field(
        ..., description="Year-by-year P&L breakdown (Insurance Revenue, Service Expenses, CSM Amortization, Service Result)."
    )
    total_insurance_revenue: float = Field(..., description="Cumulative insurance revenue recognized over policy term.")
    total_csm_released: float = Field(..., description="Total CSM amortized into P&L over policy term.")
    total_service_expenses: float = Field(..., description="Cumulative insurance service expenses incurred.")


class IFRS17Engine:
    """IFRS 17 / PSAK 117 General Measurement Model (Building Block Approach) Engine.

    Attributes:
        table: Mortality table.
        interest: Valuation interest rate assumption.
        expense: Expense loadings (acquisition and maintenance).
        lapse: Lapse and surrender rate assumptions.
        ra_ratio: Risk adjustment loading factor (e.g. 0.06 = 6% of PV future claims & expenses).
    """

    __slots__ = ("table", "interest", "expense", "lapse", "ra_ratio")

    def __init__(
        self,
        table: MortalityTable,
        interest: InterestAssumption,
        expense: Optional[ExpenseAssumption] = None,
        lapse: Optional[LapseAssumption] = None,
        ra_ratio: float = 0.06,
    ) -> None:
        """Initialize IFRS 17 Valuation Engine.

        Args:
            table: Parsed MortalityTable.
            interest: InterestAssumption for discounting fulfillment cash flows.
            expense: ExpenseAssumption for direct and maintenance expenses.
            lapse: LapseAssumption for policyholder decrement behavior.
            ra_ratio: Risk adjustment factor applied to PV future outgo (default 6%).
        """
        self.table = table
        self.interest = interest
        self.expense = expense or ExpenseAssumption()
        self.lapse = lapse or LapseAssumption()
        self.ra_ratio = max(0.0, float(ra_ratio))

    def evaluate_initial_recognition(
        self,
        contract: PolicyContract,
        gross_premium: Optional[float] = None,
        surrender_values: Optional[np.ndarray] = None,
    ) -> IFRS17InitialBalance:
        """Evaluate initial recognition balance sheet position and cohort classification at t=0.

        Args:
            contract: PolicyContract specification.
            gross_premium: Annual gross premium (if None, calculated using equivalence + 20% expense load).
            surrender_values: Optional surrender values schedule.

        Returns:
            IFRS17InitialBalance with BEL, RA, CSM, Loss Component, and cohort profitability classification.
        """
        contract.validate_against_table(self.table)

        gpv = GrossPremiumValuation(
            table=self.table,
            interest=self.interest,
            expense=self.expense,
            lapse=self.lapse,
        )

        effective_gp = gross_premium
        if effective_gp is None:
            # Auto-calculate standard loaded gross premium (20% loading over net)
            comm = CommutationFunctions(self.table, self.interest)
            pricer = LevelPremiumCalculator(comm)
            net_res = pricer.price_contract(contract)
            effective_gp = net_res.annual_premium * 1.20

        # Project full multi-decrement cash flows from t=0
        cf_df = gpv.project(contract, effective_gp, surrender_values)

        pv_claims = float(cf_df["pv_death_claims"].sum() + cf_df["pv_lapse_payouts"].sum() + cf_df["pv_maturity"].sum())
        pv_expenses = float(cf_df["pv_expense"].sum())
        pv_premiums = float(cf_df["pv_premium"].sum())

        # 1. Best Estimate Liability (BEL_0 = PV Outgo - PV Inflow)
        bel_0 = pv_claims + pv_expenses - pv_premiums

        # 2. Risk Adjustment (RA_0)
        ra_0 = (pv_claims + pv_expenses) * self.ra_ratio

        # 3. Fulfillment Cash Flows (FCF_0)
        fcf_0 = bel_0 + ra_0

        # 4. CSM vs Loss Component Determination
        if fcf_0 < -1e-6:
            # Profitable cohort: Unearned profit deferred into CSM
            csm_0 = -fcf_0
            loss_component_0 = 0.0
            margin_pct = (csm_0 / pv_premiums) if pv_premiums > 0 else 0.0
            if margin_pct > 0.05:
                classification = IFRS17CohortClassification.PROFITABLE
            else:
                classification = IFRS17CohortClassification.NO_SIGNIFICANT_RISK_OF_BECOMING_ONEROUS
        else:
            # Onerous cohort: Immediate loss recognized in P&L
            csm_0 = 0.0
            loss_component_0 = max(0.0, fcf_0)
            classification = IFRS17CohortClassification.ONEROUS
            margin_pct = (-loss_component_0 / pv_premiums) if pv_premiums > 0 else 0.0

        initial_lrc = bel_0 + ra_0 + csm_0

        return IFRS17InitialBalance(
            pv_future_benefits=round(pv_claims, 2),
            pv_future_expenses=round(pv_expenses, 2),
            pv_future_premiums=round(pv_premiums, 2),
            bel_0=round(bel_0, 2),
            ra_0=round(ra_0, 2),
            fcf_0=round(fcf_0, 2),
            csm_0=round(csm_0, 2),
            loss_component_0=round(loss_component_0, 2),
            classification=classification,
            profitability_margin=round(margin_pct, 4),
            initial_lrc=round(initial_lrc, 2),
        )

    def roll_forward(
        self,
        contract: PolicyContract,
        gross_premium: Optional[float] = None,
        surrender_values: Optional[np.ndarray] = None,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Perform full multi-period IFRS 17 roll-forward projection.

        Produces:
        1. Balance Sheet Schedule: Year-by-year trajectory of BEL, RA, CSM, LC, and Total LRC.
        2. Income Statement Schedule: Year-by-year Insurance Revenue, Service Expenses, CSM release, and Service Result.

        Args:
            contract: PolicyContract specification.
            gross_premium: Annual gross premium.
            surrender_values: Optional surrender values schedule.

        Returns:
            Tuple of (balance_sheet_df, income_statement_df).
        """
        gpv = GrossPremiumValuation(
            table=self.table,
            interest=self.interest,
            expense=self.expense,
            lapse=self.lapse,
        )

        effective_gp = gross_premium
        if effective_gp is None:
            comm = CommutationFunctions(self.table, self.interest)
            pricer = LevelPremiumCalculator(comm)
            net_res = pricer.price_contract(contract)
            effective_gp = net_res.annual_premium * 1.20

        # Base year-by-year cash flows
        cf_df = gpv.project(contract, effective_gp, surrender_values)
        max_t = len(cf_df)
        i_rate = getattr(self.interest, "annual_rate", getattr(self.interest, "rate", 0.05))
        face = contract.sum_assured

        # Coverage Units: CU_t = Face Amount * Inforce_BOY_t
        inforce_boy = cf_df["inforce_boy"].to_numpy()
        coverage_units = face * inforce_boy

        # Initial recognition
        init_balance = self.evaluate_initial_recognition(contract, effective_gp, surrender_values)

        # ────────────────────────────────────────────────────────
        # 1. Roll-Forward Arrays
        # ────────────────────────────────────────────────────────
        csm_opening = np.zeros(max_t, dtype=np.float64)
        csm_interest = np.zeros(max_t, dtype=np.float64)
        csm_amortization = np.zeros(max_t, dtype=np.float64)
        csm_closing = np.zeros(max_t, dtype=np.float64)

        lc_opening = np.zeros(max_t, dtype=np.float64)
        lc_interest = np.zeros(max_t, dtype=np.float64)
        lc_amortization = np.zeros(max_t, dtype=np.float64)
        lc_closing = np.zeros(max_t, dtype=np.float64)

        ra_opening = np.zeros(max_t, dtype=np.float64)
        ra_closing = np.zeros(max_t, dtype=np.float64)
        ra_release = np.zeros(max_t, dtype=np.float64)

        current_csm = init_balance.csm_0
        current_lc = init_balance.loss_component_0

        # Calculate reserve profile (BEL at end of each year)
        res_profile = gpv.gross_reserve_profile(contract, effective_gp, surrender_values)
        bel_trajectory = res_profile["gross_reserve"].to_numpy()  # length max_t + 1 (t=0..max_t)

        for t in range(max_t):
            # Remaining coverage units from year t to end
            remaining_cu = np.sum(coverage_units[t:])
            cu_factor = (coverage_units[t] / remaining_cu) if remaining_cu > 1e-6 else 1.0

            # ── CSM Roll-Forward ──
            csm_opening[t] = current_csm
            csm_interest[t] = current_csm * i_rate
            csm_pre = current_csm + csm_interest[t]
            csm_amortization[t] = csm_pre * cu_factor
            csm_closing[t] = max(0.0, csm_pre - csm_amortization[t])
            current_csm = csm_closing[t]

            # ── Loss Component Roll-Forward ──
            lc_opening[t] = current_lc
            lc_interest[t] = current_lc * i_rate
            lc_pre = current_lc + lc_interest[t]
            lc_amortization[t] = lc_pre * cu_factor
            lc_closing[t] = max(0.0, lc_pre - lc_amortization[t])
            current_lc = lc_closing[t]

            # ── Risk Adjustment Roll-Forward ──
            # RA at duration t is proportional to remaining future claims & expenses
            # At duration t, BEL is bel_trajectory[t]
            ra_opening[t] = max(0.0, bel_trajectory[t] * self.ra_ratio) if t > 0 else init_balance.ra_0
            ra_closing[t] = max(0.0, bel_trajectory[t + 1] * self.ra_ratio)
            ra_release[t] = max(0.0, (ra_opening[t] * (1.0 + i_rate) - ra_closing[t]))

        # Enforce terminal CSM & LC closure at maturity
        csm_closing[-1] = 0.0
        lc_closing[-1] = 0.0
        ra_closing[-1] = 0.0

        # ────────────────────────────────────────────────────────
        # 2. Build Balance Sheet Trajectory DataFrame
        # ────────────────────────────────────────────────────────
        durations = np.arange(max_t + 1, dtype=np.int64)
        bel_col = np.empty(max_t + 1, dtype=np.float64)
        ra_col = np.empty(max_t + 1, dtype=np.float64)
        csm_col = np.empty(max_t + 1, dtype=np.float64)
        lc_col = np.empty(max_t + 1, dtype=np.float64)
        total_lrc = np.empty(max_t + 1, dtype=np.float64)

        # t = 0
        bel_col[0] = init_balance.bel_0
        ra_col[0] = init_balance.ra_0
        csm_col[0] = init_balance.csm_0
        lc_col[0] = init_balance.loss_component_0
        total_lrc[0] = bel_col[0] + ra_col[0] + csm_col[0]

        # t = 1..max_t
        for t in range(max_t):
            bel_col[t + 1] = bel_trajectory[t + 1]
            ra_col[t + 1] = ra_closing[t]
            csm_col[t + 1] = csm_closing[t]
            lc_col[t + 1] = lc_closing[t]
            total_lrc[t + 1] = bel_col[t + 1] + ra_col[t + 1] + csm_col[t + 1]

        balance_sheet_df = pd.DataFrame({
            "duration": durations,
            "bel": np.round(bel_col, 2),
            "risk_adjustment": np.round(ra_col, 2),
            "csm": np.round(csm_col, 2),
            "loss_component": np.round(lc_col, 2),
            "total_lrc": np.round(total_lrc, 2),
        })

        # ────────────────────────────────────────────────────────
        # 3. Build Income Statement (P&L) DataFrame
        # ────────────────────────────────────────────────────────
        years = cf_df["year"].to_numpy()
        claims_incurred = cf_df["death_claims"].to_numpy() + cf_df["maturity_benefit"].to_numpy() + cf_df["lapse_payouts"].to_numpy()
        expenses_incurred = cf_df["total_expense"].to_numpy()
        premiums = cf_df["premium_income"].to_numpy()

        # IFRS 17 Insurance Revenue = Expected Claims + Expected Expenses + RA Release + CSM Release
        insurance_revenue = claims_incurred + expenses_incurred + ra_release + csm_amortization
        insurance_service_expenses = claims_incurred + expenses_incurred
        insurance_service_result = insurance_revenue - insurance_service_expenses

        income_statement_df = pd.DataFrame({
            "year": years,
            "premiums_collected": np.round(premiums, 2),
            "insurance_revenue": np.round(insurance_revenue, 2),
            "claims_incurred": np.round(claims_incurred, 2),
            "expenses_incurred": np.round(expenses_incurred, 2),
            "insurance_service_expenses": np.round(insurance_service_expenses, 2),
            "csm_amortization": np.round(csm_amortization, 2),
            "ra_release": np.round(ra_release, 2),
            "insurance_service_result": np.round(insurance_service_result, 2),
        })

        return balance_sheet_df, income_statement_df

    def evaluate(
        self,
        contract: PolicyContract,
        gross_premium: Optional[float] = None,
        surrender_values: Optional[np.ndarray] = None,
    ) -> IFRS17ValuationResult:
        """Run complete IFRS 17 valuation returning Pydantic result object."""
        init_balance = self.evaluate_initial_recognition(contract, gross_premium, surrender_values)
        bs_df, is_df = self.roll_forward(contract, gross_premium, surrender_values)

        total_rev = float(is_df["insurance_revenue"].sum())
        total_csm_rel = float(is_df["csm_amortization"].sum())
        total_serv_exp = float(is_df["insurance_service_expenses"].sum())

        return IFRS17ValuationResult(
            initial_balance=init_balance,
            balance_sheet_schedule=bs_df.to_dict(orient="records"),
            income_statement_schedule=is_df.to_dict(orient="records"),
            total_insurance_revenue=round(total_rev, 2),
            total_csm_released=round(total_csm_rel, 2),
            total_service_expenses=round(total_serv_exp, 2),
        )
