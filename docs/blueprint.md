# Blueprint Engine

The **Blueprint** is the cornerstone of Actura. Instead of requiring users to hardcode logic for each specific product, Actura uses a node-based DAG (Directed Acyclic Graph) approach to map out financial logic interactively.

## 🧱 Node Types

Blueprints are composed of nodes representing events, models, or data inputs. Actura supports several node paradigms:

- `policyInput` (Source): Sets the base parameters (age, sum assured, term, product type).
- `inflow` (Source): Generates cash into the system (e.g., Gross Premiums).
- `contingency` (Splitter): Maps demographic decrement tables (e.g., Mortality, Morbidity, Lapses) to create probabilities.
- `outflow` (Sink): Defines cash outgo conditional on a contingency or fixed timing (e.g., Death Benefits, Maturity Payouts, Commissions).
- `accumulator` (Logic): Unit-Linked logic that tracks fund values, deducts COI (Cost of Insurance) charges, and applies interest/dividend rates.
- `valuationSink` (Terminal): Aggregates all upstream cash flows to execute pricing/reserving calculations.

## 🔗 Execution Flow

When a simulation is run, the backend orchestrator parses the JSON DAG:
1. Validates the structure (must end in `valuationSink`).
2. Traverses the graph from Sources to Sinks.
3. Multiplies contingencies down the edges (e.g., $q_x$ from a Mortality node flows into a Death Benefit node to create Expected Outgo).
4. Aggregates final cash flows at the Terminal node to calculate Gross Reserves and Net Cash Flow profiles.

## 🎨 Frontend Implementation

The frontend utilizes **Vue Flow** (a Vue 3 wrapper for React Flow) to provide a smooth, hardware-accelerated canvas. We implemented:
- A drag-and-drop palette.
- Auto-layouting via Dagre (directed graph layout engine).
- Real-time serialization to a generic JSON spec sent to the API.
