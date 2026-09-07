"""
Domain-Aware Actuarial Validation for Blueprint Models.
"""

from collections import defaultdict, deque
from typing import Any, Optional

from actuary_engine.api.schemas import (
    ContractGraphPayload,
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
)
from actuary_engine.tables.registry import table_registry


class BlueprintValidator:
    """Validates structural, temporal, financial, and data integrity of Actura blueprints."""

    def __init__(self, table_lookup: Optional[Any] = None) -> None:
        self.table_registry = table_lookup or table_registry

    def validate(self, payload: ContractGraphPayload) -> ValidationResult:
        """Perform comprehensive validation on the given contract graph."""
        issues: list[ValidationIssue] = []

        nodes_by_id = {node.id: node for node in payload.nodes}
        if not nodes_by_id:
            issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    code="EMPTY_GRAPH",
                    message="The contract blueprint is empty.",
                    suggested_fix="Add at least one PolicyInput node.",
                )
            )
            return ValidationResult(is_valid=False, issues=issues)

        # 1. Structural Checks
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
            issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    code="GRAPH_CYCLE",
                    message="The blueprint contains a cycle or circular dependency.",
                    suggested_fix="Ensure the connections flow in a single direction (DAG).",
                )
            )

        policy_nodes = []
        outflow_nodes = []
        for node in payload.nodes:
            ntype = (node.type or "").lower()
            if ntype in ("policyinput", "policy_input", "input"):
                policy_nodes.append(node)
            elif ntype in ("outflow", "benefit", "valuation_sink", "valuationsink", "accumulator", "unitlinked", "unit_linked"):
                outflow_nodes.append(node)
                
            # Disconnected nodes check
            if ntype not in ("policyinput", "policy_input", "input"):
                if in_degree[node.id] == 0 and len(adjacency[node.id]) == 0:
                    issues.append(
                        ValidationIssue(
                            severity=ValidationSeverity.WARNING,
                            code="DISCONNECTED_NODE",
                            message=f"Node '{node.type}' is disconnected and will be ignored.",
                            node_id=node.id,
                            suggested_fix="Connect this node to the model or delete it.",
                        )
                    )

        if not policy_nodes:
            issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    code="MISSING_POLICY_INPUT",
                    message="Missing required Policy Input node.",
                    suggested_fix="Add a Policy Input node to define the contract base parameters.",
                )
            )

        if not outflow_nodes:
            issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    code="MISSING_VALUATION_SINK",
                    message="The blueprint has no outflows or benefits to value.",
                    suggested_fix="Add an Outflow, Benefit, or Accumulator node.",
                )
            )

        # Extrapolate policy metadata for Temporal, Data, Financial checks
        if policy_nodes:
            policy_node = policy_nodes[0]
            data = policy_node.data
            
            age = data.get("age") or data.get("issue_age")
            if age is None:
                age = 35 # fallback
            else:
                try:
                    age = int(age)
                except ValueError:
                    issues.append(ValidationIssue(
                        severity=ValidationSeverity.ERROR, 
                        code="INVALID_AGE", 
                        message="Issue age must be an integer.", 
                        node_id=policy_node.id
                    ))
                    age = 35

            term = data.get("term") or data.get("term_years")
            if term is None:
                term = 20
            else:
                try:
                    term = int(term)
                except ValueError:
                    issues.append(ValidationIssue(
                        severity=ValidationSeverity.ERROR, 
                        code="INVALID_TERM", 
                        message="Term must be an integer.", 
                        node_id=policy_node.id
                    ))
                    term = 20

            sum_assured = data.get("sum_assured") or data.get("face_amount")
            if sum_assured is None:
                sum_assured = 1_000_000.0
            else:
                try:
                    sum_assured = float(sum_assured)
                    if sum_assured <= 0:
                        issues.append(ValidationIssue(
                            severity=ValidationSeverity.ERROR, 
                            code="NEGATIVE_FACE_AMOUNT", 
                            message="Sum Assured must be strictly positive.", 
                            node_id=policy_node.id
                        ))
                except ValueError:
                    issues.append(ValidationIssue(
                        severity=ValidationSeverity.ERROR, 
                        code="INVALID_FACE_AMOUNT", 
                        message="Sum Assured must be a number.", 
                        node_id=policy_node.id
                    ))
                    sum_assured = 1_000_000.0

            interest_rate = data.get("interest_rate")
            if interest_rate is not None:
                try:
                    ir_val = float(interest_rate)
                    if ir_val < 0:
                        issues.append(ValidationIssue(
                            severity=ValidationSeverity.WARNING, 
                            code="NEGATIVE_INTEREST_RATE", 
                            message="Interest rate is negative. Verify if this is intended.", 
                            node_id=policy_node.id
                        ))
                    elif ir_val > 1.0:
                        issues.append(ValidationIssue(
                            severity=ValidationSeverity.WARNING, 
                            code="UNIT_MISMATCH", 
                            message="Interest rate > 100%. Did you enter a percentage instead of a decimal?", 
                            node_id=policy_node.id
                        ))
                except ValueError:
                    pass

            # Data and Temporal Checks
            table_id = str(data.get("table_id", "soa_ilt")).lower().strip()
            try:
                table = self.table_registry.get_table(table_id)
                
                if age < table.min_age:
                    issues.append(
                        ValidationIssue(
                            severity=ValidationSeverity.ERROR,
                            code="MORTALITY_COVERAGE",
                            message=f"Issue age ({age}) is below mortality table minimum age ({table.min_age}).",
                            node_id=policy_node.id,
                            suggested_fix="Increase issue age or select a table that covers lower ages.",
                        )
                    )
                if age + term > table.max_age:
                    issues.append(
                        ValidationIssue(
                            severity=ValidationSeverity.ERROR,
                            code="MORTALITY_COVERAGE",
                            message=f"Projection horizon ends at age {age + term}, exceeding table max age ({table.max_age}).",
                            node_id=policy_node.id,
                            suggested_fix="Reduce the term or select a table with a higher maximum age.",
                        )
                    )
            except KeyError:
                issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        code="MISSING_MORTALITY_DATA",
                        message=f"Mortality table '{table_id}' not found in registry.",
                        node_id=policy_node.id,
                        suggested_fix="Upload the required table or select a built-in table like 'soa_ilt'.",
                    )
                )

        # Evaluate Inflow / Premium and Contingency Nodes
        for node in payload.nodes:
            ntype = (node.type or "").lower()
            ndata = node.data
            
            if ntype in ("inflow", "premium"):
                mode = str(ndata.get("mode", "fixed")).lower()
                amt_raw = ndata.get("amount")
                if mode == "fixed" and amt_raw is not None:
                    try:
                        amt = float(amt_raw)
                        if amt < 0:
                            issues.append(
                                ValidationIssue(
                                    severity=ValidationSeverity.ERROR,
                                    code="NEGATIVE_PREMIUM",
                                    message="Fixed premium amount cannot be negative.",
                                    node_id=node.id,
                                    suggested_fix="Set a positive premium amount."
                                )
                            )
                    except ValueError:
                        pass
            
            if ntype in ("contingency", "decrement"):
                dtype = str(ndata.get("decrement_type", "")).lower()
                if not dtype:
                    issues.append(
                        ValidationIssue(
                            severity=ValidationSeverity.WARNING,
                            code="MISSING_DECREMENT_TYPE",
                            message="Decrement type is not configured.",
                            node_id=node.id,
                            suggested_fix="Select a decrement type (e.g., Mortality, Lapse)."
                        )
                    )
                mult_raw = ndata.get("multiplier")
                if mult_raw is not None:
                    try:
                        mult = float(mult_raw)
                        if mult < 0:
                            issues.append(
                                ValidationIssue(
                                    severity=ValidationSeverity.ERROR,
                                    code="NEGATIVE_MULTIPLIER",
                                    message="Decrement multiplier cannot be negative.",
                                    node_id=node.id,
                                    suggested_fix="Set the multiplier to a positive value (e.g., 1.0)."
                                )
                            )
                    except ValueError:
                        pass
            
            if ntype in ("outflow", "benefit"):
                formula = str(ndata.get("formula", "")).lower()
                btype = str(ndata.get("benefit_type", "")).lower()
                if "surrender" in formula or "surrender" in btype:
                    surr_raw = ndata.get("surrender_ratio")
                    if surr_raw is not None:
                        try:
                            surr = float(surr_raw)
                            if surr > 1.0:
                                issues.append(
                                    ValidationIssue(
                                        severity=ValidationSeverity.WARNING,
                                        code="UNIT_MISMATCH",
                                        message="Surrender ratio > 1.0. Did you enter a percentage instead of a decimal?",
                                        node_id=node.id,
                                        suggested_fix="Convert percentage to decimal (e.g., 80% -> 0.80)."
                                    )
                                )
                            if surr < 0:
                                issues.append(
                                    ValidationIssue(
                                        severity=ValidationSeverity.ERROR,
                                        code="NEGATIVE_RATIO",
                                        message="Surrender ratio cannot be negative.",
                                        node_id=node.id,
                                        suggested_fix="Set the surrender ratio between 0.0 and 1.0."
                                    )
                                )
                        except ValueError:
                            pass

        is_valid = not any(issue.severity == ValidationSeverity.ERROR for issue in issues)
        return ValidationResult(is_valid=is_valid, issues=issues)
