import uuid
from enum import Enum
from datetime import datetime
from typing import Dict, Any, Optional
from dataclasses import dataclass, field

class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class ValuationJob:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str = ""
    contract_id: str = ""
    assumption_set_id: str = ""
    status: JobStatus = JobStatus.PENDING
    progress: float = 0.0
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

# In-memory job store (replace with Redis for production if needed)
_job_store: Dict[str, ValuationJob] = {}
