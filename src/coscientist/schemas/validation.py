from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ValidationDecisionEnum(str, Enum):
    validated = "validated"
    refuted = "refuted"


class ExperimentResultSubmission(BaseModel):
    measured_metrics: dict[str, float]
    artifact_paths: dict[str, str] | None = None
    notes: str | None = None


class CriterionResult(BaseModel):
    name: str
    measured: float | None = None
    target: float
    operator: str
    passed: bool
    unit: str


class AgentValidationOutput(BaseModel):
    """Internal schema — parsed from Claude's JSON response. Not serialized to clients."""
    decision: ValidationDecisionEnum
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    criterion_results: list[CriterionResult]
    refinement_suggestions: list[str] = Field(default_factory=list)


class ValidationResultResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    experiment_id: str
    goal_id: str
    approach_id: str
    decision: ValidationDecisionEnum
    confidence: float
    reasoning: str
    criterion_results: list[CriterionResult]
    refinement_suggestions: list[str]
    measured_metrics: dict[str, float]
    artifact_paths: dict[str, str] | None
    model_used: str | None
    created_at: datetime


class ValidationResultListResponse(BaseModel):
    items: list[ValidationResultResponse]
    total: int
