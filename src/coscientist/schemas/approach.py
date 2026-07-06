from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ApproachStatusEnum(str, Enum):
    generated = "generated"
    reviewed = "reviewed"
    scored = "scored"
    experiment_proposed = "experiment_proposed"
    submitted = "submitted"
    tested = "tested"
    validated = "validated"
    refuted = "refuted"
    inconclusive = "inconclusive"
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


class NegativeEvidence(BaseModel):
    """A failed or inconclusive ResultBundle surfaced as useful evidence
    (CS-APPROACH-011): what failed, why, and what to do next."""

    result_bundle_id: str
    run_request_id: str
    validation_status: str
    failure_type: str | None = None
    failure_summary: str | None = None
    deviations: list[str] = Field(default_factory=list)
    retryable: bool = False


class ValidationSummary(BaseModel):
    aggregate_status: str
    total_runs: int
    passed_runs: int
    failed_runs: int
    blocked_runs: int
    missing_runs: int
    is_partial: bool
    metric_summaries: dict = Field(default_factory=dict)


class ExperimentEvidenceBlock(BaseModel):
    experiment_id: str
    experiment_name: str
    status: str
    execution_status: str
    execution_batch_id: str | None = None
    run_request_ids: list[str] = Field(default_factory=list)
    result_bundle_ids: list[str] = Field(default_factory=list)
    validation: ValidationSummary | None = None
    negative_evidence: list[NegativeEvidence] = Field(default_factory=list)


class ApproachExecutionEvidenceResponse(BaseModel):
    """Links an approach to its downstream execution evidence
    (CS-APPROACH-008/009): experiments, batches, run requests, result
    bundles, and validation outcomes, grouped by evidence provenance."""

    approach_id: str
    approach_name: str
    status: ApproachStatusEnum
    literature_evidence_count: int
    evidence_groups: dict[str, int]
    experiments: list[ExperimentEvidenceBlock] = Field(default_factory=list)
    suggested_followups: list[str] = Field(default_factory=list)
