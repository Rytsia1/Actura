# Visual Blueprint Builder Implementation Plan

This document outlines the architectural plan for implementing the **Visual Blueprint Builder** for the Actura Engine. The Visual Blueprint Builder converts UI-driven graph structures into validated, deterministic actuarial cash flow projections.

## User Review Required

Please review the proposed execution context payloads for the DAG nodes in `Executor`. Specifically, whether returning raw numpy arrays / lists for vectors (like `q_x`, `tPx`) inside the context dictionary aligns with your expectations for the frontend.

## Proposed Changes

### Domain Logic (Blueprint)

#### [NEW] `actuary_engine/domain/blueprint/exceptions.py`
Define custom exceptions for the blueprint engine:
- `BlueprintValidationError`: Raised during graph compilation if rules are violated.
- `BlueprintExecutionError`: Raised during runtime if node evaluation fails.

#### [NEW] `actuary_engine/domain/blueprint/models.py`
Define pure, JSON-serializable Pydantic models for the graph structure.
- `NodeType` (str, Enum): Exhaustive list of node operations (`INPUT`, `PREMIUM`, `EXPENSE`, `MORTALITY`, `SURVIVAL`, `BENEFIT`, `CASHFLOW`, `DISCOUNT`, `OUTPUT`).
- `Node` (BaseModel): Represents a single computation step with a dynamic `config` dict.
- `Edge` (BaseModel): Represents a directional data dependency between nodes.
- `Blueprint` (BaseModel): The root graph structure.

#### [NEW] `actuary_engine/domain/blueprint/validator.py`
Implement `BlueprintValidator` with a static `validate(blueprint: Blueprint)` method.
- **Cycle Detection**: Use DFS traversal to guarantee an acyclic graph.
- **Connectivity**: Verify all nodes are on a path from an `INPUT` to an `OUTPUT`.
- **Semantic Edges**: Reject invalid connections (e.g. `PREMIUM` → `MORTALITY`).
- **Configuration**: Validate required keys inside node `config` based on their `NodeType`.

#### [NEW] `actuary_engine/domain/blueprint/executor.py`
Implement `BlueprintExecutor` which consumes a validated `Blueprint`.
- **Topological Sort**: Implements Kahn's algorithm to resolve node execution order.
- **Context Passing**: Maintains a `self.context` dictionary to pipe outputs of parent nodes into inputs of child nodes.
- **Node Execution**: Contains the actuarial logic factory for processing each `NodeType`. Integrates with existing `MortalityTable` and basic math arrays to calculate cashflows dynamically.

### API Layer

#### [NEW] `actuary_engine/api/routes/blueprint.py`
Exposes the execution engine to the frontend.
- `POST /api/v1/blueprint/execute`
- Accepts `Blueprint` JSON payload.
- Validates the blueprint and executes it, returning the final output node's context.

#### [MODIFY] `actuary_engine/main.py`
Include the new `blueprint.router` in the FastAPI application setup.

### Automated Testing

#### [NEW] `tests/domain/blueprint/test_models.py`
Verify Pydantic serialization and deserialization limits UI state from bleeding into business logic.

#### [NEW] `tests/domain/blueprint/test_validator.py`
Inject broken graphs (cycles, missing inputs, floating nodes) and assert that `BlueprintValidationError` is raised with the correct descriptive messages.

#### [NEW] `tests/domain/blueprint/test_executor.py`
End-to-end integration test proving the DAG compilation yields the mathematically identical Net Single Premium / Reserve as the hardcoded `WholeLife` and `Term` pricer classes.

## Verification Plan

1. **Unit Tests**: Run `pytest tests/domain/blueprint/ -v` to ensure 100% pass rate.
2. **Integration**: Run the full test suite `pytest tests/ -v` to ensure no regressions in existing engines.
3. **Equivalence**: The executor tests will mandate that the blueprint output matches exactly to `1e-12` against the deterministic `InsurancePricer` baseline.
