from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ValidationDecisionEnum(str, Enum):
    validated = "validated"
    refuted = "refuted"
    inconclusive = "inconclusive"


class ReproductionStatusEnum(str, Enum):
    reproduced = "reproduced"
    partially_reproduced = "partially_reproduced"
    failed = "failed"
    blocked = "blocked"
    superseded = "superseded"


class ExperimentResultSubmission(BaseModel):
    measured_metrics: dict[str, float]
    artifact_paths: dict[str, str] | None = None
    notes: str | None = None
    # Canonical pass-condition metrics the reproduction physically cannot produce.
    # Reconciled to measured=None so they can't drive a refutation (unmeasured != failed).
    unmeasurable_conditions: list[str] = Field(default_factory=list)


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
    reproduction_status: ReproductionStatusEnum
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


# ---------------------------------------------------------------------------
# ResultBundle ingestion + aggregation (CS-EPIC-VALIDATION)
# ---------------------------------------------------------------------------

class BundleValidationStatusEnum(str, Enum):
    passed = "passed"
    failed = "failed"
    blocked = "blocked"
    partial = "partial"
    inconclusive = "inconclusive"


class ValidationAggregateStatusEnum(str, Enum):
    passed = "passed"
    failed = "failed"
    mixed = "mixed"
    inconclusive = "inconclusive"
    partial = "partial"
    blocked = "blocked"


class ResultBundleIngest(BaseModel):
    """Structured ResultBundle summary emitted by the Experimentation System."""

    result_bundle_id: str
    run_request_id: str
    run_id: str | None = None
    attempt_id: str | None = None
    experiment_id: str
    hypothesis_id: str | None = None
    approach_ids: list[str] = Field(default_factory=list)
    execution_batch_id: str | None = None
    validation_status: BundleValidationStatusEnum = BundleValidationStatusEnum.inconclusive
    metrics: dict[str, float] = Field(default_factory=dict)
    artifacts: dict[str, str] = Field(default_factory=dict)
    manifest_uri: str | None = None
    artifact_visibility: str = "internal"
    access_label: str | None = None
    deviations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    provenance: dict = Field(default_factory=dict)
    failure_type: str | None = None
    failure_summary: str | None = None
    retryable: bool = False
    is_partial: bool = False


class ResultBundleResponse(BaseModel):
    id: str
    result_bundle_id: str
    run_request_id: str
    run_id: str | None
    attempt_id: str | None
    experiment_id: str
    goal_id: str
    hypothesis_id: str | None
    approach_ids: list[str]
    execution_batch_id: str | None
    validation_status: BundleValidationStatusEnum
    metrics: dict[str, float]
    artifacts: dict[str, str]
    manifest_uri: str | None
    artifact_visibility: str
    access_label: str | None
    deviations: list[str]
    warnings: list[str]
    provenance: dict
    failure_type: str | None
    failure_summary: str | None
    retryable: bool
    is_partial: bool
    created_at: datetime


class MetricSummary(BaseModel):
    count: int
    min: float
    max: float
    mean: float
    variance: float
    stddev: float


class ValidationAggregationResponse(BaseModel):
    id: str
    experiment_id: str
    goal_id: str
    execution_batch_id: str | None
    aggregate_status: ValidationAggregateStatusEnum
    expected_run_count: int | None
    total_runs: int
    passed_runs: int
    failed_runs: int
    blocked_runs: int
    missing_runs: int
    is_partial: bool
    metric_summaries: dict[str, MetricSummary]
    created_at: datetime
    updated_at: datetime


class ResultBundleIngestResponse(BaseModel):
    """Ingestion ack — reports whether this event created a new bundle (idempotent)."""

    ingested: bool
    duplicate: bool
    bundle: ResultBundleResponse
    aggregation: ValidationAggregationResponse


class ResultBundleListResponse(BaseModel):
    items: list[ResultBundleResponse]
    total: int
