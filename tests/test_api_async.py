"""
Test suite for asynchronous stochastic valuation pipeline, job manager, and WebSockets.
"""

from __future__ import annotations

import time
import pytest
from fastapi.testclient import TestClient

from actuary_engine.main import app

client = TestClient(app)


class TestAsyncValuationAPI:
    """Test suite for /api/v1/valuation/stochastic/async and polling endpoints."""

    def test_enqueue_async_simulation_job(self) -> None:
        payload = {
            "product_type": "endowment",
            "issue_age": 35,
            "term": 20,
            "sum_assured": 500_000,
            "vasicek": {
                "r0": 0.05,
                "kappa": 0.20,
                "theta": 0.05,
                "sigma": 0.015,
            },
            "n_scenarios": 500,
            "seed": 42,
        }

        response = client.post("/api/v1/valuation/stochastic/async", json=payload)
        assert response.status_code == 202
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "QUEUED"
        assert data["total_paths"] == 500
        assert data["ws_endpoint"].startswith("/ws/simulations/")

    def test_polling_job_status_until_completion(self) -> None:
        payload = {
            "product_type": "term",
            "issue_age": 30,
            "term": 15,
            "sum_assured": 1_000_000,
            "vasicek": {
                "r0": 0.04,
                "kappa": 0.15,
                "theta": 0.04,
                "sigma": 0.01,
            },
            "n_scenarios": 400,
            "seed": 123,
        }

        post_res = client.post("/api/v1/valuation/stochastic/async", json=payload)
        assert post_res.status_code == 202
        job_id = post_res.json()["job_id"]

        # Poll status until completed (timeout 10s)
        completed = False
        final_data = None
        for _ in range(50):
            status_res = client.get(f"/api/v1/valuation/stochastic/status/{job_id}")
            assert status_res.status_code == 200
            data = status_res.json()
            if data["status"] == "COMPLETED":
                completed = True
                final_data = data
                break
            time.sleep(0.05)

        assert completed, f"Job {job_id} did not complete within timeout."
        assert final_data is not None
        assert final_data["progress"] == 100.0
        assert final_data["completed_paths"] == 400
        assert final_data["result"] is not None
        assert "mean_bel" in final_data["result"]
        assert "var_95" in final_data["result"]
        assert "fan_chart_rates" in final_data["result"]

    def test_polling_non_existent_job_returns_404(self) -> None:
        response = client.get("/api/v1/valuation/stochastic/status/non-existent-uuid")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_invalid_contract_params_returns_400(self) -> None:
        payload = {
            "product_type": "endowment",
            "issue_age": 120,  # invalid age > 105
            "term": 20,
            "sum_assured": 100_000,
        }
        response = client.post("/api/v1/valuation/stochastic/async", json=payload)
        assert response.status_code in (400, 422)


class TestWebSocketSimulationProgress:
    """Test suite for WebSocket /ws/simulations/{job_id} progress streaming."""

    def test_websocket_progress_and_completion_stream(self) -> None:
        payload = {
            "product_type": "endowment",
            "issue_age": 40,
            "term": 20,
            "sum_assured": 1_000_000,
            "vasicek": {
                "r0": 0.05,
                "kappa": 0.20,
                "theta": 0.05,
                "sigma": 0.015,
            },
            "n_scenarios": 600,
            "seed": 42,
        }

        # 1. Enqueue job
        post_res = client.post("/api/v1/valuation/stochastic/async", json=payload)
        assert post_res.status_code == 202
        job_id = post_res.json()["job_id"]

        # 2. Connect WebSocket
        messages = []
        with client.websocket_connect(f"/ws/simulations/{job_id}") as ws:
            while True:
                msg = ws.receive_json()
                messages.append(msg)
                if msg.get("type") in ("COMPLETE", "ERROR"):
                    break

        assert len(messages) >= 1
        types = [m["type"] for m in messages]
        assert "COMPLETE" in types

        # Validate final COMPLETE message payload
        complete_msg = next(m for m in messages if m["type"] == "COMPLETE")
        assert complete_msg["percent"] == 100.0
        assert complete_msg["completed_paths"] == 600
        assert "data" in complete_msg
        assert "mean_bel" in complete_msg["data"]
        assert "var_95" in complete_msg["data"]

    def test_websocket_non_existent_job_returns_error(self) -> None:
        with client.websocket_connect("/ws/simulations/invalid-job-id") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "ERROR"
            assert "not found" in msg["error"].lower()
