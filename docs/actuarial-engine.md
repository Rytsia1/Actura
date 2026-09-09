# Actuarial Engine

The backend mathematical core of Actura is responsible for high-performance cash flow projection and stochastic risk modeling. Built entirely in Python using `numpy` for vectorized performance, the engine processes the visual Blueprint JSON into mathematically actionable models.

## 🧮 Core Modules

### 1. Pricing Engine
- Located in `actuary_engine/pricing/`
- Handles deterministic pricing based on decrement rates, loading vectors, and specified margin requirements.
- Outputs level premiums, flexible premiums, or unit-linked charge structures.

### 2. Projections Engine
- Located in `actuary_engine/projections/`
- Converts the Blueprint DAG into a chronological cash flow map.
- Simulates month-by-month or year-by-year survival rates, mortality outgo, and expense impacts.
- Outputs multi-year decrement tables (e.g. `$q_x, p_x, _tV_x$`).

### 3. Stochastic Engine (ESG)
- Located in `actuary_engine/stochastic/`
- Integrates Economic Scenario Generators (e.g., Hull-White 1F, Black-Scholes).
- Supports large-scale Monte Carlo simulations (up to 10k scenarios) in parallel batches to derive VaR (Value at Risk) and CVaR (Conditional Value at Risk) 95% tails.

### 4. Valuation & IFRS 17
- Located in `actuary_engine/valuation/`
- Tracks the Contractual Service Margin (CSM) amortisation.
- Projects Risk Adjustment (RA) release over the contract boundary.
- Automates deterministic and stochastic reserve bridging (Analysis of Change).

## 🚀 Performance
The actuarial engine relies strictly on array broadcasting in NumPy to eliminate iterative looping over policies or scenarios. This strategy drastically lowers execution time, allowing for real-time risk updates in the Vue dashboard.
