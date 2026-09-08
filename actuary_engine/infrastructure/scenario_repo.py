"""
Repository for managing base actuarial models and assumption scenarios.
Supports persistence, overrides, duplication, and database seeding.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Optional

from sqlalchemy import (
    Table,
    Column,
    String,
    Float,
    Integer,
    select,
    update,
    delete,
    desc,
    and_,
    text,
)

from actuary_engine.infrastructure.database import engine, metadata, init_db
from actuary_engine.infrastructure.auth_repo import auth_repo

base_models_table = Table(
    "base_models",
    metadata,
    Column("id", String, primary_key=True),
    Column("name", String, nullable=False),
    Column("description", String, default=""),
    Column("project_id", String, nullable=False, default="default-project"),
    Column("product_type", String, nullable=False),
    Column("issue_age", Integer, nullable=False),
    Column("term", Integer, nullable=True),
    Column("sum_assured", Float, nullable=False),
    Column("premium_paying_term", Integer, nullable=True),
    Column("interest_rate", Float, nullable=False),
    Column("table_id", String, default="soa_ilt"),
    Column("expense", String, nullable=False),
    Column("lapse", String, nullable=False),
    Column("gross_premium", Float, nullable=True),
    Column("created_at", Float, default=time.time),
    Column("updated_at", Float, default=time.time),
    extend_existing=True,
)

scenarios_table = Table(
    "scenarios",
    metadata,
    Column("id", String, primary_key=True),
    Column("name", String, nullable=False),
    Column("description", String, default=""),
    Column("base_model_id", String, nullable=False),
    Column("overrides", String, nullable=False),
    Column("status", String, default="ACTIVE"),
    Column("created_at", Float, default=time.time),
    Column("updated_at", Float, default=time.time),
    extend_existing=True,
)

init_db()


class ScenarioRepository:
    def __init__(self) -> None:
        self.engine = engine
        self._seed_defaults()

    def _seed_defaults(self) -> None:
        """Seed initial auth and base models if not present."""
        # 1. Seed Auth Defaults
        from passlib.context import CryptContext
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        
        default_org_id = "default-org"
        if not auth_repo.get_project_by_id("default-project"):
            auth_repo.create_organization("Default Organization", org_id=default_org_id)
            auth_repo.create_project("Default Project", default_org_id, "System default project", project_id="default-project")
        
        if not auth_repo.get_user_by_username("admin"):
            auth_repo.create_user(
                username="admin",
                hashed_password=pwd_context.hash("admin"),
                role="Admin",
                organization_id=default_org_id,
            )

        with self.engine.begin() as conn:
            # Check if default model exists
            sel = select(base_models_table.c.id).where(base_models_table.c.id == "default-endowment")
            if not conn.execute(sel).fetchone():
                now = time.time()
                default_models = [
                    {
                        "id": "default-endowment",
                        "name": "20-Year Endowment (Baseline)",
                        "description": "Standard 20-Year Endowment contract, issue age 30, sum assured 1,000,000, 5% interest rate",
                        "project_id": "default-project",
                        "product_type": "endowment",
                        "issue_age": 30,
                        "term": 20,
                        "sum_assured": 1000000.0,
                        "premium_paying_term": 20,
                        "interest_rate": 0.05,
                        "table_id": "soa_ilt",
                        "expense": json.dumps({
                            "percent_of_premium_first": 0.35,
                            "percent_of_premium_renewal": 0.05,
                            "per_policy_first": 200.0,
                            "per_policy_renewal": 20.0,
                        }),
                        "lapse": json.dumps({
                            "flat_annual_rate": 0.03,
                            "duration_rates": [0.10, 0.07, 0.05, 0.04, 0.03],
                        }),
                        "gross_premium": None,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": "default-term",
                        "name": "30-Year Term Life",
                        "description": "30-Year Term Life contract, issue age 35, sum assured 750,000, 4.5% interest rate",
                        "product_type": "term",
                        "issue_age": 35,
                        "term": 30,
                        "sum_assured": 750000.0,
                        "premium_paying_term": 30,
                        "interest_rate": 0.045,
                        "table_id": "soa_ilt",
                        "expense": json.dumps({
                            "percent_of_premium_first": 0.35,
                            "percent_of_premium_renewal": 0.05,
                            "per_policy_first": 200.0,
                            "per_policy_renewal": 20.0,
                        }),
                        "lapse": json.dumps({
                            "flat_annual_rate": 0.03,
                            "duration_rates": [0.08, 0.05, 0.04, 0.03],
                        }),
                        "gross_premium": None,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": "default-whole-life",
                        "name": "Whole Life",
                        "description": "Permanent Whole Life contract, issue age 40, sum assured 500,000, 5% interest rate",
                        "product_type": "whole_life",
                        "issue_age": 40,
                        "term": None,
                        "sum_assured": 500000.0,
                        "premium_paying_term": None,
                        "interest_rate": 0.05,
                        "table_id": "soa_ilt",
                        "expense": json.dumps({
                            "percent_of_premium_first": 0.35,
                            "percent_of_premium_renewal": 0.05,
                            "per_policy_first": 200.0,
                            "per_policy_renewal": 20.0,
                        }),
                        "lapse": json.dumps({
                            "flat_annual_rate": 0.02,
                        }),
                        "gross_premium": None,
                        "created_at": now,
                        "updated_at": now,
                    },
                ]
                for m in default_models:
                    conn.execute(base_models_table.insert().values(**m))

            # Check if default scenarios exist
            sel_scen = select(scenarios_table.c.id).where(scenarios_table.c.id == "scen-base")
            if not conn.execute(sel_scen).fetchone():
                now = time.time()
                initial_scenarios = [
                    {
                        "id": "scen-base",
                        "name": "Base",
                        "description": "Baseline assumptions with zero shocks",
                        "base_model_id": "default-endowment",
                        "overrides": json.dumps({}),
                        "status": "ACTIVE",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": "scen-high-mortality",
                        "name": "High Mortality",
                        "description": "+10% mortality shock (1.10x)",
                        "base_model_id": "default-endowment",
                        "overrides": json.dumps({"mortality_multiplier": 1.10}),
                        "status": "ACTIVE",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": "scen-high-lapse",
                        "name": "High Lapse",
                        "description": "+5% additive lapse shock",
                        "base_model_id": "default-endowment",
                        "overrides": json.dumps({"lapse_rate_delta": 0.05}),
                        "status": "ACTIVE",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": "scen-low-interest",
                        "name": "Low Interest",
                        "description": "-100 bps interest rate shock (-0.01)",
                        "base_model_id": "default-endowment",
                        "overrides": json.dumps({"interest_rate_bps": -100.0, "interest_rate_delta": -0.01}),
                        "status": "ACTIVE",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": "scen-high-expense",
                        "name": "High Expense",
                        "description": "+10% expense shock (1.10x)",
                        "base_model_id": "default-endowment",
                        "overrides": json.dumps({"expense_multiplier": 1.10}),
                        "status": "ACTIVE",
                        "created_at": now,
                        "updated_at": now,
                    },
                ]
                for sc in initial_scenarios:
                    conn.execute(scenarios_table.insert().values(**sc))

    # ────────────────────────────────────────────────────────────
    # Base Model Operations
    # ────────────────────────────────────────────────────────────

    def _row_to_base_model(self, row: Any) -> dict[str, Any]:
        return {
            "id": row.id,
            "name": row.name,
            "description": row.description,
            "product_type": row.product_type,
            "issue_age": row.issue_age,
            "term": row.term,
            "sum_assured": row.sum_assured,
            "premium_paying_term": row.premium_paying_term,
            "interest_rate": row.interest_rate,
            "table_id": row.table_id,
            "expense": json.loads(row.expense) if row.expense else {},
            "lapse": json.loads(row.lapse) if row.lapse else {},
            "gross_premium": row.gross_premium,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    def list_base_models(self) -> list[dict[str, Any]]:
        """List all registered base models."""
        stmt = select(base_models_table).order_by(base_models_table.c.created_at)
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).fetchall()
            return [self._row_to_base_model(r) for r in rows]

    def get_base_model(self, model_id: str) -> Optional[dict[str, Any]]:
        """Retrieve a specific base model by ID."""
        stmt = select(base_models_table).where(base_models_table.c.id == model_id)
        with self.engine.connect() as conn:
            row = conn.execute(stmt).fetchone()
            if row:
                return self._row_to_base_model(row)
        return None

    def create_base_model(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new reusable base model."""
        model_id = data.get("id") or f"model-{uuid.uuid4().hex[:8]}"
        now = time.time()
        record = {
            "id": model_id,
            "name": data.get("name", "Custom Valuation Model"),
            "description": data.get("description", ""),
            "product_type": data.get("product_type", "endowment"),
            "issue_age": data.get("issue_age", 30),
            "term": data.get("term", 20),
            "sum_assured": data.get("sum_assured", 1000000.0),
            "premium_paying_term": data.get("premium_paying_term"),
            "interest_rate": data.get("interest_rate", 0.05),
            "table_id": data.get("table_id", "soa_ilt"),
            "expense": json.dumps(data.get("expense", {})),
            "lapse": json.dumps(data.get("lapse", {})),
            "gross_premium": data.get("gross_premium"),
            "created_at": now,
            "updated_at": now,
        }
        stmt = base_models_table.insert().values(**record)
        with self.engine.begin() as conn:
            conn.execute(stmt)
        return self.get_base_model(model_id)  # type: ignore[return-value]

    # ────────────────────────────────────────────────────────────
    # Scenario Operations
    # ────────────────────────────────────────────────────────────

    def _row_to_scenario(self, row: Any) -> dict[str, Any]:
        return {
            "id": row.id,
            "name": row.name,
            "description": row.description,
            "base_model_id": row.base_model_id,
            "overrides": json.loads(row.overrides) if row.overrides else {},
            "status": row.status,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    def list_scenarios(self, base_model_id: Optional[str] = None, status: Optional[str] = None) -> list[dict[str, Any]]:
        """List scenarios, optionally filtered by base_model_id and status."""
        stmt = select(scenarios_table)
        conditions = []
        if base_model_id:
            conditions.append(scenarios_table.c.base_model_id == base_model_id)
        if status:
            conditions.append(scenarios_table.c.status == status)
        if conditions:
            stmt = stmt.where(and_(*conditions))
        stmt = stmt.order_by(scenarios_table.c.created_at)

        with self.engine.connect() as conn:
            rows = conn.execute(stmt).fetchall()
            return [self._row_to_scenario(r) for r in rows]

    def get_scenario(self, scenario_id: str) -> Optional[dict[str, Any]]:
        """Retrieve a specific scenario by ID."""
        stmt = select(scenarios_table).where(scenarios_table.c.id == scenario_id)
        with self.engine.connect() as conn:
            row = conn.execute(stmt).fetchone()
            if row:
                return self._row_to_scenario(row)
        return None

    def create_scenario(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new scenario."""
        scenario_id = data.get("id") or f"scen-{uuid.uuid4().hex[:8]}"
        now = time.time()
        record = {
            "id": scenario_id,
            "name": data.get("name", "Custom Scenario"),
            "description": data.get("description", ""),
            "base_model_id": data.get("base_model_id", "default-endowment"),
            "overrides": json.dumps(data.get("overrides", {})),
            "status": data.get("status", "ACTIVE"),
            "created_at": now,
            "updated_at": now,
        }
        stmt = scenarios_table.insert().values(**record)
        with self.engine.begin() as conn:
            conn.execute(stmt)
        return self.get_scenario(scenario_id)  # type: ignore[return-value]

    def update_scenario(self, scenario_id: str, data: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Update an existing scenario (name, description, overrides, status)."""
        now = time.time()
        values: dict[str, Any] = {"updated_at": now}
        if "name" in data and data["name"] is not None:
            values["name"] = data["name"]
        if "description" in data and data["description"] is not None:
            values["description"] = data["description"]
        if "base_model_id" in data and data["base_model_id"] is not None:
            values["base_model_id"] = data["base_model_id"]
        if "overrides" in data and data["overrides"] is not None:
            values["overrides"] = json.dumps(data["overrides"])
        if "status" in data and data["status"] is not None:
            values["status"] = data["status"]

        stmt = update(scenarios_table).where(scenarios_table.c.id == scenario_id).values(**values)
        with self.engine.begin() as conn:
            res = conn.execute(stmt)
            if res.rowcount == 0:
                return None
        return self.get_scenario(scenario_id)

    def duplicate_scenario(self, scenario_id: str, new_name: Optional[str] = None) -> Optional[dict[str, Any]]:
        """Duplicate an existing scenario with a new ID and title."""
        original = self.get_scenario(scenario_id)
        if not original:
            return None

        dup_id = f"scen-{uuid.uuid4().hex[:8]}"
        dup_name = new_name or f"Copy of {original['name']}"
        now = time.time()
        record = {
            "id": dup_id,
            "name": dup_name,
            "description": f"Duplicated from {original['name']}. {original.get('description', '')}".strip(),
            "base_model_id": original["base_model_id"],
            "overrides": json.dumps(original["overrides"]),
            "status": original.get("status", "ACTIVE"),
            "created_at": now,
            "updated_at": now,
        }
        stmt = scenarios_table.insert().values(**record)
        with self.engine.begin() as conn:
            conn.execute(stmt)
        return self.get_scenario(dup_id)

    def delete_scenario(self, scenario_id: str) -> bool:
        """Delete a scenario."""
        stmt = delete(scenarios_table).where(scenarios_table.c.id == scenario_id)
        with self.engine.begin() as conn:
            res = conn.execute(stmt)
            return res.rowcount > 0


scenario_repo = ScenarioRepository()
