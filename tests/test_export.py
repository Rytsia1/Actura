import io
import json
import time
import zipfile
import openpyxl
import pytest
from fastapi.testclient import TestClient

from actuary_engine.api.main import app
from actuary_engine.api.job_manager import JobStatus, job_manager
from actuary_engine.services.export_service import export_service

client = TestClient(app)


@pytest.fixture
def deterministic_run_id():
    """Execute a deterministic valuation and return its persisted job ID."""
    payload = {
        "product_type": "endowment",
        "issue_age": 35,
        "term": 20,
        "sum_assured": 500000.0,
        "premium_paying_term": 20,
        "interest_rate": 0.05,
        "table_id": "soa_ilt",
        "expense": {
            "percent_of_premium_first": 0.35,
            "percent_of_premium_renewal": 0.05,
            "per_policy_first": 200.0,
            "per_policy_renewal": 20.0,
        },
        "lapse": {
            "flat_annual_rate": 0.03,
        },
    }
    res = client.post("/api/v1/valuation/deterministic", json=payload)
    assert res.status_code == 200, res.json()

    jobs = client.get("/api/v1/jobs?limit=5").json()
    assert len(jobs) > 0
    # First job should be the one just created
    job = jobs[0]
    assert job["status"] == "COMPLETED"
    assert job["result"] is not None
    return job["job_id"]


def test_export_excel_all_nine_sheets(deterministic_run_id):
    """Test generating a multi-sheet Excel (.xlsx) workbook containing all 9 mandated sheets."""
    res = client.get(f"/api/v1/export/{deterministic_run_id}?format=xlsx")
    assert res.status_code == 200
    assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in res.headers["content-type"]
    assert "attachment; filename=" in res.headers["content-disposition"]
    assert res.headers["content-disposition"].endswith('.xlsx"')

    # Load workbook from response bytes
    wb = openpyxl.load_workbook(io.BytesIO(res.content))
    expected_sheets = [
        "Summary",
        "Model",
        "Assumptions",
        "Projection",
        "Valuation",
        "Risk",
        "Sensitivity",
        "Validation",
        "Metadata",
    ]
    for s_name in expected_sheets:
        assert s_name in wb.sheetnames, f"Sheet '{s_name}' missing from generated workbook"

    # Verify Summary Sheet content
    ws_sum = wb["Summary"]
    content_text = [str(cell.value) for row in ws_sum.rows for cell in row if cell.value is not None]
    assert any("ACTURA VALUATION ENGINE" in t for t in content_text)
    assert any(deterministic_run_id in t for t in content_text)
    assert any("Best Estimate Liability (BEL)" in t for t in content_text)

    # Verify Model Sheet content
    ws_model = wb["Model"]
    model_text = [str(cell.value) for row in ws_model.rows for cell in row if cell.value is not None]
    assert any("Endowment" in t for t in model_text)
    assert any("500000" in t for t in model_text)

    # Verify Assumptions Sheet content
    ws_ass = wb["Assumptions"]
    ass_text = [str(cell.value) for row in ws_ass.rows for cell in row if cell.value is not None]
    assert any("soa_ilt" in t for t in ass_text)

    # Verify Projection Sheet content
    ws_proj = wb["Projection"]
    assert ws_proj.max_row >= 24  # title block + headers + 20 projection durations

    # Verify Metadata Sheet content
    ws_meta = wb["Metadata"]
    meta_text = [str(cell.value) for row in ws_meta.rows for cell in row if cell.value is not None]
    assert any("Model Version" in t for t in meta_text)
    assert any("Engine Version" in t for t in meta_text)
    assert any("Random Seed" in t for t in meta_text)
    assert any("Simulation Count" in t for t in meta_text)


def test_export_csv_and_zip(deterministic_run_id):
    """Test generating structured multi-section CSV, single-sheet CSV, and ZIP bundle."""
    # 1. Multi-section CSV
    res_csv = client.get(f"/api/v1/export/{deterministic_run_id}?format=csv")
    assert res_csv.status_code == 200
    assert "text/csv" in res_csv.headers["content-type"]
    csv_text = res_csv.text
    assert "# ACTURA ACTUARIAL VALUATION REPORT" in csv_text
    assert "# SECTION 1: SUMMARY" in csv_text
    assert "# SECTION 2: MODEL" in csv_text
    assert "# SECTION 3: ASSUMPTIONS" in csv_text
    assert "# SECTION 4: PROJECTION" in csv_text
    assert "# SECTION 5: VALUATION" in csv_text
    assert "# SECTION 9: METADATA" in csv_text
    assert deterministic_run_id in csv_text

    # 2. Single-sheet CSV (Projection)
    res_sheet = client.get(f"/api/v1/export/{deterministic_run_id}?format=csv&sheet=projection")
    assert res_sheet.status_code == 200
    sheet_text = res_sheet.text
    assert "Duration,Age,Inforce_lx,Deaths_dx,Premium_Income" in sheet_text
    # Check 21 duration rows (t=0..20) + 1 header
    lines = [line for line in sheet_text.strip().split("\n") if line]
    assert len(lines) == 22

    # 3. ZIP bundle of individual CSVs
    res_zip = client.get(f"/api/v1/export/{deterministic_run_id}?format=csv&as_zip=true")
    assert res_zip.status_code == 200
    assert "application/zip" in res_zip.headers["content-type"]
    zf = zipfile.ZipFile(io.BytesIO(res_zip.content))
    namelist = zf.namelist()
    assert len(namelist) == 9
    assert any("Summary.csv" in name for name in namelist)
    assert any("Projection.csv" in name for name in namelist)
    assert any("Metadata.csv" in name for name in namelist)


