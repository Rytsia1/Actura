from pydantic import BaseModel

class ValuationResponse(BaseModel):
    bel: float
    message: str = "Success"

class ErrorResponse(BaseModel):
    detail: str
