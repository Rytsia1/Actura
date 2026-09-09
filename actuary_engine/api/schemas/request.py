from pydantic import BaseModel, Field

class ValuationRequest(BaseModel):
    age: int = Field(..., ge=18, le=100)
    product_type: str = Field(..., pattern="^(WholeLife|Term|Annuity)$")
    benefit: float = Field(..., gt=0)
    term: int | None = Field(None, ge=1)  # Optional for Whole Life
    discount_rate: float = Field(0.05, ge=0.0, le=1.0)
    num_paths: int = Field(10000, ge=100, le=1000000)  # For stochastic

class ProjectionRequest(BaseModel):
    age: int = Field(..., ge=18, le=100)
    product_type: str = Field(..., pattern="^(WholeLife|Term|Annuity)$")
    years: int = Field(10, ge=1, le=100)
