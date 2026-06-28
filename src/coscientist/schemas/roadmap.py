from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class RoadmapLaneEnum(str, Enum):
    conservative = "conservative"
    exploratory = "exploratory"
    device_prototype = "device_prototype"


class RoadmapStatusEnum(str, Enum):
    open = "open"
    completed = "completed"
    superseded = "superseded"


# --- Agent internal schema ---

class AgentRoadmapItem(BaseModel):
    title: str
    description: str
    lane: RoadmapLaneEnum
    priority_score: float = Field(ge=0.0, le=1.0)
    rationale: str
    estimated_cost: str = "medium"
    estimated_information_gain: str = "medium"
    source_approach_ids: list[str] = Field(default_factory=list)
    source_experiment_id: str | None = None
    source_device_id: str | None = None


# --- Request schemas ---

class RoadmapGenerateRequest(BaseModel):
    pass


class RoadmapTransitionRequest(BaseModel):
    status: RoadmapStatusEnum


# --- Response schemas ---

class ResearchRoadmapItemResponse(BaseModel):
    id: str
    workspace_id: str
    title: str
    description: str
    lane: RoadmapLaneEnum
    status: RoadmapStatusEnum
    priority_score: float
    priority_rank: int
    rationale: str
    estimated_cost: str
    estimated_information_gain: str
    source_approach_ids: list[str]
    source_experiment_id: str | None
    source_device_id: str | None
    generation_run_id: str
    model_used: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ResearchRoadmapListResponse(BaseModel):
    items: list[ResearchRoadmapItemResponse]
    total: int
    generation_run_id: str | None = None


class ApproachEvidenceGap(BaseModel):
    approach_id: str
    approach_name: str
    method_family: str
    status: str
    missing_claim_fields: list[str]
    weak_dimensions: list[str]
    unscored: bool


class EvidenceGapResponse(BaseModel):
    goal_id: str
    gaps: list[ApproachEvidenceGap]
    total: int
