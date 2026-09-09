class DomainError(Exception):
    """Base exception for domain-level errors."""
    pass

class ValidationError(Exception):
    """Exception raised for validation errors in the business logic."""
    pass

from typing import Optional, Dict, Any
from actuary_engine.api.schemas.error import ErrorCode

class ActuraException(Exception):
    """Base exception for all Actura errors."""
    error_code: ErrorCode
    default_message: str
    
    def __init__(self, message: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        self.message = message or self.default_message
        self.details = details
        super().__init__(self.message)

class InvalidBlueprintError(ActuraException):
    error_code = ErrorCode.INVALID_BLUEPRINT
    default_message = "The blueprint contains invalid configuration."

class WorkflowStateError(ActuraException):
    error_code = ErrorCode.INVALID_WORKFLOW_STATE
    default_message = "Invalid workflow state transition."

class CycleDetectedError(ActuraException):
    error_code = ErrorCode.CYCLE_DETECTED
    default_message = "The blueprint contains a cycle and cannot be executed."

class DisconnectedNodeError(ActuraException):
    error_code = ErrorCode.DISCONNECTED_NODE
    default_message = "The blueprint has disconnected nodes."

class MortalityTableMissingError(ActuraException):
    error_code = ErrorCode.MORTALITY_TABLE_MISSING
    default_message = "Mortality table not found. Please check the file path."
