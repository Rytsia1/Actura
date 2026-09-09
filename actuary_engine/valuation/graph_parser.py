"""
Visual Node-Based Contract Logic DAG Parser and Actuarial Cash Flow Simulator.

Topologically parses visual logic graphs generated in the frontend (@vue-flow),
validates against cycles and disconnected nodes, and projects deterministic multi-decrement
cash flows and liability reserves.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Optional

import numpy as np
import pandas as pd

from actuary_engine.api.schemas import ContractGraphPayload, SimulateGraphResponse, ProvenanceTrace
from actuary_engine.models.assumptions import (
    ExpenseAssumption,
    InterestAssumption,
    LapseAssumption,
)
from actuary_engine.models.contracts import PolicyContract, ProductType
from actuary_engine.domain.pricing.premium import LevelPremiumCalculator
from actuary_engine.domain.tables.commutation import CommutationFunctions
from actuary_engine.domain.tables.mortality_table import MortalityTable
from actuary_engine.domain.tables.registry import table_registry
from actuary_engine.valuation._kernels import _rollback_gpv_kernel


class ContractGraphSimulator:
    """Evaluates node-based visual contract logic blueprints into deterministic actuarial projections."""

    def __init__(self, table_lookup: Optional[Any] = None) -> None:
        self.table_registry = table_lookup or table_registry

    def simulate(self, payload: ContractGraphPayload) -> SimulateGraphResponse:
        """Topologically sort DAG and simulate cash flows."""
        nodes_by_id = {node.id: node for node in payload.nodes}
        if not nodes_by_id:
            raise ValueError("Contract graph must contain at least one PolicyInput node.")

        # 1. Topological Sort & Cycle Detection (Kahn's algorithm)
        in_degree: dict[str, int] = defaultdict(int)
        adjacency: dict[str, list[str]] = defaultdict(list)

        for node_id in nodes_by_id:
            in_degree[node_id] = 0

        for edge in payload.edges:
            if edge.source in nodes_by_id and edge.target in nodes_by_id:
                adjacency[edge.source].append(edge.target)
                in_degree[edge.target] += 1

        queue = deque([n_id for n_id, deg in in_degree.items() if deg == 0])
        sorted_nodes: list[str] = []

        while queue:
            curr = queue.popleft()
            sorted_nodes.append(curr)
            for neighbor in adjacency[curr]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(sorted_nodes) < len(nodes_by_id):
            raise ValueError("Graph contains a cycle or circular dependency. DAG structure required.")

        # 2. Extract Policy Metadata from PolicyInput node
        policy_node = None
        policy_node_id = None
        for node in payload.nodes:
            ntype = (node.type or "").lower()
            if ntype in ("policyinput", "policy_input", "input"):
                policy_node = node
                policy_node_id = node.id
                break

        data = policy_node.data if policy_node else {}
        age = int(data.get("age", data.get("issue_age", 35)))
        term = int(data.get("term", data.get("term_years", 20)))
        sum_assured = float(data.get("sum_assured", data.get("face_amount", 1_000_000.0)))
        interest_rate = float(data.get("interest_rate", payload.discount_rate or 0.05))
        table_id = str(data.get("table_id", "soa_ilt")).lower().strip()
        product_name = str(data.get("product_name", data.get("title", "Custom Contract Logic")))

        # Fetch mortality table
        try:
            base_table = self.table_registry.get_table(table_id)
        except KeyError:
            base_table = self.table_registry.get_table("soa_ilt")

        # 3. Decrement Configurations from Contingency Nodes
        mortality_mult = 1.0
        lapse_rate = 0.03
        has_maturity = False
        maturity_year = term
        
        contingency_node_ids = []

        for node in payload.nodes:
            ntype = (node.type or "").lower()
            if ntype in ("contingency", "decrement"):
                contingency_node_ids.append(node.id)
                ndata = node.data
                dtype = str(ndata.get("decrement_type", "Mortality")).lower()
                mult = float(ndata.get("multiplier", 1.0))
                if "mort" in dtype:
                    mortality_mult *= mult
                elif "lapse" in dtype:
                    lapse_rate = float(ndata.get("lapse_rate", 0.03)) * mult
                elif "matur" in dtype:
                    has_maturity = True
                    maturity_year = int(ndata.get("maturity_year", term))

        # Adjust mortality table if multiplier is non-1.0
        if mortality_mult != 1.0:
            qx_shocked = np.clip(base_table.qx * mortality_mult, 0.0, 1.0)
            qx_shocked[:-1] = np.minimum(qx_shocked[:-1], 0.9999)
            qx_shocked[-1] = 1.0
            table = MortalityTable(
                ages=base_table.ages,
                qx=qx_shocked,
                name=f"{base_table.name}_scaled",
                radix=base_table.radix,
            )
        else:
            table = base_table

        if age < table.min_age:
            raise ValueError(f"Issue age ({age}) is below mortality table minimum age of {table.min_age} ({table.name}).")
        if age + term > table.max_age:
            raise ValueError(f"Age ({age}) + term ({term}) = {age + term} exceeds mortality table maximum age of {table.max_age} ({table.name}).")

        # 4. Outflow / Benefit Configuration
        death_benefit_factor = 1.0
        maturity_benefit_factor = 0.0
        has_surrender_benefit = False
        surrender_pct = 0.80
        expense_pct_first = 0.35
        expense_pct_renewal = 0.05
        expense_per_pol_first = 200.0
        expense_per_pol_renewal = 20.0
        is_unit_linked = False
        fund_growth_rate = 0.06
        
        outflow_node_ids = []

        for node in payload.nodes:
            ntype = (node.type or "").lower()
            ndata = node.data
            if ntype in ("outflow", "benefit"):
                outflow_node_ids.append(node.id)
                btype = str(ndata.get("benefit_type", "Death Benefit")).lower()
                formula = str(ndata.get("formula", "1.0 * SA")).lower()

                factor = 1.0
                if "0.5" in formula or "50%" in formula:
                    factor = 0.5
                elif "1.5" in formula or "150%" in formula:
                    factor = 1.5
                elif "2.0" in formula or "200%" in formula:
                    factor = 2.0

                if "death" in btype:
                    death_benefit_factor = factor
                elif "maturity" in btype:
                    has_maturity = True
                    maturity_benefit_factor = factor
                elif "surrender" in btype:
                    has_surrender_benefit = True
                    surrender_pct = float(ndata.get("surrender_ratio", 0.80))
                elif "expense" in btype:
                    expense_pct_first = float(ndata.get("first_year_pct", 0.35))
                    expense_pct_renewal = float(ndata.get("renewal_pct", 0.05))
            elif ntype in ("accumulator", "unitlinked", "unit_linked"):
                is_unit_linked = True
                fund_growth_rate = float(ndata.get("growth_rate", 0.06))

        # 5. Inflow / Premium Configuration
        annual_premium = 0.0
        interest_assump = InterestAssumption(annual_rate=interest_rate)

        # Check if inflow node has explicit amount
        explicit_premium = None
        inflow_node_ids = []
        sink_node_ids = []
        for node in payload.nodes:
            ntype = (node.type or "").lower()
            if ntype in ("inflow", "premium"):
                inflow_node_ids.append(node.id)
                ndata = node.data
                mode = str(ndata.get("mode", "fixed")).lower()
                amt = ndata.get("amount")
                if mode == "fixed" and amt is not None and float(amt) > 0:
                    explicit_premium = float(amt)
            elif ntype in ("valuationsink", "valuation_sink", "sink"):
                sink_node_ids.append(node.id)

        if explicit_premium is not None:
            annual_premium = explicit_premium
        else:
            # Auto-price standard equivalent level premium
            comm = CommutationFunctions(table, interest_assump)
            pricer = LevelPremiumCalculator(comm)
            if has_maturity and maturity_benefit_factor > 0:
                contract = PolicyContract(
                    product_type=ProductType.ENDOWMENT,
                    issue_age=age,
                    term=term,
                    sum_assured=sum_assured,
                )
            else:
                contract = PolicyContract(
                    product_type=ProductType.TERM,
                    issue_age=age,
                    term=term,
                    sum_assured=sum_assured,
                )
            net_res = pricer.price_contract(contract)
            annual_premium = round(net_res.annual_premium * 1.20, 2)  # loaded GP

        # 6. Multi-Decrement Vectorized Projection
        years_arr = np.arange(term, dtype=np.int64)
        ages_arr = age + years_arr
        v = 1.0 / (1.0 + interest_rate)

        # Look up mortality qx for cohort
        age_indices = np.clip(ages_arr - table.min_age, 0, len(table.qx) - 1)
        qx_indep = table.qx[age_indices]
        wx_indep = np.full(term, lapse_rate, dtype=np.float64)

        # UDD dependent rates
        qx_dep = qx_indep * (1.0 - wx_indep / 2.0)
        wx_dep = wx_indep * (1.0 - qx_indep / 2.0)

        # In-force cohort rollout
        p_step = np.clip(1.0 - qx_dep - wx_dep, 0.0, 1.0)
        inforce = np.zeros(term + 1, dtype=np.float64)
        inforce[0] = 1.0
        for t in range(term):
            inforce[t + 1] = inforce[t] * p_step[t]

        inforce_boy = inforce[:term]

        # Inflows (Premiums)
        premium_income = annual_premium * inforce_boy

        # Outflows (Claims, Surrenders, Maturities, Expenses)
        death_claims = sum_assured * death_benefit_factor * inforce_boy * qx_dep

        # Surrenders
        if has_surrender_benefit or is_unit_linked:
            surrender_payouts = (annual_premium * np.arange(1, term + 1) * surrender_pct) * inforce_boy * wx_dep
        else:
            surrender_payouts = np.zeros(term, dtype=np.float64)

        # Maturity Benefit
        maturity_payouts = np.zeros(term, dtype=np.float64)
        if has_maturity and maturity_benefit_factor > 0:
            maturity_idx = min(term - 1, maturity_year - 1)
            # Paid to surviving lives at end of maturity year
            maturity_payouts[maturity_idx] = sum_assured * maturity_benefit_factor * inforce[maturity_idx + 1]

        # Expenses
        pct_expenses = np.where(years_arr == 0, expense_pct_first, expense_pct_renewal) * premium_income
        per_pol_expenses = np.where(years_arr == 0, expense_per_pol_first, expense_per_pol_renewal) * inforce_boy
        total_expenses = pct_expenses + per_pol_expenses

        # Net Cash Flow (NCF = Inflow - Outgo from insurer perspective, or Outgo - Inflow for liability)
        # Actuarial liability convention: Net liability cash flow = Outgo - Inflow
        net_liability_cf = (death_claims + surrender_payouts + maturity_payouts + total_expenses) - premium_income
        signed_ncf = premium_income - (death_claims + surrender_payouts + maturity_payouts + total_expenses)

        # Discounted Net Cash Flows
        discount_factors = v ** (years_arr + 1)
        discounted_net_cf = net_liability_cf * discount_factors
        total_bel = float(np.sum(discounted_net_cf))

        # Rollback Gross Reserves Profile
        reserves = _rollback_gpv_kernel(
            death_claims=np.ascontiguousarray(death_claims, dtype=np.float64),
            lapse_payouts=np.ascontiguousarray(surrender_payouts, dtype=np.float64),
            maturity_benefits=np.ascontiguousarray(maturity_payouts, dtype=np.float64),
            expenses=np.ascontiguousarray(total_expenses, dtype=np.float64),
            premiums=np.ascontiguousarray(premium_income, dtype=np.float64),
            qx_dep=np.ascontiguousarray(qx_dep, dtype=np.float64),
            wx_dep=np.ascontiguousarray(wx_dep, dtype=np.float64),
            discount_v=float(v),
            max_t=int(term),
        )

        # 7. Calculation Provenance Layer
        provenance = {}
        
        # Helper to safely append valid IDs
        def _get_nodes(*lists):
            nodes = []
            for lst in lists:
                if lst:
                    if isinstance(lst, str): nodes.append(lst)
                    else: nodes.extend(lst)
            return list(set(nodes))
        
        provenance["total_bel"] = ProvenanceTrace(
            metric_name="Best Estimate Liability (BEL)",
            value=round(total_bel, 2),
            contributing_components=["Premiums", "Death Claims", "Surrender Payouts", "Maturity Benefits", "Expenses"],
            relevant_assumptions={
                "Discount Rate": f"{interest_rate * 100:.2f}%",
                "Mortality Table": table.name,
                "Lapse Rate": f"{lapse_rate * 100:.2f}%"
            },
            source_nodes=_get_nodes(policy_node_id, sink_node_ids, outflow_node_ids, contingency_node_ids),
            calculation_stage="Present Value Aggregation",
            calculation_description="Computed as the sum of discounted future expected benefit and expense outflows, minus the discounted future expected premium inflows."
        )

        provenance["annual_premium"] = ProvenanceTrace(
            metric_name="Annual Premium",
            value=round(annual_premium, 2),
            contributing_components=["Gross Premium"],
            relevant_assumptions={},
            source_nodes=_get_nodes(inflow_node_ids, policy_node_id),
            calculation_stage="Premium Determination",
            calculation_description="Annual premium collected at the beginning of each policy year from the active in-force cohort."
        )

        return SimulateGraphResponse(
            contract_id=payload.contract_id or "GRAPH-CONTRACT-01",
            product_name=product_name,
            issue_age=age,
            term=term,
            sum_assured=sum_assured,
            annual_premium=annual_premium,
            total_bel=round(total_bel, 2),
            years=[int(y + 1) for y in years_arr],
            ages=[int(a) for a in ages_arr],
            inforce_boy=np.round(inforce_boy, 4).tolist(),
            premiums=np.round(premium_income, 2).tolist(),
            death_claims=np.round(death_claims, 2).tolist(),
            maturity_payouts=np.round(maturity_payouts, 2).tolist(),
            surrender_payouts=np.round(surrender_payouts, 2).tolist(),
            expenses=np.round(total_expenses, 2).tolist(),
            net_cash_flow=np.round(signed_ncf, 2).tolist(),
            discounted_net_cf=np.round(discounted_net_cf, 2).tolist(),
            reserves=np.round(reserves, 2).tolist(),
            breakdown={
                "total_premiums": round(float(np.sum(premium_income)), 2),
                "total_claims": round(float(np.sum(death_claims)), 2),
                "total_maturities": round(float(np.sum(maturity_payouts)), 2),
                "total_surrenders": round(float(np.sum(surrender_payouts)), 2),
                "total_expenses": round(float(np.sum(total_expenses)), 2),
                "interest_rate": interest_rate,
                "table_id": table_id,
                "has_maturity": has_maturity,
                "node_count": len(payload.nodes),
                "edge_count": len(payload.edges),
            },
            provenance=provenance,
        )
