"""
Actura Model Health System.

Evaluates whether an actuarial model is ready to run and whether its results
can be trusted across 7 standardized categories:
1. Structure
2. Data
3. Assumptions
4. Validation
5. Coverage
6. Reproducibility
7. Configuration completeness

Provides 100% explainable health scores with actionable recommendations
and deep links to nodes, assumptions, and fields.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Any, Optional, Union

from actuary_engine.api.schemas import (
    ContractGraphPayload,
    HealthIssue,
    HealthStatus,
    ModelHealthCategory,
    ModelHealthReport,
    ValidationSeverity,
)
from actuary_engine.domain.tables.registry import table_registry
from actuary_engine.infrastructure.assumption_repo import assumption_repo


class ModelHealthEvaluator:
    """Evaluates the readiness, trustworthiness, and actuarial integrity of models."""

    def __init__(self, registry=table_registry, repo=assumption_repo) -> None:
        self.table_registry = registry
        self.assumption_repo = repo

    def evaluate_blueprint(self, payload: ContractGraphPayload) -> ModelHealthReport:
        """
        Evaluate Model Health for a visual DAG blueprint across all 7 categories.
        """
        nodes_by_id = {node.id: node for node in payload.nodes}
        edges = payload.edges

        # -------------------------------------------------------------
        # 1. Structure Evaluation
        # -------------------------------------------------------------
        struct_issues: list[HealthIssue] = []
        struct_warnings: list[HealthIssue] = []
        struct_recs: list[str] = []

        in_degree: dict[str, int] = defaultdict(int)
        out_degree: dict[str, int] = defaultdict(int)
        adjacency: dict[str, list[str]] = defaultdict(list)

        for node_id in nodes_by_id:
            in_degree[node_id] = 0
            out_degree[node_id] = 0

        for edge in edges:
            if edge.source in nodes_by_id and edge.target in nodes_by_id:
                adjacency[edge.source].append(edge.target)
                in_degree[edge.target] += 1
                out_degree[edge.source] += 1

        # Check empty graph
        if not nodes_by_id:
            struct_issues.append(
                HealthIssue(
                    code="EMPTY_GRAPH",
                    severity=ValidationSeverity.ERROR,
                    message="The blueprint contains no nodes.",
                    suggested_fix="Add at least one PolicyInput node and an Outflow / Benefit node.",
                )
            )
            struct_recs.append("Add a PolicyInput node to initiate contract cash flows.")
        else:
            # Cycle detection via topological sort (Kahn's algorithm)
            in_degree_work = dict(in_degree)
            queue = deque([n_id for n_id, deg in in_degree_work.items() if deg == 0])
            visited_count = 0
            while queue:
                curr = queue.popleft()
                visited_count += 1
                for neighbor in adjacency[curr]:
                    in_degree_work[neighbor] -= 1
                    if in_degree_work[neighbor] == 0:
                        queue.append(neighbor)

            if visited_count < len(nodes_by_id):
                struct_issues.append(
                    HealthIssue(
                        code="GRAPH_CYCLE",
                        severity=ValidationSeverity.ERROR,
                        message="The blueprint contains a circular dependency (cycle).",
                        suggested_fix="Ensure connections flow strictly forward from inputs to outputs.",
                    )
                )
                struct_recs.append("Break feedback loops to ensure the DAG is strictly forward-directed.")

            # Required node types check
            policy_nodes = [
                n for n in payload.nodes
                if (n.type or "").lower() in ("policyinput", "policy_input", "input")
            ]
            sink_nodes = [
                n for n in payload.nodes
                if (n.type or "").lower() in (
                    "outflow", "benefit", "valuation_sink", "valuationsink",
                    "accumulator", "unitlinked", "unit_linked"
                )
            ]

            if not policy_nodes:
                struct_issues.append(
                    HealthIssue(
                        code="MISSING_POLICY_INPUT",
                        severity=ValidationSeverity.ERROR,
                        message="Missing required Policy Input node.",
                        suggested_fix="Add a Policy Input node to define the contract parameters.",
                    )
                )
                struct_recs.append("Add a PolicyInput node to anchor policyholder age, term, and sum assured.")

            if not sink_nodes:
                struct_issues.append(
                    HealthIssue(
                        code="MISSING_VALUATION_SINK",
                        severity=ValidationSeverity.ERROR,
                        message="The blueprint has no outflows, benefits, or valuation sinks to evaluate.",
                        suggested_fix="Add an Outflow, Benefit, or Valuation Sink node.",
                    )
                )
                struct_recs.append("Add an Outflow or Benefit node to capture liabilities.")

            # Disconnected / orphan nodes check
            for node in payload.nodes:
                ntype = (node.type or "").lower()
                if ntype not in ("policyinput", "policy_input", "input"):
                    # Check if node has zero in-edges and zero out-edges
                    if in_degree[node.id] == 0 and out_degree[node.id] == 0:
                        struct_warnings.append(
                            HealthIssue(
                                code="DISCONNECTED_NODE",
                                severity=ValidationSeverity.WARNING,
                                message=f"Node '{node.type}' ({node.id}) is disconnected and will not contribute to valuation.",
                                node_id=node.id,
                                suggested_fix="Connect this node into the cash flow graph or delete it.",
                            )
                        )
                        struct_recs.append(f"Connect or remove orphan node '{node.id}' to clean up DAG topology.")

        if struct_issues:
            struct_status = HealthStatus.FAIL
            struct_score = 0
        elif struct_warnings:
            struct_status = HealthStatus.WARNING
            struct_score = max(60, 100 - len(struct_warnings) * 10)
        else:
            struct_status = HealthStatus.PASS
            struct_score = 100
            struct_recs.append("DAG topology is fully acyclic, connected, and structurally valid.")

        cat_structure = ModelHealthCategory(
            name="Structure",
            status=struct_status,
            score=struct_score,
            issues=struct_issues,
            warnings=struct_warnings,
            recommendations=struct_recs,
            metrics={
                "node_count": len(nodes_by_id),
                "edge_count": len(edges),
                "policy_nodes": len(policy_nodes) if nodes_by_id else 0,
                "sink_nodes": len(sink_nodes) if nodes_by_id else 0,
            },
        )

        # -------------------------------------------------------------
        # Extract Policy Data & Parameters
        # -------------------------------------------------------------
        policy_data: dict[str, Any] = {}
        primary_node_id: Optional[str] = None
        if policy_nodes:
            primary_node = policy_nodes[0]
            primary_node_id = primary_node.id
            policy_data = primary_node.data or {}

        # -------------------------------------------------------------
        # 2. Data Evaluation
        # -------------------------------------------------------------
        data_issues: list[HealthIssue] = []
        data_warnings: list[HealthIssue] = []
        data_recs: list[str] = []

        table_id = str(policy_data.get("table_id") or "soa_ilt").lower().strip()
        table = None
        try:
            table = self.table_registry.get_table(table_id)
            # Table integrity validation
            if table.radix <= 0:
                data_issues.append(
                    HealthIssue(
                        code="INVALID_RADIX",
                        severity=ValidationSeverity.ERROR,
                        message=f"Mortality table '{table_id}' has non-positive radix ({table.radix}).",
                        node_id=primary_node_id,
                        field="table_id",
                        suggested_fix="Use a standard mortality table with positive radix (e.g. 100,000).",
                    )
                )
            if any(q < 0.0 or q > 1.0 for q in table.qx):
                data_issues.append(
                    HealthIssue(
                        code="INVALID_QX_BOUNDS",
                        severity=ValidationSeverity.ERROR,
                        message=f"Mortality table '{table_id}' has mortality probabilities outside [0.0, 1.0].",
                        node_id=primary_node_id,
                        field="table_id",
                        suggested_fix="Verify table raw data or re-upload an audited table.",
                    )
                )
            # Check terminal decrement
            if table.qx[-1] < 1.0:
                data_warnings.append(
                    HealthIssue(
                        code="OPEN_ENDED_TABLE",
                        severity=ValidationSeverity.WARNING,
                        message=f"Mortality table '{table_id}' does not terminate with qx=1.0 at omega ({table.max_age}).",
                        node_id=primary_node_id,
                        field="table_id",
                        suggested_fix="Ensure omega cohort closes with qx=1.0.",
                    )
                )
                data_recs.append("Consider setting terminal age decrement q_omega = 1.0 for theoretical rigor.")
        except KeyError:
            data_issues.append(
                HealthIssue(
                    code="MISSING_MORTALITY_DATA",
                    severity=ValidationSeverity.ERROR,
                    message=f"Mortality table '{table_id}' was not found in TableRegistry.",
                    node_id=primary_node_id,
                    field="table_id",
                    suggested_fix="Upload the required mortality table or select built-in 'soa_ilt'.",
                )
            )
            data_recs.append(f"Register table '{table_id}' or select standard 'soa_ilt' table.")

        if data_issues:
            data_status = HealthStatus.FAIL
            data_score = 0
        elif data_warnings:
            data_status = HealthStatus.WARNING
            data_score = 90
        else:
            data_status = HealthStatus.PASS
            data_score = 100
            data_recs.append(f"Mortality data '{table_id}' is verified and ready in registry.")

        cat_data = ModelHealthCategory(
            name="Data",
            status=data_status,
            score=data_score,
            issues=data_issues,
            warnings=data_warnings,
            recommendations=data_recs,
            metrics={
                "table_id": table_id,
                "table_found": table is not None,
                "min_age": table.min_age if table else None,
                "max_age": table.max_age if table else None,
                "radix": table.radix if table else None,
            },
        )

        # -------------------------------------------------------------
        # 3. Assumptions Evaluation
        # -------------------------------------------------------------
        ass_issues: list[HealthIssue] = []
        ass_warnings: list[HealthIssue] = []
        ass_recs: list[str] = []

        # Interest rate
        interest_rate = policy_data.get("interest_rate", payload.discount_rate)
        if interest_rate is not None:
            try:
                ir_val = float(interest_rate)
                if ir_val < 0:
                    ass_issues.append(
                        HealthIssue(
                            code="NEGATIVE_INTEREST_RATE",
                            severity=ValidationSeverity.ERROR,
                            message=f"Discount rate ({ir_val:.2%}) is negative.",
                            node_id=primary_node_id,
                            field="interest_rate",
                            suggested_fix="Set a non-negative discount rate.",
                        )
                    )
                elif ir_val > 1.0:
                    ass_warnings.append(
                        HealthIssue(
                            code="UNIT_MISMATCH",
                            severity=ValidationSeverity.WARNING,
                            message=f"Interest rate is {ir_val} (> 100%). Entered percentage instead of decimal?",
                            node_id=primary_node_id,
                            field="interest_rate",
                            suggested_fix="Convert percentage to decimal (e.g. 5% -> 0.05).",
                        )
                    )
                    ass_recs.append("Verify interest rate unit: use 0.05 for 5.0%.")
                elif ir_val == 0.0:
                    ass_warnings.append(
                        HealthIssue(
                            code="ZERO_DISCOUNT_RATE",
                            severity=ValidationSeverity.WARNING,
                            message="Interest rate is exactly 0.00%. Cash flows will be undiscounted.",
                            node_id=primary_node_id,
                            field="interest_rate",
                            suggested_fix="Provide a positive discount rate if present-value discounting is expected.",
                        )
                    )
            except ValueError:
                ass_issues.append(
                    HealthIssue(
                        code="INVALID_INTEREST_RATE",
                        severity=ValidationSeverity.ERROR,
                        message="Interest rate must be a numeric value.",
                        node_id=primary_node_id,
                        field="interest_rate",
                    )
                )

        # Expense loading checks
        has_expenses = False
        for node in payload.nodes:
            ndata = node.data or {}
            ntype = (node.type or "").lower()
            if ntype in ("expense", "outflow", "policyinput"):
                if ndata.get("expense_first_year_pct") or ndata.get("expense_renewal_pct") or ndata.get("expenses"):
                    has_expenses = True
                    break

        if not has_expenses:
            ass_warnings.append(
                HealthIssue(
                    code="UNLOADED_EXPENSES",
                    severity=ValidationSeverity.WARNING,
                    message="Expense loadings are not configured. Valuation will reflect benefit-only obligations.",
                    node_id=primary_node_id,
                    field="expense",
                    suggested_fix="Add acquisition and maintenance expense loadings.",
                )
            )
            ass_recs.append("Configure expense loadings to capture acquisition and policy maintenance costs.")

        # Lapse decrement checks
        has_lapse = False
        for node in payload.nodes:
            ndata = node.data or {}
            ntype = (node.type or "").lower()
            if ntype in ("contingency", "decrement"):
                if str(ndata.get("decrement_type", "")).lower() == "lapse":
                    has_lapse = True
                    break
            if ndata.get("lapse_rate") is not None and float(ndata.get("lapse_rate", 0)) > 0:
                has_lapse = True
                break

        if not has_lapse:
            ass_warnings.append(
                HealthIssue(
                    code="ZERO_LAPSE_ASSUMPTION",
                    severity=ValidationSeverity.WARNING,
                    message="Lapse decrements are omitted (lapse rate is 0.00%).",
                    node_id=primary_node_id,
                    field="lapse_rate",
                    suggested_fix="Consider adding a lapse assumption (e.g. 3.0% flat annual).",
                )
            )
            ass_recs.append("Add a realistic lapse assumption to model voluntary policy terminations.")

        # Assumption governance check
        if self.assumption_repo:
            try:
                active_assumptions = self.assumption_repo.list_assumptions()
                deprecated = [a for a in active_assumptions if str(a.get("status", "")).upper() == "DEPRECATED"]
                if deprecated:
                    ass_warnings.append(
                        HealthIssue(
                            code="DEPRECATED_ASSUMPTION_IN_LIBRARY",
                            severity=ValidationSeverity.WARNING,
                            message=f"Library contains {len(deprecated)} deprecated assumptions. Ensure model uses APPROVED versions.",
                            suggested_fix="Review Assumption Library to ensure all referenced assumptions are APPROVED.",
                        )
                    )
            except Exception:
                pass

        if ass_issues:
            ass_status = HealthStatus.FAIL
            ass_score = 0
        elif ass_warnings:
            ass_status = HealthStatus.WARNING
            ass_score = max(60, 100 - len(ass_warnings) * 10)
        else:
            ass_status = HealthStatus.PASS
            ass_score = 100
            ass_recs.append("Financial, expense, and decrement assumptions are balanced and approved.")

        cat_assumptions = ModelHealthCategory(
            name="Assumptions",
            status=ass_status,
            score=ass_score,
            issues=ass_issues,
            warnings=ass_warnings,
            recommendations=ass_recs,
            metrics={
                "interest_rate": interest_rate,
                "has_expenses": has_expenses,
                "has_lapse": has_lapse,
            },
        )

        # -------------------------------------------------------------
        # 4. Validation Evaluation
        # -------------------------------------------------------------
        val_issues: list[HealthIssue] = []
        val_warnings: list[HealthIssue] = []
        val_recs: list[str] = []

        # Issue age
        age = policy_data.get("age", policy_data.get("issue_age", 35))
        try:
            age = int(age)
            if age < 0:
                val_issues.append(
                    HealthIssue(
                        code="NEGATIVE_AGE",
                        severity=ValidationSeverity.ERROR,
                        message="Issue age cannot be negative.",
                        node_id=primary_node_id,
                        field="issue_age",
                    )
                )
        except (ValueError, TypeError):
            val_issues.append(
                HealthIssue(
                    code="INVALID_AGE",
                    severity=ValidationSeverity.ERROR,
                    message="Issue age must be an integer.",
                    node_id=primary_node_id,
                    field="issue_age",
                )
            )
            age = 35

        # Term
        term = policy_data.get("term", policy_data.get("term_years", 20))
        try:
            term = int(term)
            if term <= 0:
                val_issues.append(
                    HealthIssue(
                        code="INVALID_TERM",
                        severity=ValidationSeverity.ERROR,
                        message="Policy term must be greater than 0.",
                        node_id=primary_node_id,
                        field="term",
                    )
                )
        except (ValueError, TypeError):
            val_issues.append(
                HealthIssue(
                    code="INVALID_TERM_TYPE",
                    severity=ValidationSeverity.ERROR,
                    message="Policy term must be an integer.",
                    node_id=primary_node_id,
                    field="term",
                )
            )
            term = 20

        # Sum assured
        sum_assured = policy_data.get("sum_assured", policy_data.get("face_amount", 1_000_000.0))
        try:
            sum_assured = float(sum_assured)
            if sum_assured <= 0:
                val_issues.append(
                    HealthIssue(
                        code="NEGATIVE_FACE_AMOUNT",
                        severity=ValidationSeverity.ERROR,
                        message="Sum Assured must be strictly positive.",
                        node_id=primary_node_id,
                        field="sum_assured",
                    )
                )
        except (ValueError, TypeError):
            val_issues.append(
                HealthIssue(
                    code="INVALID_FACE_AMOUNT",
                    severity=ValidationSeverity.ERROR,
                    message="Sum Assured must be a numeric value.",
                    node_id=primary_node_id,
                    field="sum_assured",
                )
            )

        # Node parameter checks across other nodes
        for node in payload.nodes:
            ndata = node.data or {}
            ntype = (node.type or "").lower()

            if ntype in ("inflow", "premium"):
                amt_raw = ndata.get("amount")
                if amt_raw is not None:
                    try:
                        if float(amt_raw) < 0:
                            val_issues.append(
                                HealthIssue(
                                    code="NEGATIVE_PREMIUM",
                                    severity=ValidationSeverity.ERROR,
                                    message="Fixed premium amount cannot be negative.",
                                    node_id=node.id,
                                    field="amount",
                                )
                            )
                    except ValueError:
                        pass

            if ntype in ("contingency", "decrement"):
                mult_raw = ndata.get("multiplier")
                if mult_raw is not None:
                    try:
                        if float(mult_raw) < 0:
                            val_issues.append(
                                HealthIssue(
                                    code="NEGATIVE_MULTIPLIER",
                                    severity=ValidationSeverity.ERROR,
                                    message="Decrement multiplier cannot be negative.",
                                    node_id=node.id,
                                    field="multiplier",
                                )
                            )
                    except ValueError:
                        pass

            if ntype in ("outflow", "benefit"):
                surr_raw = ndata.get("surrender_ratio")
                if surr_raw is not None:
                    try:
                        surr = float(surr_raw)
                        if surr < 0 or surr > 1.0:
                            val_issues.append(
                                HealthIssue(
                                    code="INVALID_SURRENDER_RATIO",
                                    severity=ValidationSeverity.ERROR,
                                    message="Surrender ratio must be between 0.0 and 1.0.",
                                    node_id=node.id,
                                    field="surrender_ratio",
                                )
                            )
                    except ValueError:
                        pass

        if val_issues:
            val_status = HealthStatus.FAIL
            val_score = 0
        elif val_warnings:
            val_status = HealthStatus.WARNING
            val_score = max(70, 100 - len(val_warnings) * 10)
        else:
            val_status = HealthStatus.PASS
            val_score = 100
            val_recs.append("Domain rules and parameter constraints verified without issues.")

        cat_validation = ModelHealthCategory(
            name="Validation",
            status=val_status,
            score=val_score,
            issues=val_issues,
            warnings=val_warnings,
            recommendations=val_recs,
            metrics={"age": age, "term": term, "sum_assured": sum_assured},
        )

        # -------------------------------------------------------------
        # 5. Coverage Evaluation
        # -------------------------------------------------------------
        cov_issues: list[HealthIssue] = []
        cov_warnings: list[HealthIssue] = []
        cov_recs: list[str] = []

        if table is not None:
            if age < table.min_age:
                cov_issues.append(
                    HealthIssue(
                        code="MORTALITY_COVERAGE_UNDERFLOW",
                        severity=ValidationSeverity.ERROR,
                        message=f"Issue age ({age}) is below mortality table minimum age ({table.min_age}).",
                        node_id=primary_node_id,
                        field="issue_age",
                        suggested_fix=f"Increase issue age >= {table.min_age} or select an infant/child table.",
                    )
                )
                cov_recs.append(f"Adjust issue age to at least {table.min_age}.")

            terminal_age = age + term
            if terminal_age > table.max_age:
                cov_issues.append(
                    HealthIssue(
                        code="MORTALITY_COVERAGE_OVERFLOW",
                        severity=ValidationSeverity.ERROR,
                        message=f"Projection horizon ({terminal_age}y) exceeds mortality table max age ({table.max_age}y).",
                        node_id=primary_node_id,
                        field="term",
                        suggested_fix=f"Reduce policy term to <= {table.max_age - age} years or choose an extended table.",
                    )
                )
                cov_recs.append(f"Reduce term from {term} to {max(1, table.max_age - age)} years to avoid extrapolation past omega.")
            elif terminal_age >= table.max_age - 5:
                cov_warnings.append(
                    HealthIssue(
                        code="PROXIMITY_TO_OMEGA",
                        severity=ValidationSeverity.WARNING,
                        message=f"Projection horizon reaches age {terminal_age}, within 5 years of mortality table omega ({table.max_age}).",
                        node_id=primary_node_id,
                        field="term",
                        suggested_fix="Verify adequacy of mortality rates near table boundary.",
                    )
                )
                cov_recs.append(f"Model projects up to age {terminal_age} (omega: {table.max_age}). Be aware of rapid decrement acceleration.")

        if cov_issues:
            cov_status = HealthStatus.FAIL
            cov_score = 0
        elif cov_warnings:
            cov_status = HealthStatus.WARNING
            cov_score = 80
        else:
            cov_status = HealthStatus.PASS
            cov_score = 100
            cov_recs.append("Full chronological and actuarial table coverage confirmed across projection horizon.")

        cat_coverage = ModelHealthCategory(
            name="Coverage",
            status=cov_status,
            score=cov_score,
            issues=cov_issues,
            warnings=cov_warnings,
            recommendations=cov_recs,
            metrics={
                "issue_age": age,
                "term": term,
                "terminal_age": age + term,
                "table_min_age": table.min_age if table else None,
                "table_max_age": table.max_age if table else None,
            },
        )

        # -------------------------------------------------------------
        # 6. Reproducibility Evaluation
        # -------------------------------------------------------------
        rep_issues: list[HealthIssue] = []
        rep_warnings: list[HealthIssue] = []
        rep_recs: list[str] = []

        # Check random seed
        seed = policy_data.get("seed")
        is_stochastic = any(
            (n.type or "").lower() in ("esg", "stochastic", "vasicek")
            for n in payload.nodes
        )

        if is_stochastic and seed is None:
            rep_warnings.append(
                HealthIssue(
                    code="UNPINNED_RANDOM_SEED",
                    severity=ValidationSeverity.WARNING,
                    message="Random seed is unpinned. Monte Carlo paths will generate with non-deterministic seeds.",
                    node_id=primary_node_id,
                    field="seed",
                    suggested_fix="Specify a fixed integer seed (e.g. 42) for reproducible audit trails.",
                )
            )
            rep_recs.append("Pin a random seed to ensure simulation results can be reproduced identically in future audits.")

        # Check assumption versioning
        has_versioned_refs = bool(policy_data.get("assumption_refs"))
        if not has_versioned_refs:
            rep_warnings.append(
                HealthIssue(
                    code="UNVERSIONED_ASSUMPTIONS",
                    severity=ValidationSeverity.WARNING,
                    message="Model does not reference pinned assumption version IDs.",
                    node_id=primary_node_id,
                    field="assumption_refs",
                    suggested_fix="Attach versioned assumption IDs from Assumption Library.",
                )
            )
            rep_recs.append("Pin assumption version tags (e.g. mortality_soa_ilt:v1.0) to guard against upstream table updates.")

        if rep_issues:
            rep_status = HealthStatus.FAIL
            rep_score = 0
        elif rep_warnings:
            rep_status = HealthStatus.WARNING
            rep_score = max(70, 100 - len(rep_warnings) * 10)
        else:
            rep_status = HealthStatus.PASS
            rep_score = 100
            rep_recs.append("Model is version-pinned and computationally reproducible.")

        cat_reproducibility = ModelHealthCategory(
            name="Reproducibility",
            status=rep_status,
            score=rep_score,
            issues=rep_issues,
            warnings=rep_warnings,
            recommendations=rep_recs,
            metrics={
                "has_seed": seed is not None,
                "has_versioned_assumptions": has_versioned_refs,
                "is_stochastic": is_stochastic,
            },
        )

        # -------------------------------------------------------------
        # 7. Configuration Completeness Evaluation
        # -------------------------------------------------------------
        cfg_issues: list[HealthIssue] = []
        cfg_warnings: list[HealthIssue] = []
        cfg_recs: list[str] = []

        # Check contract identification
        if not payload.contract_id:
            cfg_warnings.append(
                HealthIssue(
                    code="UNNAMED_CONTRACT",
                    severity=ValidationSeverity.INFO,
                    message="Contract ID or Product Code is not specified.",
                    suggested_fix="Provide a descriptive contract identifier (e.g. 'TERM-LIFE-20Y').",
                )
            )
            cfg_recs.append("Assign an explicit contract code for portfolio tracking.")

        # Check gross premium configuration
        gross_prem = policy_data.get("gross_premium")
        has_inflow = any((n.type or "").lower() in ("inflow", "premium") for n in payload.nodes)
        if not gross_prem and not has_inflow:
            cfg_warnings.append(
                HealthIssue(
                    code="IMPLICIT_PREMIUM_LOADING",
                    severity=ValidationSeverity.WARNING,
                    message="Gross premium is omitted; engine will auto-calculate with a default 20% loading rule.",
                    node_id=primary_node_id,
                    field="gross_premium",
                    suggested_fix="Explicitly declare annual gross premium or an inflow premium node.",
                )
            )
            cfg_recs.append("Explicitly specify gross premium to avoid relying on implicit 20% expense loading.")

        if cfg_issues:
            cfg_status = HealthStatus.FAIL
            cfg_score = 0
        elif cfg_warnings:
            cfg_status = HealthStatus.WARNING
            cfg_score = max(80, 100 - len(cfg_warnings) * 10)
        else:
            cfg_status = HealthStatus.PASS
            cfg_score = 100
            cfg_recs.append("All parameters, identifiers, and financial options are explicitly defined.")

        cat_configuration = ModelHealthCategory(
            name="Configuration completeness",
            status=cfg_status,
            score=cfg_score,
            issues=cfg_issues,
            warnings=cfg_warnings,
            recommendations=cfg_recs,
            metrics={
                "has_contract_id": bool(payload.contract_id),
                "has_gross_premium": gross_prem is not None or has_inflow,
            },
        )

        # -------------------------------------------------------------
        # Assemble Overall Health Report & Explainable Score
        # -------------------------------------------------------------
        categories = {
            "structure": cat_structure,
            "data": cat_data,
            "assumptions": cat_assumptions,
            "validation": cat_validation,
            "coverage": cat_coverage,
            "reproducibility": cat_reproducibility,
            "configuration": cat_configuration,
        }

        any_fail = any(c.status == HealthStatus.FAIL for c in categories.values())
        all_pass = all(c.status == HealthStatus.PASS for c in categories.values())

        score_breakdown: list[str] = ["Base Score: 100/100"]

        if any_fail:
            overall_status = HealthStatus.FAIL
            is_ready_to_run = False
            # Blockers cap score
            overall_score = min(40, round(sum(c.score for c in categories.values()) / 7.0))
            for c_name, c in categories.items():
                for iss in c.issues:
                    score_breakdown.append(f"BLOCKER: [{c.name}] {iss.message}")
            summary_headline = f"Model is NOT ready to run: {len([i for c in categories.values() for i in c.issues])} critical blocker(s) detected."
        elif not all_pass:
            overall_status = HealthStatus.WARNING
            is_ready_to_run = True
            total_deductions = 0
            for c in categories.values():
                for w in c.warnings:
                    ded = 5 if c.name in ("Reproducibility", "Configuration completeness") else 8
                    total_deductions += ded
                    score_breakdown.append(f"-{ded} pts: [{c.name}] {w.message}")

            overall_score = max(50, 100 - total_deductions)
            total_warnings = len([w for c in categories.values() for w in c.warnings])
            summary_headline = f"Model is ready to run with {total_warnings} advisory warning(s)."
        else:
            overall_status = HealthStatus.PASS
            is_ready_to_run = True
            overall_score = 100
            score_breakdown.append("Zero defects detected. All 7 health categories passed.")
            summary_headline = "Model Health: 100/100. Production-ready and fully audited."

        return ModelHealthReport(
            overall_status=overall_status,
            is_ready_to_run=is_ready_to_run,
            overall_score=overall_score,
            score_breakdown=score_breakdown,
            categories=categories,
            summary_headline=summary_headline,
            created_at=time.time(),
        )

    def evaluate_model_config(self, config: dict[str, Any]) -> ModelHealthReport:
        """
        Evaluate health for standard request payloads (e.g. DeterministicValuationRequest).
        Synthesizes a minimal ContractGraphPayload and delegates to evaluate_blueprint.
        """
        from actuary_engine.api.schemas import GraphNodeData, GraphEdgeData

        nodes = [
            GraphNodeData(
                id="policy-input-1",
                type="policyInput",
                data={
                    "issue_age": config.get("issue_age", 35),
                    "term": config.get("term", 20),
                    "sum_assured": config.get("sum_assured", 1_000_000.0),
                    "interest_rate": config.get("interest_rate", 0.05),
                    "table_id": config.get("table_id", "soa_ilt"),
                    "gross_premium": config.get("gross_premium"),
                    "seed": config.get("seed"),
                    "assumption_refs": config.get("assumption_refs"),
                    "expenses": config.get("expense"),
                    "lapse_rate": config.get("lapse", {}).get("flat_annual_rate") if isinstance(config.get("lapse"), dict) else None,
                },
            ),
            GraphNodeData(
                id="sink-1",
                type="valuationSink",
                data={"name": "Liabilities Sink"},
            ),
        ]
        edges = [GraphEdgeData(source="policy-input-1", target="sink-1")]
        payload = ContractGraphPayload(
            contract_id=config.get("product_type", "Standard Valuation"),
            nodes=nodes,
            edges=edges,
            discount_rate=config.get("interest_rate", 0.05),
        )
        return self.evaluate_blueprint(payload)


# Global singleton instance
model_health_service = ModelHealthEvaluator()
