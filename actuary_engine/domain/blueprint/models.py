import uuid
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

class NodeType(str, Enum):
    # Standard Flow node types
    POLICY_INPUT = "policyInput"
    INFLOW = "inflow"
    OUTFLOW = "outflow"
    CONTINGENCY = "contingency"
    ACCUMULATOR = "accumulator"
    VALUATION_SINK = "valuationSink"

    # Domain / visual blueprint node types
    INPUT = "input"
    OUTPUT = "output"
    MORTALITY = "mortality"
    SURVIVAL = "survival"
    BENEFIT = "benefit"
    DISCOUNT = "discount"
    CASHFLOW = "cashflow"
    PREMIUM = "premium"
    EXPENSE = "expense"


class Node(BaseModel):
    id: str = Field(..., description="Unique UUID or slug")
    type: NodeType
    config: Dict[str, Any] = Field(default_factory=dict, alias="data", description="Configuration parameters for the node")
    position: Optional[Dict[str, float]] = Field(default=None, description="Visual position for UI, ignored by engine")

    model_config = ConfigDict(populate_by_name=True)


class Edge(BaseModel):
    id: str
    source: str = Field(..., description="Source Node ID")
    target: str = Field(..., description="Target Node ID")
    source_handle: Optional[str] = Field(None, description="Output port name, e.g., 'qx'")
    target_handle: Optional[str] = Field(None, description="Input port name, e.g., 'mortality'")


class Blueprint(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "Untitled Projection"
    nodes: List[Node]
    edges: List[Edge]
