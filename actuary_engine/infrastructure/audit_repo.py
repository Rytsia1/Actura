"""
Repository for managing audit logs and traceability events.
"""
from __future__ import annotations

import time
import uuid
import json
from typing import Any, Optional

from sqlalchemy import (
    Table,
    Column,
    String,
    Float,
    select,
    insert,
)

from actuary_engine.infrastructure.database import engine, metadata, init_db

audit_logs_table = Table(
    "audit_logs",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=False),
    Column("entity_type", String, nullable=False),  # MODEL, VALUATION, ASSUMPTION
    Column("entity_id", String, nullable=False),
    Column("action", String, nullable=False),       # MODEL_UPDATED, MODEL_APPROVED, VALUATION_STARTED
    Column("previous_value", String, nullable=True),
    Column("new_value", String, nullable=True),
    Column("run_id", String, nullable=True),
    Column("timestamp", Float, default=time.time),
    extend_existing=True,
)

init_db()

class AuditRepository:
    def __init__(self) -> None:
        self.engine = engine

    def log_event(
        self,
        user_id: str,
        entity_type: str,
        entity_id: str,
        action: str,
        previous_value: Optional[dict[str, Any]] = None,
        new_value: Optional[dict[str, Any]] = None,
        run_id: Optional[str] = None
    ) -> dict[str, Any]:
        event_id = str(uuid.uuid4())
        now = time.time()
        
        event_data = {
            "id": event_id,
            "user_id": user_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "action": action,
            "previous_value": json.dumps(previous_value) if previous_value else None,
            "new_value": json.dumps(new_value) if new_value else None,
            "run_id": run_id,
            "timestamp": now,
        }
        
        with self.engine.begin() as conn:
            conn.execute(insert(audit_logs_table).values(event_data))
        
        return event_data

    def get_logs_for_entity(self, entity_type: str, entity_id: str) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            query = select(audit_logs_table).where(
                (audit_logs_table.c.entity_type == entity_type) &
                (audit_logs_table.c.entity_id == entity_id)
            ).order_by(audit_logs_table.c.timestamp.desc())
            
            rows = conn.execute(query).fetchall()
            logs = []
            for row in rows:
                row_dict = dict(row._mapping)
                if row_dict["previous_value"]:
                    row_dict["previous_value"] = json.loads(row_dict["previous_value"])
                if row_dict["new_value"]:
                    row_dict["new_value"] = json.loads(row_dict["new_value"])
                logs.append(row_dict)
            return logs

audit_repo = AuditRepository()
