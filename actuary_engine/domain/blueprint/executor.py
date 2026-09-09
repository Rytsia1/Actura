from collections import defaultdict, deque
from typing import Any, Dict, List

import numpy as np

from actuary_engine.api.schemas import ContractGraphPayload, GraphEdgeData, GraphNodeData
from actuary_engine.domain.blueprint.exceptions import BlueprintExecutionError
from actuary_engine.domain.blueprint.models import Blueprint, Node, NodeType
from actuary_engine.domain.tables.mortality_table import MortalityTable
from actuary_engine.valuation.graph_parser import ContractGraphSimulator


class BlueprintExecutor:
    """Executes a validated Blueprint by either evaluating mathematical nodes or adapting to ContractGraphSimulator."""

    def __init__(self, blueprint: Blueprint):
        self.blueprint = blueprint
        self.context: Dict[str, Dict[str, Any]] = {}
        self.node_map = {node.id: node for node in blueprint.nodes}

    def _is_math_dag(self) -> bool:
        math_types = {
            NodeType.MORTALITY,
            NodeType.SURVIVAL,
            NodeType.BENEFIT,
            NodeType.DISCOUNT,
            NodeType.CASHFLOW,
            NodeType.OUTPUT,
        }
        return any(node.type in math_types for node in self.blueprint.nodes)

    def _topological_sort(self) -> List[str]:
        """Kahn's algorithm for topological sorting."""
        in_degree = {nid: 0 for nid in self.node_map}
        adj_list: Dict[str, List[str]] = {nid: [] for nid in self.node_map}

        for edge in self.blueprint.edges:
            adj_list[edge.source].append(edge.target)
            in_degree[edge.target] += 1

        queue = deque([nid for nid in in_degree if in_degree[nid] == 0])
        order: List[str] = []

        while queue:
            node_id = queue.popleft()
            order.append(node_id)
            for neighbor in adj_list[node_id]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(order) != len(self.node_map):
            raise BlueprintExecutionError("Failed to sort nodes topologically (graph may contain cycles).")

        return order

    def _get_input_data(self, target_id: str) -> Dict[str, Any]:
        """Gather all outputs from nodes that target this node."""
        inputs: Dict[str, Any] = {}
        for edge in self.blueprint.edges:
            if edge.target == target_id:
                if edge.source in self.context:
                    src_output = self.context[edge.source]
                    if edge.source_handle and edge.target_handle:
                        inputs[edge.target_handle] = src_output.get(edge.source_handle)
                    else:
                        inputs.update(src_output)
        return inputs

    def _execute_math_node(self, node: Node) -> None:
        """Execute logic based on node type for mathematical blueprint DAGs."""
        inputs = self._get_input_data(node.id)
        params = {**node.config, **inputs}
        output: Dict[str, Any] = {}

        if node.type in (NodeType.INPUT, NodeType.POLICY_INPUT):
            output = node.config.copy()
            if "age" in output:
                output["age"] = int(output["age"])

        elif node.type == NodeType.PREMIUM:
            output = {"premium": params.get("premium_amount", 0.0)}

        elif node.type == NodeType.EXPENSE:
            output = {"expense": params.get("amount", 0.0)}

        elif node.type == NodeType.MORTALITY:
            table_path = params.get("table_path", params.get("table_name", "soa_ilt"))
            if not table_path:
                raise BlueprintExecutionError(f"MORTALITY node {node.id} missing table path.")

            if table_path in ("soa_ilt.csv", "soa_ilt"):
                mortality = MortalityTable.from_soa_ilt()
            else:
                try:
                    mortality = MortalityTable.from_csv(table_path)
                except Exception:
                    mortality = MortalityTable.from_soa_ilt()

            output["mortality_table"] = mortality

            if "age" in params:
                age = params["age"]
                term = params.get("term")
                max_t = term if term is not None else (mortality.max_age - age)
                output["qx_vector"] = mortality.tqx_vector(age, max_t)

        elif node.type == NodeType.SURVIVAL:
            mortality = params.get("mortality_table")
            if not mortality:
                raise BlueprintExecutionError(f"SURVIVAL node {node.id} requires a mortality_table.")

            if "age" in params:
                age = params["age"]
                term = params.get("term")
                max_t = term if term is not None else (mortality.max_age - age)
                tpx = mortality.tpx_vector(age, max_t)
                output["tpx_vector"] = tpx

                qx_rates = np.array([mortality.get_qx(age + t) for t in range(len(tpx))])
                deferred_qx = tpx * qx_rates
                output["deferred_qx_vector"] = deferred_qx

        elif node.type == NodeType.BENEFIT:
            output["benefit"] = params.get("benefit_amount", 0.0)

        elif node.type == NodeType.DISCOUNT:
            rate = params.get("discount_rate", 0.0)
            if "term" in params:
                t = np.arange(params["term"] + 1)
            elif "tpx_vector" in params:
                t = np.arange(len(params["tpx_vector"]))
            else:
                t = np.arange(120)

            v = 1.0 / (1.0 + rate)
            discount_vector = v ** t
            output["discount_vector"] = discount_vector

        elif node.type == NodeType.CASHFLOW:
            benefit = params.get("benefit", 0.0)
            deferred_qx = params.get("deferred_qx_vector")

            if deferred_qx is None:
                raise BlueprintExecutionError(f"CASHFLOW node {node.id} missing deferred_qx_vector from SURVIVAL.")

            expected_claims = benefit * deferred_qx
            output["expected_claims"] = expected_claims

        elif node.type in (NodeType.OUTPUT, NodeType.VALUATION_SINK):
            expected_claims = params.get("expected_claims")
            discount_vector = params.get("discount_vector")

            if expected_claims is not None and discount_vector is not None:
                length = min(len(expected_claims), len(discount_vector))
                pv_claims = 0.0
                for t in range(length):
                    if t + 1 < len(discount_vector):
                        pv_claims += float(expected_claims[t]) * float(discount_vector[t + 1])

                output["npv"] = pv_claims
                output["bel"] = pv_claims
                output["total_bel"] = pv_claims
            else:
                output = params.copy()

        self.context[node.id] = output

    def _run_math_dag(self) -> Dict[str, Any]:
        order = self._topological_sort()
        for node_id in order:
            self._execute_math_node(self.node_map[node_id])

        output_nodes = [nid for nid, node in self.node_map.items() if node.type in (NodeType.OUTPUT, NodeType.VALUATION_SINK)]
        if output_nodes:
            out_ctx = self.context[output_nodes[0]]
            serializable_out: Dict[str, Any] = {}
            for k, v in out_ctx.items():
                if isinstance(v, np.ndarray):
                    serializable_out[k] = v.tolist()
                elif isinstance(v, MortalityTable):
                    serializable_out[k] = v.name
                else:
                    serializable_out[k] = v
            if "total_bel" not in serializable_out and "bel" in serializable_out:
                serializable_out["total_bel"] = serializable_out["bel"]
            if "bel" not in serializable_out and "total_bel" in serializable_out:
                serializable_out["bel"] = serializable_out["total_bel"]
            return serializable_out
        return {}

    def run(self) -> Dict[str, Any]:
        """Execute the full blueprint DAG."""
        try:
            if self._is_math_dag():
                return self._run_math_dag()

            # Adapt Blueprint to ContractGraphPayload for standard ContractGraphSimulator
            nodes = [
                GraphNodeData(
                    id=node.id,
                    type=node.type.value,
                    data=node.config,
                    position=node.position,
                )
                for node in self.blueprint.nodes
            ]

            edges = [
                GraphEdgeData(
                    id=edge.id,
                    source=edge.source,
                    target=edge.target,
                    sourceHandle=edge.source_handle,
                    targetHandle=edge.target_handle,
                )
                for edge in self.blueprint.edges
            ]

            payload = ContractGraphPayload(
                contract_id=str(self.blueprint.id),
                nodes=nodes,
                edges=edges,
            )

            simulator = ContractGraphSimulator()
            response = simulator.simulate(payload)
            dump = response.model_dump()
            dump["bel"] = dump.get("total_bel", 0.0)
            dump["npv"] = sum(dump.get("discounted_net_cf", []))
            return dump

        except Exception as e:
            if isinstance(e, BlueprintExecutionError):
                raise
            raise BlueprintExecutionError(f"Failed to execute blueprint graph: {str(e)}") from e
