from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class CriticVerdictEnum(str, Enum):
    advance = "advance"
    revise = "revise"
    refute = "refute"


class ApproachCritiqueRequest(BaseModel):
    apply: bool = False
    method_families: list[str] | None = None


class AgentCritiqueOutput(BaseModel):
    """Schema the critic agent must return for one approach card."""

    verdict: CriticVerdictEnum
    summary: str
    grounding_issues: list[str] = Field(default_factory=list)
    device_fit_issues: list[str] = Field(default_factory=list)
    maturity_issues: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    cited_evidence_ids: list[str] = Field(default_factory=list)
    confidence: float | None = None


class ApproachCritiqueResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    workspace_id: str
    approach_id: str
    approach_name: str
    method_family: str
    critique_run_id: str
    verdict: CriticVerdictEnum
    summary: str
    grounding_issues: list[str]
    device_fit_issues: list[str]
    maturity_issues: list[str]
    strengths: list[str]
    cited_evidence_ids: list[str]
    recommended_status: str
    applied: bool
    confidence: float | None
    model_used: str
    created_at: datetime


class CritiqueRunResponse(BaseModel):
    critique_run_id: str
    goal_id: str
    critiqued_count: int
    advance_count: int
    revise_count: int
    refute_count: int
    applied_count: int
    critiques: list[ApproachCritiqueResponse] = Field(default_factory=list)
