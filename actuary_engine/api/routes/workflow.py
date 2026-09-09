from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from actuary_engine.api.schemas.project import CreateProjectRequest
from actuary_engine.api.schemas.workflow import (
    CreateAssumptionSetRequest,
    CreateContractRequest,
    WorkflowStateResponse,
)
from actuary_engine.infrastructure.database import get_db
from actuary_engine.infrastructure.repositories import (
    AssumptionSetRepository,
    ContractRepository,
)
from actuary_engine.services.project_service import ProjectService
from actuary_engine.services.workflow_orchestrator import ValuationWorkflow

router = APIRouter(prefix="/workflow", tags=["Valuation Workflow"])


@router.post("/start", response_model=WorkflowStateResponse)
def start_workflow(request: CreateProjectRequest, db: Session = Depends(get_db)):
    """Initialize a new project and workflow."""
    service = ProjectService(db)
    project = service.create_project(request.name, request.description)

    workflow = ValuationWorkflow(db, project.id)
    state = workflow.transition_to_next_step()
    return {"project_id": project.id, **state}


@router.get("/{project_id}/state", response_model=WorkflowStateResponse)
def get_workflow_state(project_id: UUID, db: Session = Depends(get_db)):
    """Get the current workflow step and required data for the UI."""
    workflow = ValuationWorkflow(db, project_id)
    try:
        state = workflow.transition_to_next_step()
        return {"project_id": project_id, **state}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{project_id}/contract", response_model=WorkflowStateResponse)
def add_contract(project_id: UUID, request: CreateContractRequest, db: Session = Depends(get_db)):
    """Create a contract and advance the workflow."""
    repo = ContractRepository(db)
    contract = repo.create(
        project_id=project_id,
        name=request.name,
        product_type=request.product_type,
        blueprint_json=request.blueprint_json or {},
    )
    workflow = ValuationWorkflow(db, project_id)
    state = workflow.transition_to_next_step()
    return {"project_id": project_id, "contract_id": contract.id, **state}


@router.post("/{project_id}/assumptions", response_model=WorkflowStateResponse)
def set_assumptions(project_id: UUID, request: CreateAssumptionSetRequest, db: Session = Depends(get_db)):
    """Configure assumptions and advance the workflow."""
    repo = AssumptionSetRepository(db)
    assumptions = repo.create(
        project_id=project_id,
        name=request.name,
        assumptions=request.assumptions,
    )
    workflow = ValuationWorkflow(db, project_id)
    state = workflow.transition_to_next_step()
    return {"project_id": project_id, "assumption_set_id": assumptions.id, **state}


@router.post("/{project_id}/run", response_model=WorkflowStateResponse)
def trigger_valuation(project_id: UUID, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Execute the valuation asynchronously and return a Job ID."""
    workflow = ValuationWorkflow(db, project_id, background_tasks)
    state = workflow.trigger_run()
    return {"project_id": project_id, **state}


@router.get("/status/{job_id}", response_model=WorkflowStateResponse)
def get_job_status(job_id: str):
    """Poll the status of an asynchronous valuation job."""
    from actuary_engine.core.jobs import JobStatus
    from actuary_engine.services.async_valuation_service import AsyncValuationService

    job = AsyncValuationService.get_job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status == JobStatus.COMPLETED:
        return {
            "project_id": UUID(job.project_id),
            "step": "results",
            "job_id": job.id,
            "progress": job.progress,
            "result": job.result,
        }
    elif job.status == JobStatus.FAILED:
        raise HTTPException(status_code=500, detail=job.error)
    else:
        return {
            "project_id": UUID(job.project_id),
            "step": "running",
            "job_id": job.id,
            "progress": job.progress,
        }
