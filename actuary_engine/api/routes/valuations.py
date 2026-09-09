from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from actuary_engine.infrastructure.database import get_db
from actuary_engine.services.valuation_service import ValuationService
from actuary_engine.api.schemas.valuation import RunValuationRequest, ValuationRunResponse

router = APIRouter(prefix="/projects/{project_id}/valuations", tags=["Valuations"])

@router.post("/", response_model=ValuationRunResponse)
def run_valuation(project_id: UUID, request: RunValuationRequest, db: Session = Depends(get_db)):
    service = ValuationService(db)
    run = service.run_valuation(
        project_id=project_id,
        contract_id=request.contract_id,
        assumption_set_id=request.assumption_set_id
    )
    return run

@router.get("/", response_model=list[ValuationRunResponse])
def list_valuation_history(project_id: UUID, db: Session = Depends(get_db)):
    from actuary_engine.infrastructure.repositories import ValuationRunRepository
    repo = ValuationRunRepository(db)
    return repo.list_by_project(project_id)

@router.get("/{run_id}", response_model=ValuationRunResponse)
def get_valuation_result(project_id: UUID, run_id: UUID, db: Session = Depends(get_db)):
    from actuary_engine.infrastructure.repositories import ValuationRunRepository
    repo = ValuationRunRepository(db)
    run = repo.get(run_id)
    if not run or run.project_id != project_id:
        raise HTTPException(status_code=404, detail="Valuation run not found")
    return run
