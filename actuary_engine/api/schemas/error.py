from pydantic import BaseModel
from typing import Optional, Dict, Any
from enum import Enum

class ErrorCode(str, Enum):
    # Validation Errors
    INVALID_BLUEPRINT = "INVALID_BLUEPRINT"
    MISSING_INPUT = "MISSING_INPUT"
    INVALID_CONFIG = "INVALID_CONFIG"
    CYCLE_DETECTED = "CYCLE_DETECTED"
    DISCONNECTED_NODE = "DISCONNECTED_NODE"
    
    # Calculation Errors
    MORTALITY_TABLE_MISSING = "MORTALITY_TABLE_MISSING"
    STOCHASTIC_FAILED = "STOCHASTIC_FAILED"
    DISCOUNT_ERROR = "DISCOUNT_ERROR"
    
    # Server Errors
    INTERNAL_ERROR = "INTERNAL_ERROR"
    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    
    # Not Found
    NOT_FOUND = "NOT_FOUND"
    
    # Workflow
    INVALID_WORKFLOW_STATE = "INVALID_WORKFLOW_STATE"

class ErrorResponse(BaseModel):
    error: ErrorCode
    message: str
    details: Optional[Dict[str, Any]] = None
    timestamp: str  # ISO 8601
    path: Optional[str] = None
