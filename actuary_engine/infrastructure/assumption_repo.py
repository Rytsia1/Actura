"""
Repository for managing version-controlled actuarial assumptions.
Supports retrieving latest versions, history, and immutable updates.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Optional

from sqlalchemy import Table, Column, String, Float, Integer, select, update, desc, and_, text

from actuary_engine.infrastructure.database import engine, metadata, init_db

assumptions_table = Table(
    "assumptions",
    metadata,
    Column("id", String, primary_key=True),
    Column("version", Integer, primary_key=True),
    Column("name", String, nullable=False),
    Column("type", String, nullable=False),
    Column("description", String, default=""),
    Column("source", String, default=""),
    Column("effective_date", String, default=""),
    Column("status", String, default="ACTIVE"),
    Column("parameters", String, nullable=False),
    Column("created_by", String, default="system"),
    Column("created_at", Float, default=time.time),
    Column("updated_at", Float, default=time.time),
    extend_existing=True,
)

init_db()

class AssumptionRepository:
    def __init__(self) -> None:
        self.engine = engine

    def _row_to_dict(self, row: Any) -> dict[str, Any]:
        return {
            "id": row.id,
            "version": row.version,
            "name": row.name,
            "type": row.type,
            "description": row.description,
            "source": row.source,
            "effective_date": row.effective_date,
            "status": row.status,
            "parameters": json.loads(row.parameters) if row.parameters else {},
            "created_by": row.created_by,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    def create_assumption(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a completely new assumption (version 1)."""
        assump_id = data.get("id") or str(uuid.uuid4())
        record = {
            "id": assump_id,
            "version": 1,
            "name": data.get("name", "Unnamed"),
            "type": data.get("type", "UNKNOWN"),
            "description": data.get("description", ""),
            "source": data.get("source", ""),
            "effective_date": data.get("effective_date", ""),
            "status": data.get("status", "ACTIVE"),
            "parameters": json.dumps(data.get("parameters", {})),
            "created_by": data.get("created_by", "system"),
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        
        stmt = assumptions_table.insert().values(**record)
        with self.engine.begin() as conn:
            conn.execute(stmt)
            
        return self.get_version(assump_id, 1)

    def create_new_version(self, id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new version of an existing assumption, keeping history immutable."""
        # Find max version
        stmt_max = select(assumptions_table.c.version).where(assumptions_table.c.id == id).order_by(desc(assumptions_table.c.version)).limit(1)
        with self.engine.connect() as conn:
            row = conn.execute(stmt_max).fetchone()
            if not row:
                raise ValueError(f"Assumption {id} not found.")
            next_version = row.version + 1

        record = {
            "id": id,
            "version": next_version,
            "name": data.get("name"),
            "type": data.get("type"),
            "description": data.get("description", ""),
            "source": data.get("source", ""),
            "effective_date": data.get("effective_date", ""),
            "status": data.get("status", "ACTIVE"),
            "parameters": json.dumps(data.get("parameters", {})),
            "created_by": data.get("created_by", "system"),
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        
        stmt = assumptions_table.insert().values(**record)
        with self.engine.begin() as conn:
            conn.execute(stmt)
            
        return self.get_version(id, next_version)

    def get_latest_version(self, id: str) -> Optional[dict[str, Any]]:
        """Retrieve the highest version of an assumption."""
        stmt = select(assumptions_table).where(assumptions_table.c.id == id).order_by(desc(assumptions_table.c.version)).limit(1)
        with self.engine.connect() as conn:
            row = conn.execute(stmt).fetchone()
            if row:
                return self._row_to_dict(row)
        return None

    def get_version(self, id: str, version: int) -> Optional[dict[str, Any]]:
        """Retrieve a specific version of an assumption."""
        stmt = select(assumptions_table).where(and_(assumptions_table.c.id == id, assumptions_table.c.version == version))
        with self.engine.connect() as conn:
            row = conn.execute(stmt).fetchone()
            if row:
                return self._row_to_dict(row)
        return None

    def get_history(self, id: str) -> list[dict[str, Any]]:
        """Retrieve all versions of an assumption."""
        stmt = select(assumptions_table).where(assumptions_table.c.id == id).order_by(desc(assumptions_table.c.version))
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def list_latest_assumptions(self, assump_type: Optional[str] = None) -> list[dict[str, Any]]:
        """Retrieve the latest version of all assumptions, optionally filtered by type."""
        # Using a subquery to find the max version for each ID
        subq = select(
            assumptions_table.c.id,
            assumptions_table.c.version
        ).group_by(assumptions_table.c.id).having(assumptions_table.c.version == text("MAX(assumptions.version)")).subquery()
        
        # SQLite doesn't support the above cleanly sometimes, so let's do a simpler approach:
        # Get all rows, then group in python, since number of assumptions is small.
        stmt = select(assumptions_table).order_by(desc(assumptions_table.c.version))
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).fetchall()
            
            latest_map = {}
            for row in rows:
                if row.id not in latest_map:
                    if assump_type is None or row.type == assump_type:
                        latest_map[row.id] = self._row_to_dict(row)
                        
            return list(latest_map.values())

    def update_status(self, id: str, status: str) -> Optional[dict[str, Any]]:
        """Update the status of ALL versions of an assumption (e.g., DEACTIVATED)."""
        stmt = update(assumptions_table).where(assumptions_table.c.id == id).values(status=status, updated_at=time.time())
        with self.engine.begin() as conn:
            conn.execute(stmt)
        return self.get_latest_version(id)

assumption_repo = AssumptionRepository()
