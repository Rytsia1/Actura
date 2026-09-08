"""
Database-backed Job Registry and WebSocket Pub/Sub Manager for Asynchronous Simulations.
Supports both SQLite (local dev) and PostgreSQL (production) via SQLAlchemy Core.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field

from actuary_engine.infrastructure.database import engine, metadata, init_db, check_db_health
from sqlalchemy import Table, Column, String, Float, Integer, select, update, text

class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class SimulationJob(BaseModel):
    """Data model representing the state of an asynchronous simulation task."""

    job_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: JobStatus = Field(default=JobStatus.QUEUED)
    progress: float = Field(default=0.0, ge=0.0, le=100.0)
    completed_paths: int = Field(default=0, ge=0)
    total_paths: int = Field(..., gt=0)
    partial_metrics: dict[str, Any] = Field(default_factory=dict)
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    run_metadata: Optional[dict[str, Any]] = None
    original_request: Optional[dict[str, Any]] = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class JobManager:
    """Manages life-cycle, status updates, and WebSocket broadcasting for simulation jobs."""

    def __init__(self) -> None:
        self.engine = engine
        self.metadata = metadata
        
        self.jobs_table = Table(
            "jobs",
            self.metadata,
            Column("job_id", String, primary_key=True),
            Column("status", String),
            Column("progress", Float),
            Column("completed_paths", Integer),
            Column("total_paths", Integer),
            Column("partial_metrics", String),
            Column("result", String),
            Column("error", String),
            Column("run_metadata", String),
            Column("original_request", String),
            Column("created_at", Float),
            Column("updated_at", Float),
            extend_existing=True,
        )
        
        self._listeners: dict[str, list[asyncio.Queue[dict[str, Any]]]] = {}
        init_db()

    def _row_to_job(self, row: Any) -> SimulationJob:
        return SimulationJob(
            job_id=row.job_id,
            status=JobStatus(row.status),
            progress=row.progress,
            completed_paths=row.completed_paths,
            total_paths=row.total_paths,
            partial_metrics=json.loads(row.partial_metrics) if row.partial_metrics else {},
            result=json.loads(row.result) if row.result else None,
            error=row.error,
            run_metadata=json.loads(row.run_metadata) if row.run_metadata else None,
            original_request=json.loads(row.original_request) if row.original_request else None,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def create_job(self, total_paths: int, run_metadata: Optional[dict[str, Any]] = None, original_request: Optional[dict[str, Any]] = None) -> SimulationJob:
        """Register a new job in QUEUED status."""
        job = SimulationJob(total_paths=total_paths, run_metadata=run_metadata, original_request=original_request)
        
        stmt = self.jobs_table.insert().values(
            job_id=job.job_id,
            status=job.status.value,
            progress=job.progress,
            completed_paths=job.completed_paths,
            total_paths=job.total_paths,
            partial_metrics=json.dumps(job.partial_metrics),
            result=json.dumps(job.result) if job.result else None,
            error=job.error,
            run_metadata=json.dumps(job.run_metadata) if job.run_metadata else None,
            original_request=json.dumps(job.original_request) if job.original_request else None,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )
        with self.engine.begin() as conn:
            conn.execute(stmt)
            
        self._listeners[job.job_id] = []
        return job

    def get_job(self, job_id: str) -> Optional[SimulationJob]:
        """Retrieve job state by ID."""
        stmt = select(self.jobs_table).where(self.jobs_table.c.job_id == job_id)
        with self.engine.connect() as conn:
            row = conn.execute(stmt).fetchone()
            if row:
                return self._row_to_job(row)
        return None

    def set_processing(self, job_id: str) -> None:
        """Mark job as PROCESSING."""
        stmt = (
            update(self.jobs_table)
            .where(self.jobs_table.c.job_id == job_id)
            .values(status=JobStatus.PROCESSING.value, updated_at=time.time())
        )
        with self.engine.begin() as conn:
            conn.execute(stmt)

    async def update_progress(
        self,
        job_id: str,
        completed_paths: int,
        total_paths: int,
        partial_metrics: Optional[dict[str, Any]] = None,
    ) -> None:
        """Update job progress and broadcast PROGRESS event to all active WebSocket listeners."""
        progress = round((completed_paths / total_paths) * 100.0, 1)
        pm_json = json.dumps(partial_metrics) if partial_metrics else "{}"
        
        stmt = (
            update(self.jobs_table)
            .where(self.jobs_table.c.job_id == job_id)
            .values(
                status=JobStatus.PROCESSING.value,
                progress=progress,
                completed_paths=completed_paths,
                total_paths=total_paths,
                partial_metrics=pm_json,
                updated_at=time.time()
            )
        )
        with self.engine.begin() as conn:
            conn.execute(stmt)

        event = {
            "type": "PROGRESS",
            "job_id": job_id,
            "status": JobStatus.PROCESSING.value,
            "percent": progress,
            "completed_paths": completed_paths,
            "total_paths": total_paths,
            "partial_metrics": partial_metrics or {},
        }
        await self._broadcast(job_id, event)

    async def set_completed(self, job_id: str, result_data: dict[str, Any]) -> None:
        """Mark job as COMPLETED and broadcast COMPLETE event with payload."""
        with self.engine.begin() as conn:
            # Need to get total_paths to set completed_paths
            stmt_sel = select(self.jobs_table.c.total_paths).where(self.jobs_table.c.job_id == job_id)
            row = conn.execute(stmt_sel).fetchone()
            if not row:
                return
            total_paths = row.total_paths
            
            stmt_upd = (
                update(self.jobs_table)
                .where(self.jobs_table.c.job_id == job_id)
                .values(
                    status=JobStatus.COMPLETED.value,
                    progress=100.0,
                    completed_paths=total_paths,
                    result=json.dumps(result_data),
                    updated_at=time.time()
                )
            )
            conn.execute(stmt_upd)

        event = {
            "type": "COMPLETE",
            "job_id": job_id,
            "status": JobStatus.COMPLETED.value,
            "percent": 100.0,
            "completed_paths": total_paths,
            "total_paths": total_paths,
            "data": result_data,
        }
        await self._broadcast(job_id, event)

    async def set_failed(self, job_id: str, error_message: str) -> None:
        """Mark job as FAILED and broadcast ERROR event."""
        stmt = (
            update(self.jobs_table)
            .where(self.jobs_table.c.job_id == job_id)
            .values(status=JobStatus.FAILED.value, error=error_message, updated_at=time.time())
        )
        with self.engine.begin() as conn:
            conn.execute(stmt)

        event = {
            "type": "ERROR",
            "job_id": job_id,
            "status": JobStatus.FAILED.value,
            "error": error_message,
        }
        await self._broadcast(job_id, event)

    def set_cancelled(self, job_id: str) -> None:
        """Mark job as CANCELLED."""
        stmt = (
            update(self.jobs_table)
            .where(self.jobs_table.c.job_id == job_id)
            .values(status=JobStatus.CANCELLED.value, updated_at=time.time())
        )
        with self.engine.begin() as conn:
            conn.execute(stmt)

    def check_db_health(self) -> bool:
        """Ping the database to verify connectivity."""
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except OperationalError:
            return False

    def subscribe(self, job_id: str) -> asyncio.Queue[dict[str, Any]]:
        """Subscribe a new WebSocket connection to receive events for job_id."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        if job_id not in self._listeners:
            self._listeners[job_id] = []
        self._listeners[job_id].append(queue)
        return queue

    def unsubscribe(self, job_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Remove a subscriber queue when WebSocket disconnects."""
        if job_id in self._listeners and queue in self._listeners[job_id]:
            self._listeners[job_id].remove(queue)
            if not self._listeners[job_id]:
                del self._listeners[job_id]

    async def _broadcast(self, job_id: str, event: dict[str, Any]) -> None:
        """Push message to all subscriber queues for job_id."""
        listeners = self._listeners.get(job_id, [])
        for queue in listeners:
            await queue.put(event)


# Global singleton JobManager instance
job_manager = JobManager()
