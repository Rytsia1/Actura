from uuid import UUID
from sqlalchemy.orm import Session
from actuary_engine.infrastructure.repositories import ProjectRepository
from actuary_engine.infrastructure.models import Project

class ProjectService:
    def __init__(self, db: Session):
        self.repo = ProjectRepository(db)

    def create_project(self, name: str, description: str = "") -> Project:
        return self.repo.create(name=name, description=description)

    def get_project(self, project_id: UUID) -> Project:
        return self.repo.get(project_id)

    def list_projects(self) -> list[Project]:
        return self.repo.list()

    def update_project(self, project_id: UUID, name: str = None, description: str = None, is_pinned: bool = None, sandbox_state: dict = None) -> Project:
        return self.repo.update(project_id, name=name, description=description, is_pinned=is_pinned, sandbox_state=sandbox_state)

    def delete_project(self, project_id: UUID) -> bool:
        return self.repo.delete(project_id)
