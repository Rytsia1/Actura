# Actura | Actuarial Valuation & Risk Platform

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg?logo=python&logoColor=white)
![Vue.js](https://img.shields.io/badge/Vue.js-3.x-4FC08D.svg?logo=vuedotjs&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg?logo=fastapi&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg?logo=docker&logoColor=white)

## 📌 Overview
**Actura** is an enterprise-grade actuarial platform that bridges the gap between complex risk mathematics and modern UI/UX. It provides actuaries and risk engineers with a powerful Python-based valuation engine (handling everything from Monte Carlo simulations to IFRS 17 trajectories) paired with a sleek, neo-skeuomorphic Vue 3 dashboard.

## 📸 Screenshots

### Valuation Dashboard
<img width="1917" height="1078" alt="Screenshot 2026-08-27 220531" src="https://github.com/user-attachments/assets/e414e87c-2bba-493a-a220-7665253687b7" />

*Real-time stochastic projection, tail risk (CVaR) analysis, and comprehensive reserve profiles.*

### Contract Logic Blueprint Builder
<img width="1917" height="1078" alt="Screenshot 2026-08-27 223759" src="https://github.com/user-attachments/assets/2e2bcb71-7aa3-451f-8060-38e548926705" />

*A visual, node-based DAG (Directed Acyclic Graph) editor for designing insurance cash flow blueprints without writing code.*

---

## ✨ Features
- 🧩 **Visual Logic Builder:** Drag-and-drop DAG editor to map out premiums, benefits, and decrement models seamlessly.
- 📈 **Stochastic Engine:** Integrated Economic Scenario Generators (ESG) and advanced Monte Carlo simulations.
- 📊 **Risk Analytics:** Built-in calculation for BEL, VaR 95%, CVaR / CTE 95, and quantile fan-charts.
- ⚙️ **IFRS 17 Ready:** Automated CSM (Contractual Service Margin) mechanics and Risk Adjustment tracking.
- ⚡ **High-Performance Backend:** Powered by FastAPI for rapid deterministic and stochastic valuations.
- 🐳 **Docker-Ready:** Fully containerized architecture with Nginx reverse proxy for immediate, production-like deployment.

## 🏛️ Architecture
Actura uses a modern decoupled architecture:
1. **Frontend**: Vue 3 SPA handling graph interactions (Vue Flow) and charting (ECharts).
2. **Backend**: FastAPI providing REST endpoints to handle math-heavy actuarial modeling, state management, and DB interactions.
3. **Database**: PostgreSQL (via SQLAlchemy) to store projects, blueprints, and stochastic results.
4. **Proxy**: Nginx for static serving and routing.

See [Architecture Documentation](docs/architecture.md) for deeper details.

## ⚙️ How it works
Actura evaluates insurance cash flows as a **Directed Acyclic Graph (DAG)**. 
- **Nodes** represent financial events (e.g. premium collection, mortality decrements, expense payouts).
- **Edges** dictate the flow of policyholder states and cash across the timeline.
The graph is compiled by the Vue 3 frontend, saved as a JSON blueprint to the database, and executed by the Python actuarial engine over projection timesteps.

See [Blueprint Engine](docs/blueprint.md) for more details.

## 🔄 Example workflow
1. **Project Setup:** Create a new project and select an actuarial preset (e.g., *20-Year Term Life*).
2. **Blueprint Design:** In the Visual Builder, drag and drop nodes to define logic (e.g., attach an Expense node to the Inflow).
3. **Simulation:** Hit "Run Simulation". The backend parses the DAG and generates cash flow trajectories.
4. **Risk Dashboard:** View the aggregated results (BEL, Net Cash Flow, Stochastic Fan Charts) on the main dashboard.

## 🛠️ Tech stack
- **Backend:** Python 3.10+, FastAPI, SQLAlchemy, NumPy, Pandas, SciPy.
- **Frontend:** Vue 3 (Composition API), Vite, Tailwind CSS, Vue Flow, Apache ECharts.
- **Infrastructure:** Docker, Docker Compose, Nginx, PostgreSQL.

## 🚀 Installation

### Quick Start (Docker)
1. **Clone the repository**
   ```bash
   git clone https://github.com/rytsia1/actuarial-valuation-engine.git
   cd actuarial-valuation-engine
   ```
2. **Build and spin up the containers**
   ```bash
   docker compose up --build -d
   ```
3. **Access the Platform**
   - 🖥️ **UI Dashboard:** `http://localhost:3000`
   - ⚙️ **API Docs:** `http://localhost:8000/docs`

For local development setup without Docker, check out [Development Guide](docs/development.md).

## 📡 API
The backend exposes a REST API via FastAPI.
- `/projects/`: CRUD operations for workspaces.
- `/projects/{id}/blueprints/`: Blueprint DAG persistence.
- `/projects/{id}/valuations/`: Trigger stochastic or deterministic engine runs.

See the full [API Documentation](docs/API.md).

## 🧪 Testing
Actura leverages `pytest` for robust numerical validation.
```bash
docker exec -it actura_postgres pytest tests/
```
We assert calculations against standard actuarial tables (e.g., SOA ILT) to guarantee numerical precision.

## ⚡ Performance
- Vectorized array operations via NumPy allows for 1000+ stochastic scenarios to be run in under a second.
- Vue Flow handles 100+ DAG nodes efficiently using hardware-accelerated rendering.
- ECharts leverages Canvas/WebGL for smooth 60fps charting of large stochastic datasets.

## 🗺️ Roadmap
- [ ] Export to Excel/CSV for IFRS 17 disclosures
- [ ] Collaborative real-time blueprint editing
- [ ] Integration with external ESG providers (e.g., Moody's / Barrie & Hibbert)
- [ ] Additional decrement tables support (Morbidity, Multi-state transitions)
