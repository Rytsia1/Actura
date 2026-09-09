# Development Guide

This guide explains how to set up Actura for local development without relying purely on the production Docker cluster.

## Architecture

Actura uses a FastAPI backend with Vue 3 frontend. 
The core engine is built with NumPy and Numba for vectorization and compilation.

## Job Execution Architecture

To prevent CPU-bound Monte Carlo simulations from blocking the ASGI event loop, Actura delegates heavy computation to a separate process pool.
See [Job Execution](./job-execution.md) for details on the asynchronous worker system, queueing, and WebSocket progress streaming.

## 🛠 Prerequisites
- **Python 3.11+**
- **Node.js 18+** & NPM
- **PostgreSQL 15+** (You can use Docker to spin up just the DB, or install locally).

## 🗄️ Database Setup
1. Spin up a local Postgres instance:
   ```bash
   docker run --name actura_dev_db -e POSTGRES_USER=actura_user -e POSTGRES_PASSWORD=actura_password -e POSTGRES_DB=actura_db -p 5432:5432 -d postgres:15-alpine
   ```
2. The FastAPI backend will automatically use SQLite (`jobs.db`) if no Postgres `DATABASE_URL` is provided. If you want to use Postgres locally, export it:
   ```bash
   export DATABASE_URL="postgresql://actura_user:actura_password@localhost:5432/actura_db"
   ```

## 🐍 Backend (FastAPI) Setup
1. Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   pip install -e ".[dev,api]"
   ```
3. Run the server:
   ```bash
   uvicorn actuary_engine.main:app --reload --port 8000
   ```
   The backend will now be available at `http://localhost:8000`.

## 🌐 Frontend (Vue 3) Setup
1. Navigate to the frontend directory:
   ```bash
   cd frontend
   ```
2. Install NPM dependencies:
   ```bash
   npm install
   ```
3. Create a `.env.local` file (optional, if you need to override the API base URL):
   ```env
   VITE_API_BASE_URL=http://localhost:8000
   ```
4. Start the Vite dev server:
   ```bash
   npm run dev
   ```
   The frontend will now be available at `http://localhost:5173`. Hot-Module Replacement (HMR) is enabled.

## 🧪 Running Tests
Actura uses `pytest` for the backend validation.
```bash
pytest tests/ -v
```

## 📐 Project Structure Guidelines
- **UI Components:** Place inside `frontend/src/components/`. If it's a Vue Flow node, place it in `frontend/src/components/nodes/`.
- **Actuarial Logic:** Add quantitative python code to `actuary_engine/`. Do NOT put mathematical logic in the FastAPI router files (`api/routes/`). Use service classes instead.
- **Styling:** We use Tailwind CSS. Avoid writing raw CSS unless you are overriding Vue Flow internals in `style.css`.
