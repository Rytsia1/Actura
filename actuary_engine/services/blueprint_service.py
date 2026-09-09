from uuid import UUID
from sqlalchemy.orm import Session
from actuary_engine.infrastructure.repositories import ContractRepository
from actuary_engine.domain.blueprint.models import Blueprint
from actuary_engine.domain.blueprint.validator import BlueprintValidator
from actuary_engine.core.exceptions import InvalidBlueprintError
from actuary_engine.infrastructure.models import Contract

class BlueprintService:
    def __init__(self, db: Session):
        self.repo = ContractRepository(db)
        self.validator = BlueprintValidator()

    def save_blueprint(self, project_id: UUID, name: str, blueprint: Blueprint) -> Contract:
        """Save a blueprint to the database."""
        # Validate before saving
        validation_result = self.validator.validate(blueprint)
        # Note: validator.validate raises BlueprintValidationError on failure, but we could catch it
        # However, we'll let it raise so it maps to InvalidBlueprintError at router
        
        contract = self.repo.create(
            project_id=project_id,
            name=name,
            blueprint_json=blueprint.model_dump()
        )
        return contract

    def load_blueprint(self, contract_id: UUID) -> Blueprint:
        """Load a blueprint from the database."""
        contract = self.repo.get(contract_id)
        if not contract:
            raise ValueError(f"Contract {contract_id} not found")
        return Blueprint(**contract.blueprint_json)

    def update_blueprint(self, contract_id: UUID, blueprint: Blueprint) -> Contract:
        """Update an existing blueprint."""
        # Validate before updating
        self.validator.validate(blueprint)
        
        contract = self.repo.update(contract_id, blueprint_json=blueprint.model_dump())
        return contract
