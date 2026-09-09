"""
Payload compression and server-side quantile reduction test suite.

Verifies:
1. Response payloads for large-scale Monte Carlo simulations (10,000+ paths) remain under 100 KB.
2. Cross-sectional quantiles satisfy monotonicity: p5 <= p25 <= p50 <= p75 <= p95 at every timestep.
3. Terminal distribution histogram and statistical moments (mean, std, skewness, VaR, CVaR) are pre-calculated.
4. No raw simulation tensors of size (n_scenarios x n_timesteps) are transmitted.
"""

from __future__ import annotations

import json
import numpy as np
import pytest
from fastapi.testclient import TestClient

from actuary_engine.main import app
from actuary_engine.domain.stochastic.monte_carlo import (
    compute_quantile_trajectory,
    compute_terminal_distribution,
    sample_representative_paths,
)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


class TestServerSideQuantilesAndMoments:
    """Test unit logic for quantile reduction and histogram binning."""

    def test_quantile_trajectory_monotonicity(self) -> None:
        """Verify p5 <= p25 <= p50 <= p75 <= p95 across all timesteps."""
        rng = np.random.default_rng(42)
        n_scenarios = 5000
        n_steps = 20
        # Simulated rate paths
        paths = np.empty((n_scenarios, n_steps + 1))
        paths[:, 0] = 0.05
        for t in range(n_steps):
            paths[:, t + 1] = paths[:, t] + 0.20 * (0.05 - paths[:, t]) + 0.015 * rng.standard_normal(n_scenarios)

        quantiles = compute_quantile_trajectory(paths)

        assert len(quantiles["p5"]) == n_steps + 1
        assert len(quantiles["p25"]) == n_steps + 1
        assert len(quantiles["p50"]) == n_steps + 1
        assert len(quantiles["p75"]) == n_steps + 1
        assert len(quantiles["p95"]) == n_steps + 1

        for t in range(n_steps + 1):
            assert quantiles["p5"][t] <= quantiles["p25"][t] + 1e-9
            assert quantiles["p25"][t] <= quantiles["p50"][t] + 1e-9
            assert quantiles["p50"][t] <= quantiles["p75"][t] + 1e-9
            assert quantiles["p75"][t] <= quantiles["p95"][t] + 1e-9

    def test_terminal_distribution_moments_and_bins(self) -> None:
        """Verify terminal distribution histogram binning, moments, and VaR/CVaR."""
        rng = np.random.default_rng(100)
        # Normal distribution with mean 10,000 and std 2,000
        values = rng.normal(10_000.0, 2_000.0, size=10_000)

        dist = compute_terminal_distribution(values, bins=40)

        assert len(dist["counts"]) == 40
        assert len(dist["bin_edges"]) == 41
        assert sum(dist["counts"]) == 10_000

        # Mean and std within statistical error
        assert dist["mean"] == pytest.approx(10_000.0, abs=100.0)
        assert dist["std"] == pytest.approx(2_000.0, abs=100.0)
        # Normal distribution has near-zero skewness
        assert abs(dist["skewness"]) < 0.15

        # VaR and CVaR ordering
        assert dist["var_95"] < dist["var_99"]
        assert dist["cvar_95"] >= dist["var_95"]
        assert dist["cvar_99"] >= dist["var_99"]

    def test_representative_path_sampling_budget(self) -> None:
        """Verify sample_representative_paths caps sample traces to budget."""
        rng = np.random.default_rng(77)
        paths = rng.normal(0.05, 0.01, size=(5000, 25))

        samples = sample_representative_paths(paths, max_paths=12)

        assert len(samples) == 12
        for p in samples:
            assert len(p) == 25


class TestAPIPayloadCompression:
    """Test API endpoint payload size and schema compression."""

    def test_stochastic_endpoint_payload_compression(self, client: TestClient) -> None:
        """Verify POST /api/v1/valuation/stochastic returns structured quantiles under 100 KB for 10k paths."""
        payload = {
            "product_type": "endowment",
            "issue_age": 30,
            "term": 20,
            "sum_assured": 1_000_000.0,
            "table_id": "soa_ilt",
            "n_scenarios": 10_000,
            "seed": 42,
        }

        response = client.post("/api/v1/valuation/stochastic", json=payload)
        assert response.status_code == 200

        # 1. Payload size check
        raw_json_bytes = response.content
        payload_kb = len(raw_json_bytes) / 1024.0
        # 10,000 raw paths would be ~2 MB; compressed payload must be well under 100 KB
        assert payload_kb < 100.0

        data = response.json()

        # 2. Structured quantiles verification
        assert "quantiles" in data
        q = data["quantiles"]
        assert len(q["p5"]) == 21
        assert len(q["p25"]) == 21
        assert len(q["p50"]) == 21
        assert len(q["p75"]) == 21
        assert len(q["p95"]) == 21

        # Monotonicity check
        for t in range(21):
            assert q["p5"][t] <= q["p25"][t] + 1e-5
            assert q["p25"][t] <= q["p50"][t] + 1e-5
            assert q["p50"][t] <= q["p75"][t] + 1e-5
            assert q["p75"][t] <= q["p95"][t] + 1e-5

        # 3. Terminal distribution verification
        assert "terminal_distribution" in data
        td = data["terminal_distribution"]
        assert len(td["counts"]) == 40
        assert len(td["bin_edges"]) == 41
        assert sum(td["counts"]) == 10_000
        assert "skewness" in td
        assert "var_95" in td
        assert "cvar_95" in td

        # 4. Sample paths verification (capped at 15)
        assert "sample_paths" in data
        assert len(data["sample_paths"]) <= 15
        assert len(data["sample_paths"]) > 0

        # 5. Summary KPIs dictionary
        assert "summary_kpis" in data
        kpis = data["summary_kpis"]
        assert "mean_bel" in kpis
        assert "var_95" in kpis
        assert "skewness" in kpis
