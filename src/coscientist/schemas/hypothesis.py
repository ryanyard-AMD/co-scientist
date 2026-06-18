from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class HypothesisStatusEnum(str, Enum):
    generated = "generated"
    reviewed = "reviewed"
    experiment_proposed = "experiment_proposed"
    superseded = "superseded"


class HypothesisTypeEnum(str, Enum):
    conservative = "conservative"
    exploratory = "exploratory"


class CompatibilityNote(BaseModel):
    approach_a_id: str
    approach_b_id: str
    compatible: bool
    shared_hardware: list[str] = Field(default_factory=list)
    conflicting_assumptions: list[str] = Field(default_factory=list)
    complementary_dimensions: list[str] = Field(default_factory=list)
    note: str = ""


class HypothesisGenerateRequest(BaseModel):
    min_approaches: int = Field(default=2, ge=2)
    include_exploratory: bool = True
    max_hypotheses: int = Field(default=20, ge=1, le=100)


class HypothesisCardCreate(BaseModel):
    name: str
    text: str
    rationale: str
    hypothesis_type: HypothesisTypeEnum = HypothesisTypeEnum.conservative
    approach_ids: list[str] = Field(min_length=2)
    assumptions: list[str] = Field(default_factory=list)
    expected_benefits: list[str] = Field(default_factory=list)
    failure_modes: list[str] = Field(default_factory=list)
    required_experiments: list[str] = Field(default_factory=list)
    compatibility_notes: list[CompatibilityNote] = Field(default_factory=list)
    has_conflicts: bool = False


class HypothesisCardUpdate(BaseModel):
    name: str | None = None
    text: str | None = None
    rationale: str | None = None
    assumptions: list[str] | None = None
    expected_benefits: list[str] | None = None
    failure_modes: list[str] | None = None
    required_experiments: list[str] | None = None


class HypothesisStatusUpdate(BaseModel):
    status: HypothesisStatusEnum


class HypothesisCardResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    workspace_id: str
    name: str
    text: str
    rationale: str
    hypothesis_type: HypothesisTypeEnum
    approach_ids: list[str]
    assumptions: list[str]
    expected_benefits: list[str]
    failure_modes: list[str]
    required_experiments: list[str]
    compatibility_notes: list[CompatibilityNote]
    has_conflicts: bool
    status: HypothesisStatusEnum
    generation_run_id: str | None
    created_at: datetime
    updated_at: datetime


class HypothesisListResponse(BaseModel):
    items: list[HypothesisCardResponse]
    total: int


class HypothesisGenerateResponse(BaseModel):
    generation_run_id: str
    goal_id: str
    hypotheses_created: int
    hypotheses_skipped_duplicate: int
    conservative_count: int
    exploratory_count: int
    hypotheses: list[HypothesisCardResponse]
