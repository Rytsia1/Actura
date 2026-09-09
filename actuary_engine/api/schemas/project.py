from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Dict, Any
from uuid import UUID
from datetime import datetime

class CreateProjectRequest(BaseModel):
    name: str
    description: Optional[str] = ""

class UpdateProjectRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_pinned: Optional[bool] = None
    sandbox_state: Optional[Dict[str, Any]] = None

class ProjectResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    is_pinned: bool = False
    sandbox_state: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class SaveBlueprintRequest(BaseModel):
    name: str
    blueprint_json: Dict[str, Any]
    product_type: Optional[str] = "Unknown"

class ContractResponse(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    product_type: str
    blueprint_json: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
