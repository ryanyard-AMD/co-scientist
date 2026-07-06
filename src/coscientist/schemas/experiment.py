from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ExperimentStatusEnum(str, Enum):
    """Card lifecycle / approval state — distinct from execution state.

    `reviewed`, `running`, `completed`, `failed` are retained for backward
    compatibility with the legacy synchronous runner path; the canonical
    execution lifecycle now lives in ExecutionStatusEnum.
    """

    generated = "generated"
    needs_review = "needs_review"
    reviewed = "reviewed"
    approved = "approved"
    rejected = "rejected"
    duplicated = "duplicated"
    running = "running"
    completed = "completed"
    failed = "failed"
    superseded = "superseded"
    archived = "archived"


class ExecutionStatusEnum(str, Enum):
    """Where the experiment stands in the external Experimentation System."""

    not_submitted = "not_submitted"
    submitted = "submitted"
    queued = "queued"
    running = "running"
    partially_completed = "partially_completed"
    completed = "completed"
    failed = "failed"
    blocked = "blocked"
    mixed_outcome = "mixed_outcome"


class HandoffStatusEnum(str, Enum):
    """State of the submission attempt to the Experimentation System."""

    not_submitted = "not_submitted"
    submitting = "submitting"
    submitted = "submitted"
    failed = "failed"
    canceled = "canceled"


class SubmissionModeEnum(str, Enum):
    single_run = "single_run"
    run_request_batch = "run_request_batch"
    sweep_batch = "sweep_batch"


class ExperimentTypeEnum(str, Enum):
    simulation = "simulation"
    measurement = "measurement"
    hybrid = "hybrid"


class CostEstimateEnum(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class ExperimentRubricDimensionEnum(str, Enum):
    hypothesis_clarity = "hypothesis_clarity"
    device_relevance = "device_relevance"
    baseline_quality = "baseline_quality"
    metric_quality = "metric_quality"
    reproducibility = "reproducibility"
    information_gain = "information_gain"
    cost_time = "cost_time"
    failure_informativeness = "failure_informativeness"
    robustness_coverage = "robustness_coverage"
    artifact_quality = "artifact_quality"


class ValidationCriteria(BaseModel):
    pass_conditions: dict[str, float] = Field(default_factory=dict)
    comparison: dict[str, Any] = Field(default_factory=dict)


class RuntimeSpec(BaseModel):
    preferred: str = "python_numerics_or_treble"
    alternatives: list[str] = Field(default_factory=list)


class ExecutionHandoff(BaseModel):
    """How an approved card should be handed to the Experimentation System."""

    submission_mode: SubmissionModeEnum = SubmissionModeEnum.single_run
    handoff_status: HandoffStatusEnum = HandoffStatusEnum.not_submitted
    experiment_control_plane: str | None = None
    required_capabilities: list[str] = Field(default_factory=list)
    runner_pool_preference: str | None = None
    run_request_ids: list[str] = Field(default_factory=list)
    execution_batch_id: str | None = None
    result_bundle_ids: list[str] = Field(default_factory=list)
    batch_expansion: dict[str, Any] = Field(default_factory=dict)
    expected_run_count: int | None = None


class ExperimentGenerateRequest(BaseModel):
    approach_ids: list[str] | None = None
    hypothesis_id: str | None = None
    include_measurement: bool = False
    max_experiments: int = Field(default=10, ge=1, le=50)


class ExperimentCardCreate(BaseModel):
    name: str
    objective: str
    hypothesis_text: str
    approach_ids: list[str] = Field(min_length=1)
    hypothesis_id: str | None = None
    baseline_methods: list[str] = Field(default_factory=list)
    independent_variables: dict[str, list] = Field(default_factory=dict)
    fixed_assumptions: dict[str, Any] = Field(default_factory=dict)
    metrics: list[str] = Field(default_factory=list)
    validation: ValidationCriteria = Field(default_factory=ValidationCriteria)
    runtime: RuntimeSpec = Field(default_factory=RuntimeSpec)
    artifacts: list[str] = Field(default_factory=list)
    estimated_cost: CostEstimateEnum = CostEstimateEnum.low
    estimated_runtime: CostEstimateEnum = CostEstimateEnum.medium
    experiment_type: ExperimentTypeEnum = ExperimentTypeEnum.simulation
    requires_human_approval: bool = True
    submission_mode: SubmissionModeEnum = SubmissionModeEnum.single_run
    required_capabilities: list[str] = Field(default_factory=list)
    runner_pool_preference: str | None = None
    experiment_control_plane: str | None = None


class ExperimentCardUpdate(BaseModel):
    name: str | None = None
    objective: str | None = None
    hypothesis_text: str | None = None
    baseline_methods: list[str] | None = None
    independent_variables: dict[str, list] | None = None
    fixed_assumptions: dict[str, Any] | None = None
    metrics: list[str] | None = None
    validation: ValidationCriteria | None = None
    runtime: RuntimeSpec | None = None
    artifacts: list[str] | None = None
    estimated_cost: CostEstimateEnum | None = None
    estimated_runtime: CostEstimateEnum | None = None
    experiment_type: ExperimentTypeEnum | None = None
    requires_human_approval: bool | None = None
    submission_mode: SubmissionModeEnum | None = None
    required_capabilities: list[str] | None = None
    runner_pool_preference: str | None = None
    experiment_control_plane: str | None = None


class ExperimentStatusUpdate(BaseModel):
    status: ExperimentStatusEnum


class ExecutionStatusUpdate(BaseModel):
    execution_status: ExecutionStatusEnum


class ExperimentCardResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    workspace_id: str
    name: str
    objective: str
    hypothesis_text: str
    approach_ids: list[str]
    hypothesis_id: str | None
    baseline_methods: list[str]
    independent_variables: dict[str, list]
    fixed_assumptions: dict[str, Any]
    metrics: list[str]
    validation: ValidationCriteria
    runtime: RuntimeSpec
    artifacts: list[str]
    estimated_cost: str
    estimated_runtime: str
    estimated_compute: str | None
    requires_human_approval: bool
    experiment_type: ExperimentTypeEnum
    parameter_sweep_count: int | None
    status: ExperimentStatusEnum
    execution_status: ExecutionStatusEnum
    execution_handoff: ExecutionHandoff
    generation_run_id: str | None
    created_at: datetime
    updated_at: datetime


class ExperimentListResponse(BaseModel):
    items: list[ExperimentCardResponse]
    total: int


class ExperimentGenerateResponse(BaseModel):
    generation_run_id: str
    goal_id: str
    experiments_created: int
    experiments_skipped_duplicate: int
    simulation_count: int
    measurement_count: int
    experiments: list[ExperimentCardResponse]


class ExperimentExportResponse(BaseModel):
    experiment_id: str
    format: str
    content: str


class ExperimentDimensionScoreResponse(BaseModel):
    dimension: ExperimentRubricDimensionEnum
    score: float
    weight: float
    weighted_score: float
    rationale: str


class ExperimentScoreResponse(BaseModel):
    experiment_id: str
    dimensions: list[ExperimentDimensionScoreResponse]
    total_score: float


class RunRequestPreviewItem(BaseModel):
    index: int
    parameters: dict[str, Any]


class RunRequestPreview(BaseModel):
    """CS-EXP-012: preview of the RunRequests a card would expand into."""

    experiment_id: str
    submission_mode: SubmissionModeEnum
    expanded_run_count: int
    truncated: bool
    variables: dict[str, list]
    required_capabilities: list[str]
    estimated_cost: str
    estimated_runtime: str
    requires_human_approval: bool
    approval_implication: str
    runs: list[RunRequestPreviewItem]
