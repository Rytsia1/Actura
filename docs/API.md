# API Reference

Actura is powered by a FastAPI backend. This document provides an overview of the core endpoints. For interactive testing and real-time schema validation, start the server and navigate to `http://localhost:8000/docs` (Swagger UI).

## 🗂️ Workspaces (Projects)

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/projects/` | Create a new project workspace. |
| `GET` | `/projects/` | List all available projects (ordered by pinned & recency). |
| `GET` | `/projects/{id}` | Fetch metadata for a specific project. |
| `PUT` | `/projects/{id}` | Update project metadata (e.g., pinning, renaming). |
| `DELETE` | `/projects/{id}` | Permanently delete a project and all associated contracts. |

## 📐 Blueprints (Contracts)

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/projects/{id}/blueprints/` | Save a new Blueprint (Contract DAG) JSON layout. |
| `GET` | `/projects/{id}/blueprints/` | Retrieve a list of blueprints for a project. |
| `GET` | `/projects/{id}/blueprints/{contract_id}` | Retrieve a specific blueprint's nodes and edges. |
| `PUT` | `/projects/{id}/blueprints/{contract_id}` | Update an existing blueprint JSON in the DB. |

## ⚙️ Workflow & Valuation

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/workflow/{id}/start` | Initialize a new valuation workflow state. |
| `GET` | `/workflow/{id}/state` | Get current workflow orchestration state. |
| `POST` | `/workflow/{id}/contract` | Add a contract preset layout to the active workflow. |
| `POST` | `/projects/{id}/valuations/run` | Execute deterministic or stochastic simulation against a specific contract ID. Returns Job ID. |
| `GET` | `/projects/{id}/valuations/{run_id}/result` | Fetch calculated BEL, VaR, Net Cash Flows, and risk distributions. |

---

*Note: All endpoints are prefixed with `/api/` when routed through the Nginx reverse proxy in Docker.*
