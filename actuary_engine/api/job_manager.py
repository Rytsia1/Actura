"""
SQLite-backed Job Registry and WebSocket Pub/Sub Manager for Asynchronous Simulations.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
import uuid
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


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

    def __init__(self, db_path: str = "jobs.db") -> None:
        self.db_path = db_path
        self._listeners: dict[str, list[asyncio.Queue[dict[str, Any]]]] = {}
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    status TEXT,
                    progress REAL,
                    completed_paths INTEGER,
                    total_paths INTEGER,
                    partial_metrics TEXT,
                    result TEXT,
                    error TEXT,
                    run_metadata TEXT,
                    original_request TEXT,
                    created_at REAL,
                    updated_at REAL
                )
                """
            )
            # Try to add the columns if they don't exist (primitive migration)
            try:
                conn.execute("ALTER TABLE jobs ADD COLUMN run_metadata TEXT")
            except sqlite3.OperationalError:
                pass  # column exists
            try:
                conn.execute("ALTER TABLE jobs ADD COLUMN original_request TEXT")
            except sqlite3.OperationalError:
                pass  # column exists
            conn.commit()

    def _get_connection(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def _row_to_job(self, row: sqlite3.Row) -> SimulationJob:
        return SimulationJob(
            job_id=row["job_id"],
            status=JobStatus(row["status"]),
            progress=row["progress"],
            completed_paths=row["completed_paths"],
            total_paths=row["total_paths"],
            partial_metrics=json.loads(row["partial_metrics"]) if row["partial_metrics"] else {},
            result=json.loads(row["result"]) if row["result"] else None,
            error=row["error"],
            run_metadata=json.loads(row["run_metadata"]) if row["run_metadata"] else None,
            original_request=json.loads(row["original_request"]) if row["original_request"] else None,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def create_job(self, total_paths: int, run_metadata: Optional[dict[str, Any]] = None, original_request: Optional[dict[str, Any]] = None) -> SimulationJob:
        """Register a new job in QUEUED status."""
        job = SimulationJob(total_paths=total_paths, run_metadata=run_metadata, original_request=original_request)
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    job_id, status, progress, completed_paths, total_paths, 
                    partial_metrics, result, error, run_metadata, original_request, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.job_id,
                    job.status.value,
                    job.progress,
                    job.completed_paths,
                    job.total_paths,
                    json.dumps(job.partial_metrics),
                    json.dumps(job.result) if job.result else None,
                    job.error,
                    json.dumps(job.run_metadata) if job.run_metadata else None,
                    json.dumps(job.original_request) if job.original_request else None,
                    job.created_at,
                    job.updated_at,
                ),
            )
        self._listeners[job.job_id] = []
        return job

    def get_job(self, job_id: str) -> Optional[SimulationJob]:
        """Retrieve job state by ID."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if row:
                return self._row_to_job(row)
        return None

    def set_processing(self, job_id: str) -> None:
        """Mark job as PROCESSING."""
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, updated_at = ? WHERE job_id = ?",
                (JobStatus.PROCESSING.value, time.time(), job_id),
            )

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
        
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE jobs 
                SET status = ?, progress = ?, completed_paths = ?, total_paths = ?, partial_metrics = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (JobStatus.PROCESSING.value, progress, completed_paths, total_paths, pm_json, time.time(), job_id),
            )

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
        with self._get_connection() as conn:
            # Need to get total_paths to set completed_paths
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT total_paths FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if not row:
                return
            total_paths = row["total_paths"]
            
            conn.execute(
                """
                UPDATE jobs 
                SET status = ?, progress = ?, completed_paths = ?, result = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (JobStatus.COMPLETED.value, 100.0, total_paths, json.dumps(result_data), time.time(), job_id),
            )

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
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, error = ?, updated_at = ? WHERE job_id = ?",
                (JobStatus.FAILED.value, error_message, time.time(), job_id),
            )

        event = {
            "type": "ERROR",
            "job_id": job_id,
            "status": JobStatus.FAILED.value,
            "error": error_message,
        }
        await self._broadcast(job_id, event)

    def set_cancelled(self, job_id: str) -> None:
        """Mark job as CANCELLED."""
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, updated_at = ? WHERE job_id = ?",
                (JobStatus.CANCELLED.value, time.time(), job_id),
            )

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
