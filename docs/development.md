# Development Guide

## Architecture

Actura uses a FastAPI backend with Vue 3 frontend. 
The core engine is built with NumPy and Numba for vectorization and compilation.

## Job Execution Architecture

To prevent CPU-bound Monte Carlo simulations from blocking the ASGI event loop, Actura delegates heavy computation to a separate process pool.

See [Job Execution](./job-execution.md) for details on the asynchronous worker system, queueing, and WebSocket progress streaming.

## Local Development Setup

1. Install dependencies:
   ```bash
   poetry install
   ```

2. Run the FastAPI development server:
   ```bash
   poetry run uvicorn actuary_engine.api.main:app --reload
   ```

3. Run the test suite:
   ```bash
   poetry run pytest
   ```

Note: Background jobs are executed using a local `ProcessPoolExecutor` backed by a SQLite database (`jobs.db`). No Redis or Celery instance is required for local development.
