"""
Test suite for Dynamic Mortality Table Registry, Parsers, and Upload Endpoints.
"""

from __future__ import annotations

import io
import pytest
from fastapi.testclient import TestClient
import numpy as np

from actuary_engine.main import app
from actuary_engine.domain.tables.mortality_table import MortalityTable
from actuary_engine.domain.tables.parsers import (
    TableParsingError,
    parse_csv_mortality_table,
    parse_mortality_file,
    parse_xtbml_mortality_table,
)
from actuary_engine.domain.tables.registry import TableMetadata, TableRegistry, table_registry


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


class TestCSVMortalityParser:
    """Test parsing and validation of CSV mortality tables."""

    def test_standard_age_qx_parsing(self) -> None:
        csv_text = """age,qx
0,0.0050
1,0.0008
2,0.0005
3,0.0004
4,0.0003
5,0.0003
"""
        table = parse_csv_mortality_table(csv_text, name="Test Table")
        assert table.name == "Test Table"
        assert table.min_age == 0
        assert table.max_age == 5
        assert len(table.qx) == 6
        assert table.qx[0] == 0.0050
        # Terminal age condition: qx[-1] = 1.0 enforced if < 1.0
        assert table.qx[-1] == 1.0

    def test_alternative_column_headers_px(self) -> None:
        csv_text = """x,px
20,0.999
21,0.998
22,0.997
"""
        table = parse_csv_mortality_table(csv_text)
        assert table.min_age == 20
        assert table.max_age == 22
        assert np.isclose(table.qx[0], 0.001)

    def test_alternative_column_headers_lx(self) -> None:
        csv_text = """Age,lx
30,100000
31,99500
32,98900
"""
        table = parse_csv_mortality_table(csv_text)
        assert table.min_age == 30
        assert table.max_age == 32
        assert np.isclose(table.qx[0], 0.005)  # (100000 - 99500) / 100000

    def test_missing_age_column_raises(self) -> None:
        invalid_csv = "rate,survival\n0.01,0.99"
        with pytest.raises(TableParsingError, match="Missing required age column"):
            parse_csv_mortality_table(invalid_csv)

    def test_non_contiguous_ages_raises(self) -> None:
        gap_csv = """age,qx
0,0.01
1,0.02
5,0.03
"""
        with pytest.raises(TableParsingError, match="contiguous"):
            parse_csv_mortality_table(gap_csv)

    def test_invalid_probability_bounds_raises(self) -> None:
        bad_prob_csv = """age,qx
20,-0.05
21,0.02
"""
        with pytest.raises(TableParsingError, match="must satisfy 0 <= qx <= 1"):
            parse_csv_mortality_table(bad_prob_csv)

    def test_empty_csv_raises(self) -> None:
        with pytest.raises(TableParsingError, match="empty"):
            parse_csv_mortality_table("")


class TestXTbMLMortalityParser:
    """Test XML-based XTbML mortality table parsing."""

    def test_xtbml_structure_parsing(self) -> None:
        xml_content = """<XTbML>
  <TableIdentity>Sample XML Mortality Table</TableIdentity>
  <Table>
    <Values>
      <Axis Def="Age">
        <Y t="0">0.0045</Y>
        <Y t="1">0.0008</Y>
        <Y t="2">0.0005</Y>
      </Axis>
    </Values>
  </Table>
</XTbML>"""
        table = parse_xtbml_mortality_table(xml_content)
        assert table.name == "Sample XML Mortality Table"
        assert table.min_age == 0
        assert table.max_age == 2
        assert table.qx[0] == 0.0045


class TestTableRegistry:
    """Test in-memory TableRegistry singleton operations."""

    def test_default_soa_ilt_preloaded(self) -> None:
        assert table_registry.has_table("soa_ilt")
        table = table_registry.get_table("soa_ilt")
        assert table.omega == 110
        meta = table_registry.get_metadata("soa_ilt")
        assert meta.is_builtin is True

    def test_register_and_delete_custom_table(self) -> None:
        ages = np.arange(20, 101)
        qx = np.clip(0.001 * (1.08 ** (ages - 20)), 0.0, 1.0)
        qx[-1] = 1.0
        custom_table = MortalityTable(ages=ages, qx=qx, name="Custom Experience 2024")

        meta = table_registry.register_table(
            table_id="custom_exp_2024",
            table=custom_table,
            description="2024 Company Experience",
        )
        assert meta.table_id == "custom_exp_2024"
        assert table_registry.has_table("custom_exp_2024")

        # Delete table
        deleted = table_registry.delete_table("custom_exp_2024")
        assert deleted is True
        assert not table_registry.has_table("custom_exp_2024")

    def test_nonexistent_table_raises_key_error(self) -> None:
        with pytest.raises(KeyError, match="not found in registry"):
            table_registry.get_table("non_existent_table_12345")


class TestTableUploadAPI:
    """Test FastAPI upload, listing, and dynamic valuation linking."""

    def test_list_tables_endpoint(self, client: TestClient) -> None:
        response = client.get("/api/v1/tables")
        assert response.status_code == 200
        tables = response.json()
        assert len(tables) >= 1
        ids = [t["table_id"] for t in tables]
        assert "soa_ilt" in ids

    def test_upload_valid_csv_table(self, client: TestClient) -> None:
        csv_bytes = b"age,qx\n20,0.001\n21,0.0011\n22,0.0012\n23,0.0013\n24,1.0\n"
        response = client.post(
            "/api/v1/tables/upload",
            files={"file": ("custom_mortality.csv", csv_bytes, "text/csv")},
            data={"table_name": "Test Uploaded Table", "table_description": "Uploaded for testing"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["table_name"] == "Test Uploaded Table"
        assert data["min_age"] == 20
        assert data["max_age"] == 24
        assert data["rows_count"] == 5

        table_id = data["table_id"]

        # 1. Verify in list
        list_res = client.get("/api/v1/tables")
        table_ids = [t["table_id"] for t in list_res.json()]
        assert table_id in table_ids

        # 2. Run deterministic valuation using newly uploaded table_id
        val_payload = {
            "product_type": "endowment",
            "issue_age": 20,
            "term": 4,
            "sum_assured": 100_000,
            "table_id": table_id,
            "interest_rate": 0.05,
        }
        val_res = client.post("/api/v1/valuation/deterministic", json=val_payload)
        assert val_res.status_code == 200
        val_data = val_res.json()
        assert val_data["table_id"] == table_id
        assert val_data["table_name"] == "Test Uploaded Table"
        assert val_data["annual_net_premium"] > 0

    def test_upload_invalid_csv_returns_400(self, client: TestClient) -> None:
        bad_csv = b"age,qx\n20,5.50\n21,0.02\n"  # qx > 1.0
        response = client.post(
            "/api/v1/tables/upload",
            files={"file": ("bad_table.csv", bad_csv, "text/csv")},
        )
        assert response.status_code == 400
        assert "validation error" in response.json()["detail"]
