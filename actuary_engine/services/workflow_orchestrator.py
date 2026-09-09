from enum import Enum
from uuid import UUID
from sqlalchemy.orm import Session
from actuary_engine.infrastructure.repositories import (
    ProjectRepository,
    ContractRepository,
    AssumptionSetRepository,
    ValuationRunRepository,
)
from actuary_engine.services.blueprint_service import BlueprintService
from actuary_engine.services.valuation_service import ValuationService
from actuary_engine.domain.blueprint.models import Blueprint
from actuary_engine.core.exceptions import InvalidBlueprintError, WorkflowStateError

class WorkflowStep(str, Enum):
    PROJECT = "project"
    CONTRACT = "contract"
    BLUEPRINT = "blueprint"
    ASSUMPTIONS = "assumptions"
    VALIDATION = "validation"
    RUNNING = "running"
    RESULTS = "results"

class ValuationWorkflow:
    """
    Orchestrates the entire valuation lifecycle.
    Tracks which step the user is currently on and ensures prerequisites are met.
    """
    def __init__(self, db: Session, project_id: UUID, background_tasks=None):
        self.db = db
        self.project_id = project_id
        self.background_tasks = background_tasks
        self.project_repo = ProjectRepository(db)
        self.contract_repo = ContractRepository(db)
        self.assumption_repo = AssumptionSetRepository(db)
        self.run_repo = ValuationRunRepository(db)
        self.blueprint_service = BlueprintService(db)
        self.valuation_service = ValuationService(db)
        self._current_step = WorkflowStep.PROJECT

    def get_current_step(self) -> WorkflowStep:
        """Determine the current step based on existing data."""
        project = self.project_repo.get(self.project_id)
        if not project:
            return WorkflowStep.PROJECT

        contracts = self.contract_repo.list_by_project(self.project_id)
        if not contracts:
            return WorkflowStep.CONTRACT

        # If there's a contract but no valid blueprint, assume blueprint step
        latest_contract = contracts[0]
        if not latest_contract.blueprint_json or not latest_contract.blueprint_json.get("nodes"):
            return WorkflowStep.BLUEPRINT

        # Check if assumptions exist
        from actuary_engine.infrastructure.models import AssumptionSet
        assumptions = (
            self.db.query(AssumptionSet)
            .filter(AssumptionSet.project_id == self.project_id)
            .order_by(AssumptionSet.created_at.desc())
            .all()
        )
        if not assumptions:
            return WorkflowStep.ASSUMPTIONS

        # Check if valuation has been run
        runs = self.run_repo.list_by_project(self.project_id)
        if not runs or runs[0].status != "completed":
            return WorkflowStep.RUNNING

        return WorkflowStep.RESULTS

    def transition_to_next_step(self) -> dict:
        """
        Validates the current state and moves to the next step.
        Returns the updated state and any required data for the UI.
        """
        current = self.get_current_step()

        if current == WorkflowStep.PROJECT:
            return {"step": WorkflowStep.PROJECT}

        elif current == WorkflowStep.CONTRACT:
            return {"step": WorkflowStep.CONTRACT, "project_id": self.project_id}

        elif current == WorkflowStep.BLUEPRINT:
            contracts = self.contract_repo.list_by_project(self.project_id)
            return {"step": WorkflowStep.BLUEPRINT, "contract_id": contracts[0].id}

        elif current == WorkflowStep.ASSUMPTIONS:
            contracts = self.contract_repo.list_by_project(self.project_id)
            return {"step": WorkflowStep.ASSUMPTIONS, "blueprint": contracts[0].blueprint_json}

        elif current == WorkflowStep.RUNNING:
            from actuary_engine.infrastructure.models import AssumptionSet
            assumptions = (
                self.db.query(AssumptionSet)
                .filter(AssumptionSet.project_id == self.project_id)
                .order_by(AssumptionSet.created_at.desc())
                .all()
            )
            return {"step": WorkflowStep.RUNNING, "assumption_set_id": assumptions[0].id if assumptions else ""}

        elif current == WorkflowStep.RESULTS:
            runs = self.run_repo.list_by_project(self.project_id)
            if runs and runs[0].result:
                return {
                    "step": WorkflowStep.RESULTS,
                    "result": {
                        "bel": runs[0].result.bel,
                        "var_95": runs[0].result.var_95,
                        "cvar_95": runs[0].result.cvar_95,
                        "full_output": runs[0].result.full_output,
                    },
                }
            return {"step": WorkflowStep.RUNNING}

        return {"step": current}

    def trigger_run(self) -> dict:
        """Specific method to trigger the valuation run asynchronously."""
        current = self.get_current_step()
        if current not in (WorkflowStep.RUNNING, WorkflowStep.RESULTS):
            raise WorkflowStateError("Cannot run valuation from current step")

        contracts = self.contract_repo.list_by_project(self.project_id)
        from actuary_engine.infrastructure.models import AssumptionSet
        assumptions = (
            self.db.query(AssumptionSet)
            .filter(AssumptionSet.project_id == self.project_id)
            .order_by(AssumptionSet.created_at.desc())
            .all()
        )

        from actuary_engine.services.async_valuation_service import AsyncValuationService
        job_id = AsyncValuationService.submit_job(
            project_id=str(self.project_id),
            contract_id=str(contracts[0].id),
            assumption_set_id=str(assumptions[0].id) if assumptions else "",
            background_tasks=self.background_tasks,
        )
        return {"step": WorkflowStep.RUNNING, "job_id": job_id}
