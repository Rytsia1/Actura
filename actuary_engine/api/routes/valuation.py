from fastapi import APIRouter, HTTPException
from actuary_engine.api.schemas.request import ValuationRequest
from actuary_engine.api.schemas.response import ValuationResponse, ErrorResponse
from actuary_engine.services.valuation_service import ValuationService
from actuary_engine.core.exceptions import ValidationError, DomainError

router = APIRouter(tags=["Valuation"])

@router.post("/valuation", response_model=ValuationResponse, responses={400: {"model": ErrorResponse}})
async def create_valuation(request: ValuationRequest):
    try:
        result = ValuationService.calculate(request.model_dump())
        return ValuationResponse(bel=result["bel"])
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except DomainError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")