def test_export_json_structure_and_metadata(deterministic_run_id):
    """Test exporting complete structured JSON with exact reproducibility metadata."""
    res = client.get(f"/api/v1/export/{deterministic_run_id}?format=json")
    assert res.status_code == 200
    data = res.json()

    # Verify all 9 sections exist
    required_sections = [
        "executive_summary",
        "product_definition",
        "assumptions",
        "projection",
        "valuation_results",
        "risk_metrics",
        "sensitivity",
        "validation_results",
        "reproducibility_metadata",
    ]
    for sec in required_sections:
        assert sec in data, f"Section '{sec}' missing from exported JSON"

    # Verify Executive Summary
    exec_sum = data["executive_summary"]
    assert exec_sum["run_id"] == deterministic_run_id
    assert exec_sum["status"] == "COMPLETED"
    assert len(exec_sum["key_metrics"]) > 0

    # Verify Exact Values Match Persisted Result
    job = job_manager.get_job(deterministic_run_id)
    persisted_result = job.result
    val_results = {row["Component"]: row["Value"] for row in data["valuation_results"]}
    assert round(val_results["Best Estimate Liability"], 2) == round(persisted_result["bel"], 2)
    assert round(val_results["Annual Net Premium"], 2) == round(persisted_result["annual_net_premium"], 2)
    assert round(val_results["Net Single Premium"], 2) == round(persisted_result["nsp"], 2)

    # Verify Reproducibility Metadata
    meta = data["reproducibility_metadata"]
    assert "model_version" in meta
    assert "engine_version" in meta
    assert "seed" in meta
    assert "simulation_count" in meta
    assert meta["run_id"] == deterministic_run_id
    assert "dependencies" in meta


def test_export_stochastic_job():
    """Test exporting a stochastic Monte Carlo simulation run with quantile trajectories."""
    # Register a simulated completed stochastic job in job_manager
    sim_result = {
        "mean_bel": 154200.50,
        "std_bel": 12450.25,
        "min_bel": 118000.0,
        "max_bel": 210000.0,
        "var_95": 178000.0,
        "cvar_95": 189500.0,
        "var_99": 198000.0,
        "cvar_99": 204000.0,
        "timesteps": [0, 1, 2, 3, 4, 5],
        "quantiles": {
            "p5": [0.0, 12000.0, 25000.0, 40000.0, 58000.0, 78000.0],
            "p25": [0.0, 15000.0, 31000.0, 49000.0, 70000.0, 95000.0],
            "p50": [0.0, 18000.0, 38000.0, 60000.0, 85000.0, 115000.0],
            "p75": [0.0, 22000.0, 46000.0, 72000.0, 102000.0, 138000.0],
            "p95": [0.0, 28000.0, 58000.0, 92000.0, 130000.0, 175000.0],
        },
        "terminal_distribution": {
            "mean": 154200.50,
            "std": 12450.25,
            "skewness": 0.35,
            "var_95": 178000.0,
            "cvar_95": 189500.0,
        },
    }
    run_meta = {
        "valuation_type": "Stochastic",
        "seed": 424242,
        "n_scenarios": 2000,
        "engine_version": "0.3.0",
        "model_version": "stoch-endowment-v1",
        "table_id": "soa_ilt",
    }
    orig_req = {
        "product_type": "endowment",
        "issue_age": 30,
        "term": 20,
        "sum_assured": 1000000.0,
        "vasicek": {"r0": 0.05, "kappa": 0.20, "theta": 0.05, "sigma": 0.015},
    }

    job = job_manager.create_job(total_paths=2000, run_metadata=run_meta, original_request=orig_req)
    # Mark as completed
    from sqlalchemy import update
    stmt = (
        update(job_manager.jobs_table)
        .where(job_manager.jobs_table.c.job_id == job.job_id)
        .values(status="COMPLETED", progress=100.0, completed_paths=2000, result=json.dumps(sim_result))
    )
    with job_manager.engine.begin() as conn:
        conn.execute(stmt)

    # Test Excel export
    res_xl = client.get(f"/api/v1/export/{job.job_id}?format=xlsx")
    assert res_xl.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(res_xl.content))
    assert "Risk" in wb.sheetnames
    assert "Projection" in wb.sheetnames

    # Test JSON export
    res_json = client.get(f"/api/v1/export/{job.job_id}?format=json")
    assert res_json.status_code == 200
    data = res_json.json()
    assert data["reproducibility_metadata"]["seed"] == 424242
    assert data["reproducibility_metadata"]["simulation_count"] == 2000
    assert data["executive_summary"]["valuation_type"] == "Stochastic"
    km_map = {m["Metric"]: m["Value"] for m in data["executive_summary"]["key_metrics"]}
    assert km_map["Mean BEL"] == 154200.50
    assert km_map["Value at Risk (VaR 95%)"] == 178000.0


