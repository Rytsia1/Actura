from sqlalchemy import Column, String, DateTime, Float, ForeignKey, JSON, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime, timezone
from actuary_engine.infrastructure.database import Base

def utcnow():
    return datetime.now(timezone.utc)

class Project(Base):
    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(String(500))
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    owner_id = Column(String(100))  # For multi-tenant support (placeholder)
    is_pinned = Column(Boolean, default=False)
    sandbox_state = Column(JSON, nullable=True)

    # Relationships
    contracts = relationship("Contract", back_populates="project", cascade="all, delete-orphan")
    assumption_sets = relationship("AssumptionSet", back_populates="project", cascade="all, delete-orphan")
    valuation_runs = relationship("ValuationRun", back_populates="project", cascade="all, delete-orphan")

class Contract(Base):
    __tablename__ = "contracts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    name = Column(String(255), nullable=False)
    product_type = Column(String(50))  # WholeLife, Term, Annuity
    blueprint_json = Column(JSON, nullable=False)  # The full Blueprint JSON
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Relationships
    project = relationship("Project", back_populates="contracts")
    valuation_runs = relationship("ValuationRun", back_populates="contract", cascade="all, delete-orphan")

class AssumptionSet(Base):
    __tablename__ = "assumption_sets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(String(500))
    assumptions = Column(JSON, nullable=False)  # e.g., {"discount_rate": 0.05, "mortality_table": "soa_ilt.csv"}
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Relationships
    project = relationship("Project", back_populates="assumption_sets")
    valuation_runs = relationship("ValuationRun", back_populates="assumption_set")

class ValuationRun(Base):
    __tablename__ = "valuation_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    contract_id = Column(UUID(as_uuid=True), ForeignKey("contracts.id"), nullable=False)
    assumption_set_id = Column(UUID(as_uuid=True), ForeignKey("assumption_sets.id"), nullable=True) # allow null for simple runs without full assumption set
    
    status = Column(String(50), default="pending")  # pending, running, completed, failed
    started_at = Column(DateTime, default=utcnow)
    completed_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    
    # Input snapshot (for historical reproducibility)
    input_snapshot = Column(JSON, nullable=False)  # Captures all inputs at run time
    
    created_at = Column(DateTime, default=utcnow)

    # Relationships
    project = relationship("Project", back_populates="valuation_runs")
    contract = relationship("Contract", back_populates="valuation_runs")
    assumption_set = relationship("AssumptionSet", back_populates="valuation_runs")
    result = relationship("ValuationResult", back_populates="valuation_run", uselist=False, cascade="all, delete-orphan")

class ValuationResult(Base):
    __tablename__ = "valuation_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    valuation_run_id = Column(UUID(as_uuid=True), ForeignKey("valuation_runs.id"), nullable=False, unique=True)
    
    # Core metrics
    bel = Column(Float, nullable=False)  # Best Estimate Liability
    var_95 = Column(Float, nullable=True)  # Value at Risk (95%)
    cvar_95 = Column(Float, nullable=True)  # Conditional Tail Expectation (95%)
    net_premium = Column(Float, nullable=True)
    
    # Full output (for later analysis or charts)
    full_output = Column(JSON, nullable=True)  # Paths, distributions, detailed breakdowns
    
    created_at = Column(DateTime, default=utcnow)

    # Relationships
    valuation_run = relationship("ValuationRun", back_populates="result")
