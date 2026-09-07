# Development Guide

## Architecture

Actura uses a FastAPI backend with Vue 3 frontend. 
The core engine is built with NumPy and Numba for vectorization and compilation.

## Job Execution Architecture

To prevent CPU-bound Monte Carlo simulations from blocking the ASGI event loop, Actura delegates heavy computation to a separate process pool.

See [Job Execution](./job-execution.md) for details on the asynchronous worker system, queueing, and WebSocket progress streaming.

## Local Development Setup

1. Install pinned dependencies in a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows use: .venv\Scripts\activate
   pip install -r requirements.txt
   pip install -e ".[dev]"
   ```

2. Run the FastAPI development server:
   ```bash
   uvicorn actuary_engine.api.main:app --reload
   ```

3. Run the test suite:
   ```bash
   pytest
   ```

Note: Background jobs are executed using a local `ProcessPoolExecutor`. By default, job state is backed by a local SQLite database (`jobs.db`). 

For production configurations or how to connect to PostgreSQL, see [Configuration & Deployment](./configuration.md).
