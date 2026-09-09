"""
Test suite for Seriatim Batch Portfolio Valuation Engine and performance benchmarks.
"""

from __future__ import annotations

import time
import pytest
import numpy as np
import pandas as pd

from actuary_engine.models.assumptions import ExpenseAssumption, InterestAssumption, LapseAssumption
from actuary_engine.models.contracts import PolicyContract, ProductType
from actuary_engine.domain.tables.mortality_table import MortalityTable
from actuary_engine.valuation.gpv import GrossPremiumValuation
from actuary_engine.valuation.portfolio import PortfolioSummary, PortfolioValuationEngine


@pytest.fixture(scope="session")
def table() -> MortalityTable:
    return MortalityTable.from_soa_ilt()


@pytest.fixture(scope="session")
def engine(table: MortalityTable) -> PortfolioValuationEngine:
    interest = InterestAssumption(annual_rate=0.05)
    expense = ExpenseAssumption(
        percent_of_premium_first=0.35,
        percent_of_premium_renewal=0.05,
        per_policy_first=200.0,
        per_policy_renewal=20.0,
    )
    lapse = LapseAssumption(flat_annual_rate=0.03)
    return PortfolioValuationEngine(table=table, interest=interest, expense=expense, lapse=lapse)


class TestPortfolioVectorizedEquivalence:
    """Validate that vectorized portfolio valuation matches individual GPV engine calculations."""

    def test_single_term_policy_matches_individual_gpv(
        self, table: MortalityTable, engine: PortfolioValuationEngine
    ) -> None:
        contract = PolicyContract(
            product_type=ProductType.TERM,
            issue_age=30,
            term=20,
            sum_assured=1_000_000,
        )
        gross_premium = 3000.0

        # Individual GPV Engine
        gpv = GrossPremiumValuation(
            table=table,
            interest=engine.interest,
            expense=engine.expense,
            lapse=engine.lapse,
        )
        individual_bel = gpv.best_estimate_liability(contract, gross_premium=gross_premium)
        individual_cf = gpv.project(contract, gross_premium=gross_premium)
        individual_pvfp = float(individual_cf["pv_premium"].sum())
        individual_pvfb = float((individual_cf["pv_death_claims"] + individual_cf["pv_maturity"]).sum())
        individual_pvfe = float(individual_cf["pv_expense"].sum())

        # Portfolio Engine
        df_single = pd.DataFrame([{
            "policy_id": "POL-0001",
            "issue_age": 30,
            "term_years": 20,
            "sum_assured": 1_000_000,
            "gross_premium": 3000.0,
            "product_type": "term",
            "policy_duration_years": 0,
        }])
        df_norm = engine.load_portfolio_df(df_single)
        res_df, summary = engine.evaluate_portfolio(df_norm)

        assert summary.total_policies == 1
        assert summary.total_sum_assured == 1_000_000.0
        assert np.isclose(summary.total_pvfb, individual_pvfb, rtol=1e-3)
        assert np.isclose(summary.total_pvfp, individual_pvfp, rtol=1e-3)
        assert np.isclose(summary.total_pvfe, individual_pvfe, rtol=1e-3)
        assert np.isclose(summary.total_bel, individual_bel, rtol=1e-3)

    def test_multi_product_portfolio_consistency(
        self, table: MortalityTable, engine: PortfolioValuationEngine
    ) -> None:
        policies = [
            {"policy_id": "T1", "issue_age": 25, "term_years": 30, "sum_assured": 500_000, "gross_premium": 1200.0, "product_type": "term", "policy_duration_years": 2},
            {"policy_id": "E1", "issue_age": 35, "term_years": 20, "sum_assured": 1_000_000, "gross_premium": 35000.0, "product_type": "endowment", "policy_duration_years": 5},
            {"policy_id": "W1", "issue_age": 45, "term_years": 65, "sum_assured": 250_000, "gross_premium": 4000.0, "product_type": "whole_life", "policy_duration_years": 10},
            {"policy_id": "P1", "issue_age": 40, "term_years": 15, "sum_assured": 750_000, "gross_premium": 28000.0, "product_type": "pure_endowment", "policy_duration_years": 0},
        ]
        df = engine.load_portfolio_df(pd.DataFrame(policies))
        res_df, summary = engine.evaluate_portfolio(df)

        assert summary.total_policies == 4
        assert summary.total_sum_assured == 2_500_000.0
        assert len(summary.product_breakdown) == 4
        assert "term" in summary.product_breakdown
        assert "endowment" in summary.product_breakdown
        assert "whole_life" in summary.product_breakdown
        assert "pure_endowment" in summary.product_breakdown

        # Check that product breakdown sums match totals
        total_pvfb_breakdown = sum(p["pvfb"] for p in summary.product_breakdown.values())
        total_pvfp_breakdown = sum(p["pvfp"] for p in summary.product_breakdown.values())
        total_bel_breakdown = sum(p["bel"] for p in summary.product_breakdown.values())

        assert np.isclose(summary.total_pvfb, total_pvfb_breakdown, rtol=1e-4)
        assert np.isclose(summary.total_pvfp, total_pvfp_breakdown, rtol=1e-4)
        assert np.isclose(summary.total_bel, total_bel_breakdown, rtol=1e-4)


