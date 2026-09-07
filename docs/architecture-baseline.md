# Actura Architecture Baseline

## 1. Current Architecture

- **Frontend**: Vue 3 application built with Vite. State management is handled by Pinia (`useValuationStore.js`). Uses Vue Router for navigation. Key libraries include `@vue-flow/core` for the visual blueprint/modeling system, `echarts` for charting, and `tailwindcss` for styling.
- **Backend**: FastAPI web framework (Python 3.11+). Exposes REST endpoints and WebSockets for real-time streaming.
- **Domain layer**: Modular actuarial models located in `actuary_engine/models`, `actuary_engine/curves`, `actuary_engine/pricing`, and `actuary_engine/valuation`. Includes classes like `PolicyContract`, `MortalityTable`, `LevelPremiumCalculator`, and `StochasticValuationEngine`. Computationally intensive operations are accelerated with `numpy`, `scipy`, `pandas`, and `numba`.
- **Persistence**: Currently minimal or entirely in-memory. `TableRegistry` stores uploaded mortality tables in memory, and `JobManager` handles job tracking in memory.
- **Simulation**: Supports Level 4 Monte Carlo simulations using ESG models (Vasicek, CIR, HullWhite1F, LeeCarter) with chunking and fan chart analytics.
- **Job execution**: Asynchronous jobs are queued using FastAPI's `BackgroundTasks` and managed by an in-memory `JobManager`.
- **Communication**: Standard REST endpoints for stateless operations. WebSockets (`/ws/simulations/{job_id}`) are used to stream real-time progress for heavy stochastic jobs.
- **Deployment**: Dockerized with a `docker-compose.yml` defining `frontend` and `backend` services.

## 2. Current Data Flow

### A. Deterministic valuation
1. Client POSTs to `/api/v1/valuation/deterministic`.
2. Request is mapped to `DeterministicValuationRequest`.
3. `LevelPremiumCalculator` prices the net level premium.
4. `ReserveCalculator` calculates prospective/retrospective reserves.
5. `GrossPremiumValuation` projects cash flows based on expense and lapse assumptions.
6. Returns `DeterministicValuationResponse` with cash flow trajectories and reserves.

### B. Stochastic valuation
1. Client POSTs to `/api/v1/valuation/stochastic`.
2. `StochasticValuationEngine` uses the configured ESG (e.g., Vasicek) to generate scenario paths.
3. Computes stochastic BEL distributions, percentiles (VaR, CVaR).
4. Extracts quantiles and terminal distributions for charting.

### C. Simulation progress
1. Client enqueues task at `/api/v1/valuation/stochastic/async`.
2. `JobManager` generates a `job_id` and registers the job.
3. Background task executes the simulation chunks and updates `JobManager`.
4. Client connects to `/ws/simulations/{job_id}` to receive real-time JSON payloads (`type: PROGRESS`).
5. Upon completion, broadcasts `type: COMPLETE` with the full result.

### D. Project/model loading
1. Client uploads a CSV/TSV table to `/api/v1/tables/upload`.
2. `parse_mortality_file` parses and validates the table.
3. `TableRegistry` stores the table in memory.
4. Returns table metadata.

### E. Blueprint execution
1. Vue frontend sends DAG nodes and edges representing a contract.
2. `ContractGraphSimulator` topologically sorts the graph and validates against cycles.
3. Node configuration (PolicyInput, Decrement, Outflow, Inflow) is extracted.
4. Deterministic multi-decrement cash flows are projected using vectorized numpy arrays.
5. `SimulateGraphResponse` containing cash flows and rolled back reserves is returned.

## 3. Current API Surface

- `GET /api/v1/health`: Basic health check.
- `GET /api/v1/tables`: Lists available mortality tables.
- `GET /api/v1/tables/{table_id}`: Gets specific table metadata.
- `POST /api/v1/tables/upload`: Uploads a custom mortality table.
- `DELETE /api/v1/tables/{table_id}`: Deletes a registered table.
- `POST /api/v1/valuation/deterministic`: Synchronous deterministic valuation.
- `POST /api/v1/valuation/stochastic`: Synchronous Monte Carlo valuation.
- `POST /api/v1/valuation/stochastic/async`: Enqueue an async simulation task.
- `GET /api/v1/valuation/stochastic/status/{job_id}`: Polling endpoint for job status.
- `WS /ws/simulations/{job_id}`: WebSocket connection for progress streaming.
- `POST /api/v1/valuation/portfolio`: JSON batch seriatim portfolio valuation.
- `POST /api/v1/valuation/portfolio/csv`: CSV batch seriatim portfolio valuation.
- `POST /api/v1/mortality/lee-carter/forecast`: Stochastic mortality forecasting.

## 4. Current Domain Model

- **Entities**: 
  - `PolicyContract` (ProductType, term, age, sum assured)
  - `MortalityTable` (ages, qx rates, radix)
  - `SimulationJob` (job_id, status, progress, total_paths)
