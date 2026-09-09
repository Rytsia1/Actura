from fastapi import Request
from fastapi.responses import JSONResponse
from actuary_engine.core.exceptions import ActuraException
from actuary_engine.api.schemas.error import ErrorResponse, ErrorCode
from datetime import datetime, timezone

async def actura_exception_handler(request: Request, exc: ActuraException):
    return JSONResponse(
        status_code=400 if "INVALID" in exc.error_code or "DETECTED" in exc.error_code or "DISCONNECTED" in exc.error_code else 500,
        content=ErrorResponse(
            error=exc.error_code,
            message=exc.message,
            details=exc.details,
            timestamp=datetime.now(timezone.utc).isoformat(),
            path=request.url.path
        ).model_dump()
    )

async def generic_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error=ErrorCode.INTERNAL_ERROR,
            message="An unexpected error occurred. Please try again later.",
            details={"trace_id": request.headers.get("X-Request-ID", "unknown"), "internal": str(exc)},
            timestamp=datetime.now(timezone.utc).isoformat(),
            path=request.url.path
        ).model_dump()
    )
