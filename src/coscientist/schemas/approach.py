from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ApproachStatusEnum(str, Enum):
    generated = "generated"
    reviewed = "reviewed"
    scored = "scored"
    experiment_proposed = "experiment_proposed"
    tested = "tested"
    validated = "validated"
    refuted = "refuted"
    superseded = "superseded"


class ApproachMaturityEnum(str, Enum):
    theoretical = "theoretical"
    simulated = "simulated"
    measured = "measured"
    validated = "validated"


class EvidenceTypeEnum(str, Enum):
    direct = "direct"
    inferred = "inferred"


class ReportedMetric(BaseModel):
    metric_name: str
    value: float | str | None = None
    unit: str | None = None
    source_evidence_id: str | None = None
    confidence: float | None = None
    evidence_type: EvidenceTypeEnum = EvidenceTypeEnum.direct


class RiskItem(BaseModel):
    description: str
    failure_mode: str | None = None
    severity: str | None = None
    evidence_id: str | None = None


class EvidenceLink(BaseModel):
    evidence_id: str
    evidence_type: EvidenceTypeEnum
    claim_field: str
    confidence: float | None = None


class ApproachGenerateRequest(BaseModel):
    scout_run_id: str | None = None
    min_evidence_count: int = Field(default=2, ge=1)
    method_families: list[str] | None = None


class ApproachCardCreate(BaseModel):
    name: str
    method_family: str
    domain: str = "personal_sound_zones"
    problem_fit: str | None = None
    mechanism_summary: str | None = None
    key_assumptions: list[str] = Field(default_factory=list)
    reported_metrics: list[ReportedMetric] = Field(default_factory=list)
    hardware_requirements: list[str] = Field(default_factory=list)
    device_relevance: str | None = None
    risks_and_limitations: list[RiskItem] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    suggested_experiments: list[str] = Field(default_factory=list)
    evidence_links: list[EvidenceLink] = Field(default_factory=list)
    maturity: ApproachMaturityEnum = ApproachMaturityEnum.theoretical


class ApproachCardUpdate(BaseModel):
    name: str | None = None
    problem_fit: str | None = None
    mechanism_summary: str | None = None
    key_assumptions: list[str] | None = None
    reported_metrics: list[ReportedMetric] | None = None
    hardware_requirements: list[str] | None = None
    device_relevance: str | None = None
    risks_and_limitations: list[RiskItem] | None = None
    unresolved_questions: list[str] | None = None
    suggested_experiments: list[str] | None = None
    evidence_links: list[EvidenceLink] | None = None
    maturity: ApproachMaturityEnum | None = None


class ApproachStatusUpdate(BaseModel):
    status: ApproachStatusEnum


class ApproachMergeRequest(BaseModel):
    source_approach_id: str
    target_approach_id: str


class ApproachCardResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    workspace_id: str
    name: str
    method_family: str
    domain: str
    problem_fit: str | None
    mechanism_summary: str | None
    key_assumptions: list[str]
    reported_metrics: list[ReportedMetric]
    hardware_requirements: list[str]
    device_relevance: str | None
    risks_and_limitations: list[RiskItem]
    unresolved_questions: list[str]
    suggested_experiments: list[str]
    evidence_links: list[EvidenceLink]
    status: ApproachStatusEnum
    maturity: ApproachMaturityEnum
    generation_run_id: str | None
    merged_into_id: str | None
    created_at: datetime
    updated_at: datetime


class ApproachListResponse(BaseModel):
    items: list[ApproachCardResponse]
    total: int


class ApproachGenerateResponse(BaseModel):
    generation_run_id: str
    goal_id: str
    approaches_created: int
    approaches_skipped_duplicate: int
    approaches: list[ApproachCardResponse]


class DuplicateWarning(BaseModel):
    method_family: str
    existing_approach_id: str
    existing_status: str
