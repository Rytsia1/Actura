from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
from actuary_engine.infrastructure.models import Project, Contract, AssumptionSet, ValuationRun, ValuationResult
import uuid

class ProjectRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, name: str, description: str = "") -> Project:
        project = Project(name=name, description=description)
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)
        return project

    def get(self, project_id: uuid.UUID) -> Optional[Project]:
        return self.db.query(Project).filter(Project.id == project_id).first()

    def list(self) -> List[Project]:
        # Order by pinned first, then by updated date
        return self.db.query(Project).order_by(Project.is_pinned.desc(), Project.updated_at.desc()).all()

    def update(self, project_id: uuid.UUID, name: Optional[str] = None, description: Optional[str] = None, is_pinned: Optional[bool] = None, sandbox_state: Optional[Dict[str, Any]] = None) -> Optional[Project]:
        project = self.get(project_id)
        if project:
            if name is not None:
                project.name = name
            if description is not None:
                project.description = description
            if is_pinned is not None:
                project.is_pinned = is_pinned
            if sandbox_state is not None:
                project.sandbox_state = sandbox_state
            self.db.commit()
            self.db.refresh(project)
        return project

    def delete(self, project_id: uuid.UUID) -> bool:
        project = self.get(project_id)
        if project:
            self.db.delete(project)
            self.db.commit()
            return True
        return False

class ContractRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, project_id: uuid.UUID, name: str, blueprint_json: Dict[str, Any], product_type: str = "Unknown") -> Contract:
        contract = Contract(project_id=project_id, name=name, blueprint_json=blueprint_json, product_type=product_type)
        self.db.add(contract)
        self.db.commit()
        self.db.refresh(contract)
        return contract

    def get(self, contract_id: uuid.UUID) -> Optional[Contract]:
        return self.db.query(Contract).filter(Contract.id == contract_id).first()

    def list_by_project(self, project_id: uuid.UUID) -> List[Contract]:
        return self.db.query(Contract).filter(Contract.project_id == project_id).order_by(Contract.updated_at.desc()).all()

    def update(self, contract_id: uuid.UUID, name: Optional[str] = None, blueprint_json: Optional[Dict[str, Any]] = None) -> Optional[Contract]:
        contract = self.get(contract_id)
        if contract:
            if name is not None:
                contract.name = name
            if blueprint_json is not None:
                contract.blueprint_json = blueprint_json
            self.db.commit()
            self.db.refresh(contract)
        return contract

    def delete(self, contract_id: uuid.UUID) -> bool:
        contract = self.get(contract_id)
        if contract:
            self.db.delete(contract)
            self.db.commit()
            return True
        return False

class AssumptionSetRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, project_id: uuid.UUID, name: str, assumptions: Dict[str, Any], description: str = "") -> AssumptionSet:
        assumption_set = AssumptionSet(project_id=project_id, name=name, assumptions=assumptions, description=description)
        self.db.add(assumption_set)
        self.db.commit()
        self.db.refresh(assumption_set)
        return assumption_set

    def get(self, assumption_id: uuid.UUID) -> Optional[AssumptionSet]:
        return self.db.query(AssumptionSet).filter(AssumptionSet.id == assumption_id).first()

class ValuationRunRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, project_id: uuid.UUID, contract_id: uuid.UUID, input_snapshot: Dict[str, Any], assumption_set_id: Optional[uuid.UUID] = None) -> ValuationRun:
        run = ValuationRun(
            project_id=project_id,
            contract_id=contract_id,
            assumption_set_id=assumption_set_id,
            input_snapshot=input_snapshot,
            status="running"
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def update_status(self, run_id: uuid.UUID, status: str, error: Optional[str] = None) -> Optional[ValuationRun]:
        run = self.db.query(ValuationRun).filter(ValuationRun.id == run_id).first()
        if run:
            run.status = status
            if error:
                # Store error in snapshot or create error column (simplest is modifying snapshot for now if no error column)
                run.input_snapshot = {**run.input_snapshot, "error": error}
            self.db.commit()
            self.db.refresh(run)
        return run
    
    def list_by_project(self, project_id: uuid.UUID) -> List[ValuationRun]:
        return self.db.query(ValuationRun).filter(ValuationRun.project_id == project_id).order_by(ValuationRun.created_at.desc()).all()
    
    def get(self, run_id: uuid.UUID) -> Optional[ValuationRun]:
        return self.db.query(ValuationRun).filter(ValuationRun.id == run_id).first()

class ValuationResultRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, valuation_run_id: uuid.UUID, bel: float, var_95: Optional[float] = None, cvar_95: Optional[float] = None, net_premium: Optional[float] = None, full_output: Optional[Dict[str, Any]] = None) -> ValuationResult:
        result = ValuationResult(
            valuation_run_id=valuation_run_id,
            bel=bel,
            var_95=var_95,
            cvar_95=cvar_95,
            net_premium=net_premium,
            full_output=full_output
        )
        self.db.add(result)
        self.db.commit()
        self.db.refresh(result)
        return result
    
    def get_by_run(self, run_id: uuid.UUID) -> Optional[ValuationResult]:
        return self.db.query(ValuationResult).filter(ValuationResult.valuation_run_id == run_id).first()
