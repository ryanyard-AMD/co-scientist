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


class ScoreRequest(BaseModel):
    weight_profile: WeightProfileEnum = WeightProfileEnum.default


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