class TestPortfolioBreakdownsAndCSV:
    """Test cohort breakdowns and CSV loading capabilities."""

    def test_csv_string_loading_and_defaults(self, engine: PortfolioValuationEngine) -> None:
        csv_data = """policy_id,issue_age,term_years,sum_assured,gross_premium,product_type,policy_duration_years
POL-001,28,20,500000,1500,term,0
POL-002,42,15,1000000,42000,endowment,3
"""
        df = engine.load_portfolio_df(csv_data)
        assert len(df) == 2
        assert list(df["policy_id"]) == ["POL-001", "POL-002"]
        assert df.loc[1, "remaining_term"] == 12  # 15 - 3

    def test_missing_required_column_raises(self, engine: PortfolioValuationEngine) -> None:
        invalid_csv = "policy_id,term_years\nPOL-1,20"
        with pytest.raises(ValueError, match="missing required columns"):
            engine.load_portfolio_df(invalid_csv)

    def test_empty_portfolio_raises(self, engine: PortfolioValuationEngine) -> None:
        empty_df = pd.DataFrame(columns=["policy_id", "issue_age", "term_years", "sum_assured", "gross_premium", "product_type", "remaining_term", "remaining_prem_term", "attained_age", "policy_duration_years"])
        with pytest.raises(ValueError, match="Cannot evaluate empty portfolio"):
            engine.evaluate_portfolio(empty_df)


class TestPortfolioBenchmark:
    """Performance benchmarks testing high-throughput portfolio valuation."""

    def test_10k_policies_benchmark_under_2_seconds(self, engine: PortfolioValuationEngine) -> None:
        # Generate 10,000 synthetic life insurance policies
        raw_df = PortfolioValuationEngine.generate_synthetic_portfolio(n_policies=10_000, seed=42)
        assert len(raw_df) == 10_000

        t0 = time.perf_counter()
        norm_df = engine.load_portfolio_df(raw_df)
        res_df, summary = engine.evaluate_portfolio(norm_df)
        elapsed = time.perf_counter() - t0

        print(f"\n[BENCHMARK] Evaluated 10,000 policies in {elapsed:.4f} seconds ({10000/elapsed:,.0f} policies/sec).")

        assert summary.total_policies == 10_000
        assert summary.total_sum_assured > 0
        assert len(summary.annual_cash_flows) > 0
        assert elapsed < 2.0, f"Expected < 2.0s for 10k policies, took {elapsed:.4f}s"


class TestPortfolioAPIEndpoints:
    """Test FastAPI portfolio valuation endpoints."""

    def test_portfolio_csv_upload_endpoint(self) -> None:
        from fastapi.testclient import TestClient
        from actuary_engine.main import app

        client = TestClient(app)
        csv_content = b"policy_id,issue_age,term_years,sum_assured,gross_premium,product_type,policy_duration_years\nPOL-1,30,20,1000000,2500,term,0\nPOL-2,40,15,500000,18000,endowment,2\n"

        response = client.post(
            "/api/v1/valuation/portfolio/csv",
            files={"file": ("test_portfolio.csv", csv_content, "text/csv")},
            data={"interest_rate": 0.05},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_policies"] == 2
        assert data["total_sum_assured"] == 1_500_000.0
        assert "total_bel" in data
        assert "product_breakdown" in data
        assert len(data["sample_seriatim"]) == 2

    def test_portfolio_json_endpoint(self) -> None:
        from fastapi.testclient import TestClient
        from actuary_engine.main import app

        client = TestClient(app)
        payload = {
            "policies": [
                {"policy_id": "P1", "issue_age": 30, "term_years": 20, "sum_assured": 1000000, "gross_premium": 2500, "product_type": "term"},
                {"policy_id": "P2", "issue_age": 45, "term_years": 10, "sum_assured": 500000, "gross_premium": 25000, "product_type": "endowment"},
            ],
            "interest_rate": 0.05,
        }
        response = client.post("/api/v1/valuation/portfolio", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["total_policies"] == 2
        assert data["total_sum_assured"] == 1_500_000.0

    def test_portfolio_sample_csv_download(self) -> None:
        from fastapi.testclient import TestClient
        from actuary_engine.main import app

        client = TestClient(app)
        response = client.get("/api/v1/valuation/portfolio/sample_csv?n_policies=100")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/csv; charset=utf-8"
        lines = response.text.strip().split("\n")
        assert len(lines) == 101  # header + 100 policies

