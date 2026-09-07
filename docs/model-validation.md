# Domain-Aware Actuarial Validation

Actura implements a domain-aware validation system to ensure that visual blueprint models are mathematically and structurally sound before running computationally expensive deterministic or stochastic valuations.

## Validation Architecture

The validation system is built into the backend (`actuary_engine/valuation/blueprint_validator.py`) and exposed via the REST API endpoint `/api/v1/contracts/validate-graph`.

The system also intercepts valuation requests at the `/api/v1/contracts/simulate-graph` endpoint. If the blueprint contains `ERROR` level issues, the valuation is rejected with a 400 Bad Request to protect the engine from invalid state.

## Validation Categories

The validator checks the following rules:

### A. Structural Validation
Ensures the blueprint DAG is well-formed:
* **GRAPH_CYCLE (ERROR)**: Detects circular dependencies (cycles). The calculation engine requires a Directed Acyclic Graph (DAG).
* **MISSING_POLICY_INPUT (ERROR)**: A contract must have at least one base parameter node (`PolicyInput`).
* **MISSING_VALUATION_SINK (ERROR)**: The blueprint must contain an Outflow, Benefit, or Accumulator node to generate liabilities or cash flows.
* **DISCONNECTED_NODE (WARNING)**: Nodes that have no connections (in-degree 0 and out-degree 0) and are not a `PolicyInput`.

### B. Data Validation
Ensures reference data required by the contract exists:
* **MISSING_MORTALITY_DATA (ERROR)**: The referenced mortality table is not present in the system registry.

### C. Temporal Validation
Ensures the requested projection timeline aligns with the actuarial data:
* **MORTALITY_COVERAGE (ERROR)**: The policyholder's issue age is below the minimum age of the selected mortality table.
* **MORTALITY_COVERAGE (ERROR)**: The projection horizon (`issue_age + term`) exceeds the maximum age defined in the mortality table.
* **INVALID_AGE / INVALID_TERM (ERROR)**: Malformed or non-integer temporal values.

### D. Financial Validation
Ensures assumptions do not result in mathematically invalid scenarios:
* **NEGATIVE_FACE_AMOUNT (ERROR)**: Sum Assured must be strictly positive.
* **NEGATIVE_PREMIUM (ERROR)**: Fixed explicit premiums cannot be negative.
* **NEGATIVE_MULTIPLIER (ERROR)**: Decrement multipliers (e.g., mortality scaling) cannot be negative.
* **NEGATIVE_RATIO (ERROR)**: Benefit or surrender ratios cannot be negative.
* **INVALID_FACE_AMOUNT (ERROR)**: Sum Assured is not a number.

### E. Unit Validation
Detects common user-entry mistakes, specifically percentage vs decimal confusion:
* **UNIT_MISMATCH (WARNING)**: Surrender ratios or interest rates exceeding 100% (>1.0) usually indicate the user entered a raw percentage (e.g., 80) instead of a decimal (0.80).
* **NEGATIVE_INTEREST_RATE (WARNING)**: Interest rate is negative. (Flagged as warning as negative interest rate environments can theoretically exist, but are highly unusual for basic valuation).

## Extension Strategy

To add new validation rules:
1. Define a new check in `BlueprintValidator.validate()`.
2. Append a new `ValidationIssue` to the issues array using the `ValidationSeverity` enum (`ERROR`, `WARNING`, `INFO`).
3. Ensure the check fails gracefully if optional fields are not present on the node data.
4. Add corresponding unit tests in `tests/test_validation.py`.
