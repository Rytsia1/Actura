from uuid import UUID
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from actuary_engine.infrastructure.repositories import ValuationRunRepository, ValuationResultRepository, AssumptionSetRepository
from actuary_engine.services.blueprint_service import BlueprintService
from actuary_engine.domain.blueprint.executor import BlueprintExecutor
from actuary_engine.domain.blueprint.validator import BlueprintValidator
from actuary_engine.core.exceptions import InvalidBlueprintError
from actuary_engine.infrastructure.models import ValuationRun

class ValuationService:
    def __init__(self, db: Session):
        self.db = db
        self.run_repo = ValuationRunRepository(db)
        self.result_repo = ValuationResultRepository(db)
        self.assumption_repo = AssumptionSetRepository(db)
        self.blueprint_service = BlueprintService(db)
        self.validator = BlueprintValidator()

    def load_assumptions(self, assumption_set_id: UUID) -> dict:
        if not assumption_set_id:
            return {}
        assumption_set = self.assumption_repo.get(assumption_set_id)
        if not assumption_set:
            return {}
        return assumption_set.assumptions

    def run_valuation(self, project_id: UUID, contract_id: UUID, assumption_set_id: UUID = None) -> ValuationRun:
        """Execute a valuation and persist the results."""
        # Load the blueprint
        blueprint = self.blueprint_service.load_blueprint(contract_id)
        
        # Validate before execution
        self.validator.validate(blueprint) # will raise if invalid
        
        assumptions = self.load_assumptions(assumption_set_id)
        
        # Create the valuation run
        valuation_run = self.run_repo.create(
            project_id=project_id,
            contract_id=contract_id,
            assumption_set_id=assumption_set_id,
            input_snapshot={
                "blueprint": blueprint.model_dump(),
                "assumptions": assumptions,
            }
        )
        
        try:
            # Execute the blueprint
            # Note: in a real implementation we would merge assumptions into the blueprint config
            executor = BlueprintExecutor(blueprint)
            result = executor.run()
            
            # Save the result
            valuation_result = self.result_repo.create(
                valuation_run_id=valuation_run.id,
                bel=result.get("total_bel", 0.0),
                var_95=result.get("var_95"),
                cvar_95=result.get("cvar_95"),
                net_premium=result.get("annual_premium"),
                full_output=result
            )
            
            # Update run status
            run = self.run_repo.update_status(valuation_run.id, "completed")
            if run:
                run.completed_at = datetime.utcnow()
                if run.started_at:
                    run.duration_seconds = (run.completed_at - run.started_at).total_seconds()
                self.db.commit()
            
            return run
            
        except Exception as e:
            self.run_repo.update_status(valuation_run.id, "failed", error=str(e))
            raise