def test_export_ifrs17_job():
    """Test exporting an IFRS 17 valuation run with CSM schedules."""
    payload = {
        "product_type": "term",
        "issue_age": 40,
        "term": 10,
        "sum_assured": 50000.0,
        "premium_paying_term": 10,
        "interest_rate": 0.04,
        "gross_premium": 250.0,
        "ra_ratio": 0.06,
    }
    res = client.post("/api/v1/valuation/ifrs17", json=payload)
    assert res.status_code == 200

    jobs = client.get("/api/v1/jobs?limit=5").json()
    ifrs_job = None
    for j in jobs:
        if j.get("run_metadata", {}).get("valuation_type") == "IFRS17":
            ifrs_job = j
            break
    assert ifrs_job is not None

    res_json = client.get(f"/api/v1/export/{ifrs_job['job_id']}?format=json")
    assert res_json.status_code == 200
    data = res_json.json()
    assert data["executive_summary"]["valuation_type"] == "IFRS17"
    assert len(data["projection"]) == 11  # 11 balance sheet points (years 0..10)
    assert data["projection"][0]["Year"] == 0
    assert data["projection"][-1]["Year"] == 10


def test_failed_and_missing_job_error_handling():
    """Test proper HTTP 404 and 400 error handling for invalid or failed runs."""
    # 1. Non-existent job
    res_missing = client.get("/api/v1/export/non-existent-uuid-12345?format=xlsx")
    assert res_missing.status_code == 404
    assert "not found" in res_missing.json()["detail"].lower()

    # 2. Failed job
    failed_job = job_manager.create_job(total_paths=100)
    from sqlalchemy import update
    stmt = (
        update(job_manager.jobs_table)
        .where(job_manager.jobs_table.c.job_id == failed_job.job_id)
        .values(status="FAILED", error="Numerical instability in ESG matrix decomposition")
    )
    with job_manager.engine.begin() as conn:
        conn.execute(stmt)

    res_failed = client.get(f"/api/v1/export/{failed_job.job_id}?format=xlsx")
    assert res_failed.status_code == 400
    assert "failed" in res_failed.json()["detail"].lower()

    # 3. Job in PROCESSING state
    proc_job = job_manager.create_job(total_paths=500)
    job_manager.set_processing(proc_job.job_id)
    res_proc = client.get(f"/api/v1/export/{proc_job.job_id}?format=json")
    assert res_proc.status_code == 400
    assert "processing" in res_proc.json()["detail"].lower()


def test_large_projection_output():
    """Test exporting a long-duration policy (50 years) with complete projection records."""
    payload = {
        "product_type": "endowment",
        "issue_age": 20,
        "term": 50,
        "sum_assured": 250000.0,
        "premium_paying_term": 50,
        "interest_rate": 0.045,
        "table_id": "soa_ilt",
    }
    res = client.post("/api/v1/valuation/deterministic", json=payload)
    assert res.status_code == 200

    jobs = client.get("/api/v1/jobs?limit=1").json()
    job_id = jobs[0]["job_id"]

    # Export to Excel
    res_xl = client.get(f"/api/v1/export/{job_id}?format=xlsx")
    assert res_xl.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(res_xl.content))
    ws_proj = wb["Projection"]
    # 4 rows header/title + 51 duration rows (0..50) = 55 rows
    assert ws_proj.max_row == 55

    # Export to CSV (Projection sheet only)
    res_csv = client.get(f"/api/v1/export/{job_id}?format=csv&sheet=projection")
    assert res_csv.status_code == 200
    lines = [l for l in res_csv.text.strip().split("\n") if l]
    # Header + 51 durations = 52 lines
    assert len(lines) == 52

    # Export to JSON
    res_json = client.get(f"/api/v1/export/{job_id}?format=json")
    assert res_json.status_code == 200
    data = res_json.json()
    assert len(data["projection"]) == 51
    assert data["projection"][0]["Duration"] == 0
    assert data["projection"][-1]["Duration"] == 50