- **Assumptions**: 
  - `InterestAssumption` (annual rate)
  - `ExpenseAssumption` (first-year/renewal percentage and per-policy)
  - `LapseAssumption` (flat rate or dynamic)
- **Engines**: 
  - `StochasticValuationEngine`
  - `GrossPremiumValuation`
  - `LevelPremiumCalculator`

## 5. Current Frontend Architecture

- **Pages**: `MainDashboard.vue`, `ContractBuilderView.vue`, `PrivacyPolicy.vue`, `TermsOfService.vue`.
- **Components**: UI components in `src/components/` (e.g., `ControlPanel.vue`, `MetricCards.vue`, `StochasticFanChart.vue`, `DistributionChart.vue`) and Vue Flow nodes in `src/components/nodes/`.
- **Stores**: `useValuationStore.js` (Pinia store for managing application state and valuation results).
- **API clients**: `httpClient.js` with configured Axios instances handling timeout aborts, 422 validations, and 500 errors.

## 6. Existing Tests

- **Unit tests**: `test_annuity.py`, `test_cash_flow.py`, `test_commutation.py`, `test_insurance.py`, `test_premium.py`, `test_mortality_table.py`, `test_survival.py`.
- **Integration tests**: `test_api.py`, `test_api_async.py`, `test_api_payload.py`.
- **Stochastic tests**: `test_esg_advanced.py`, `test_lee_carter.py`, `test_stochastic.py`.
- **Validation tests**: Extensively test bounds and rules (e.g. `test_reserves.py`, `test_gpv.py`, `test_ifrs17.py`, `test_table_upload.py`).
- **Missing critical tests**: Tests involving real persistence (e.g., database integration) or queueing systems are missing because those systems do not yet exist. There may also be a lack of concurrency tests for the in-memory JobManager.

## 7. Critical Risks

| Issue | Risk Level | Description |
|---|---|---|
| **In-memory state (JobManager, Registry)** | **CRITICAL** | If the FastAPI backend restarts, all uploaded tables and simulation jobs are instantly lost. No fault tolerance. |
| **CPU-bound work inside async execution** | **HIGH** | The `_run_async_simulation_task` function runs stochastic valuations (`numpy`/`numba`) in the main asyncio event loop via `BackgroundTasks`. This blocks the event loop, causing dropped WebSocket connections and freezing the API during heavy Monte Carlo runs. |
| **Persistence coupling** | **HIGH** | The system currently lacks a persistent datastore, relying on Python dicts for state. |
| **Reproducibility** | **MEDIUM** | Requires explicit passing of seeds down the entire `VasicekESG` and `LeeCarterModel` chain. A missing seed defaults to `42` or random, which can break test stability. |
| **Concurrency** | **MEDIUM** | Dictionary updates in `JobManager` use `asyncio.Lock()`, but CPU-bound operations in the background task might still cause race conditions or delays in status delivery. |
| **Validation** | **MEDIUM** | While Pydantic handles basics, deeper domain validations are somewhat coupled inside specific execution paths rather than centralized. |
| **Security** | **LOW** | CORS configuration is extremely permissive (`*`). Missing authentication/authorization. |
| **Dependency management** | **LOW** | Python dependencies are well-specified in `pyproject.toml`, but frontend might require strict version locking as `vue-flow` updates frequently. |
| **API/domain coupling** | **MEDIUM** | The API endpoint schemas are closely intertwined with the domain models. |

## 8. Protected Behavior

The following functionalities MUST NOT be broken during refactoring:
- The `soa_ilt` default mortality table loader and the core equivalence principles (NSP vs Premium).
- The REST API paths (`/api/v1/...`) and request/response Pydantic JSON schemas.
- The `/ws/simulations/{job_id}` WebSocket message payload structures (`PROGRESS`, `COMPLETE`, `ERROR`), which the Vue frontend relies on.
- The frontend DAG visualization serialization format (`ContractGraphPayload`).
- Numba `@njit` kernels which are responsible for the current simulation performance.

## 9. Recommended Architecture Direction

To address the critical risks, the architecture should be evolved in the following phases:

1. **Decouple Task Execution**: Migrate from FastAPI `BackgroundTasks` to a distributed task queue like **Celery** using **Redis** or **RabbitMQ** as a broker. This will isolate CPU-heavy `numpy` workloads from the ASGI event loop and prevent blocked requests.
2. **Implement Persistent Datastore**: Introduce **PostgreSQL** and an ORM (e.g., **SQLAlchemy** or **SQLModel**). Migrate `TableRegistry` and `JobManager` to read/write from the database rather than in-memory dictionaries.
3. **Repository Pattern**: Abstract the database calls behind repository classes so the core actuarial domain models remain purely mathematical and unaware of the database logic.
4. **WebSocket Pub/Sub via Redis**: When multiple uvicorn workers or Celery workers are used, WebSockets need a centralized Pub/Sub mechanism (e.g., Redis Pub/Sub or Broadcaster) to push updates to clients.
