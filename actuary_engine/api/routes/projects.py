from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from actuary_engine.infrastructure.database import get_db
from actuary_engine.services.project_service import ProjectService
from actuary_engine.api.schemas.project import CreateProjectRequest, UpdateProjectRequest, ProjectResponse

router = APIRouter(prefix="/projects", tags=["Projects"])

@router.post("/", response_model=ProjectResponse)
def create_project(request: CreateProjectRequest, db: Session = Depends(get_db)):
    service = ProjectService(db)
    project = service.create_project(request.name, request.description)
    return project

@router.get("/", response_model=list[ProjectResponse])
def list_projects(db: Session = Depends(get_db)):
    service = ProjectService(db)
    return service.list_projects()

@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project_id: UUID, db: Session = Depends(get_db)):
    service = ProjectService(db)
    project = service.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project

@router.put("/{project_id}", response_model=ProjectResponse)
def update_project(project_id: UUID, request: UpdateProjectRequest, db: Session = Depends(get_db)):
    service = ProjectService(db)
    project = service.update_project(project_id, request.name, request.description, request.is_pinned, request.sandbox_state)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project

@router.delete("/{project_id}")
def delete_project(project_id: UUID, db: Session = Depends(get_db)):
    service = ProjectService(db)
    success = service.delete_project(project_id)
    if not success:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"message": "Project deleted successfully"}
