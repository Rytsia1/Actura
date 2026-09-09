from fastapi import APIRouter
from actuary_engine.api.schemas.request import ProjectionRequest
from actuary_engine.services.projection_service import ProjectionService

router = APIRouter(tags=["Projection"])

@router.post("/projection")
async def create_projection(request: ProjectionRequest):
    result = ProjectionService.project(request.model_dump())
    return result
