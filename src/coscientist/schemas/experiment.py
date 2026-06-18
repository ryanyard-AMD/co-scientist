from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ExperimentStatusEnum(str, Enum):
    generated = "generated"
    reviewed = "reviewed"
    approved = "approved"
    running = "running"
    completed = "completed"
    failed = "failed"
    superseded = "superseded"


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


class ExperimentStatusUpdate(BaseModel):
    status: ExperimentStatusEnum


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
