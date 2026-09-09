from fastapi import APIRouter
from actuary_engine.domain.blueprint.models import Blueprint
from actuary_engine.domain.blueprint.validator import BlueprintValidator
from actuary_engine.domain.blueprint.executor import BlueprintExecutor
from actuary_engine.domain.blueprint.exceptions import BlueprintValidationError, BlueprintExecutionError
from actuary_engine.core.exceptions import (
    CycleDetectedError, 
    DisconnectedNodeError, 
    InvalidBlueprintError, 
    ActuraException
)
from actuary_engine.api.schemas.error import ErrorCode

router = APIRouter(tags=["Blueprint"])

@router.post("/execute")
async def execute_blueprint(blueprint: Blueprint):
    """
    Validates and executes a UI-generated Blueprint DAG.
    """
    try:
        BlueprintValidator.validate(blueprint)
    except BlueprintValidationError as e:
        msg = str(e)
        if "Cycle detected" in msg:
            raise CycleDetectedError(details={"reason": msg})
        elif "completely disconnected" in msg:
            raise DisconnectedNodeError(details={"reason": msg})
        else:
            raise InvalidBlueprintError(details={"reason": msg})
    
    try:
        executor = BlueprintExecutor(blueprint)
        result = executor.run()
        return result
    except BlueprintExecutionError as e:
        class ExecutionError(ActuraException):
            error_code = ErrorCode.INTERNAL_ERROR
            default_message = "Execution failed."
        raise ExecutionError(details={"reason": str(e)})
    except Exception as e:
        raise Exception(f"Internal engine error: {str(e)}")
