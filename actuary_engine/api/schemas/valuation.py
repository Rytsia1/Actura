from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Dict, Any
from uuid import UUID
from datetime import datetime

class RunValuationRequest(BaseModel):
    contract_id: UUID
    assumption_set_id: Optional[UUID] = None

class ValuationResultResponse(BaseModel):
    id: UUID
    bel: float
    var_95: Optional[float] = None
    cvar_95: Optional[float] = None
    net_premium: Optional[float] = None
    full_output: Optional[Dict[str, Any]] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class ValuationRunResponse(BaseModel):
    id: UUID
    project_id: UUID
    contract_id: UUID
    assumption_set_id: Optional[UUID] = None
    status: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    created_at: datetime
    result: Optional[ValuationResultResponse] = None

    model_config = ConfigDict(from_attributes=True)
