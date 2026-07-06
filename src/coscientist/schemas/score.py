from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class RubricDimensionEnum(str, Enum):
    evidence_strength = "evidence_strength"
    reproducibility = "reproducibility"
    acoustic_performance = "acoustic_performance"
    robustness = "robustness"
    realtime_feasibility = "realtime_feasibility"
    hardware_feasibility = "hardware_feasibility"
    calibration_burden = "calibration_burden"
    composability = "composability"
    measurement_clarity = "measurement_clarity"
    device_relevance = "device_relevance"


class WeightProfileEnum(str, Enum):
    default = "default"
    fastest_prototype = "fastest_prototype"
    scientific_novelty = "scientific_novelty"
    robustness = "robustness"
    product_feasibility = "product_feasibility"


class ExecutionEvidenceTypeEnum(str, Enum):
    approved_experiment_design = "approved_experiment_design"
    queued_experiment = "queued_experiment"
    completed_experiment = "completed_experiment"
    failed_experiment = "failed_experiment"
    validation_passed = "validation_passed"
    validation_failed = "validation_failed"
    mixed_validation = "mixed_validation"


class ScoreRequest(BaseModel):
    weight_profile: WeightProfileEnum = WeightProfileEnum.default


class ScoreUpdateResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    source_key: str
    workspace_id: str
    approach_id: str
    experiment_id: str
    execution_batch_id: str | None
    dimension: str
    validation_status: str
    evidence_type: ExecutionEvidenceTypeEnum
    previous_score: float
    new_score: float
    score_delta: float
    previous_confidence: float | None
    new_confidence: float | None
    confidence_delta: float
    run_count: int
    passed_count: int
    failed_count: int
    missing_count: int
    result_bundle_refs: list[str]
    aggregate_metrics: dict
    rationale: str
    reviewer_notes: str | None
    created_at: datetime


class ScoreUpdateListResponse(BaseModel):
    items: list[ScoreUpdateResponse]
    total: int


class WeightOverride(BaseModel):
    dimension: RubricDimensionEnum
    weight: float = Field(ge=0.0, le=1.0)


class DimensionScoreResponse(BaseModel):
    dimension: RubricDimensionEnum
    score: float
    weight: float
    weighted_score: float
    confidence: float | None
    rationale: str
    evidence_ids: list[str]
    low_confidence: bool


class ApproachScoreResponse(BaseModel):
    approach_id: str
    approach_name: str
    method_family: str
    dimensions: list[DimensionScoreResponse]
    total_score: float
    risk_penalty: float
    final_score: float
    scoring_run_id: str


class DimensionRanking(BaseModel):
    dimension: RubricDimensionEnum
    rankings: list[dict]


class ScoreComparisonResponse(BaseModel):
    approaches: list[ApproachScoreResponse]
    dimension_rankings: list[DimensionRanking]


class ParetoResponse(BaseModel):
    pareto_optimal: list[ApproachScoreResponse]
    dominated: list[ApproachScoreResponse]
    dimension_rankings: list[DimensionRanking]
