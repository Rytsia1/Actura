from pydantic import BaseModel, ConfigDict
from typing import Optional, Dict, Any
from uuid import UUID

class CreateContractRequest(BaseModel):
    name: str
    product_type: str
    blueprint_json: Optional[Dict[str, Any]] = None

class CreateAssumptionSetRequest(BaseModel):
    name: str
    assumptions: Dict[str, Any]

class WorkflowStateResponse(BaseModel):
    project_id: Optional[UUID] = None
    contract_id: Optional[UUID] = None
    assumption_set_id: Optional[UUID] = None
    valuation_run_id: Optional[UUID] = None
    job_id: Optional[str] = None
    progress: Optional[float] = None
    step: str
    blueprint: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)
