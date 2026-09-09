from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from actuary_engine.infrastructure.database import get_db
from actuary_engine.services.blueprint_service import BlueprintService
from actuary_engine.api.schemas.project import SaveBlueprintRequest, ContractResponse
from actuary_engine.domain.blueprint.models import Blueprint

router = APIRouter(prefix="/projects/{project_id}/blueprints", tags=["Blueprints"])

@router.post("/", response_model=ContractResponse)
def save_blueprint(project_id: UUID, request: SaveBlueprintRequest, db: Session = Depends(get_db)):
    service = BlueprintService(db)
    blueprint = Blueprint(**request.blueprint_json)
    contract = service.save_blueprint(project_id, request.name, blueprint)
    return contract

@router.get("/", response_model=list[ContractResponse])
def list_blueprints(project_id: UUID, db: Session = Depends(get_db)):
    from actuary_engine.infrastructure.repositories import ContractRepository
    repo = ContractRepository(db)
    return repo.list_by_project(project_id)

@router.get("/{contract_id}")
def load_blueprint(project_id: UUID, contract_id: UUID, db: Session = Depends(get_db)):
    service = BlueprintService(db)
    try:
        blueprint = service.load_blueprint(contract_id)
        return blueprint.model_dump()
    except ValueError:
        raise HTTPException(status_code=404, detail="Contract not found")

@router.put("/{contract_id}", response_model=ContractResponse)
def update_blueprint(project_id: UUID, contract_id: UUID, request: SaveBlueprintRequest, db: Session = Depends(get_db)):
    service = BlueprintService(db)
    blueprint = Blueprint(**request.blueprint_json)
    contract = service.update_blueprint(contract_id, blueprint)
    return contract
