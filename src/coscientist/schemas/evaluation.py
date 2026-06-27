from pydantic import BaseModel


class ApproachUsefulnessMetrics(BaseModel):
    goal_id: str
    total: int
    by_status: dict[str, int]
    useful_count: int
    discarded_count: int
    pending_count: int
    usefulness_rate: float
    usefulness_target: float
    usefulness_meets_target: bool
    traceable_count: int
    traceability_rate: float
    traceability_target: float
    traceability_meets_target: bool


class UnsupportedClaim(BaseModel):
    approach_id: str
    approach_name: str
    claim_field: str


class EvidenceGroundingMetrics(BaseModel):
    goal_id: str
    total_claims: int
    grounded: int
    inferred: int
    unsupported: int
    grounding_rate: float
    grounding_target: float
    grounding_meets_target: bool
    unsupported_rate: float
    unsupported_target: float
    unsupported_meets_target: bool
    unsupported_claims: list[UnsupportedClaim]


class ExperimentQualityMetrics(BaseModel):
    goal_id: str
    total: int
    by_status: dict[str, int]
    accepted_count: int
    discarded_count: int
    failed_count: int
    pending_count: int
    acceptance_rate: float
    acceptance_target: float
    acceptance_meets_target: bool
    valid_count: int
    validity_rate: float
    validity_target: float
    validity_meets_target: bool
    invalid_experiment_ids: list[str]


class EvaluationReport(BaseModel):
    goal_id: str
    approach_usefulness: ApproachUsefulnessMetrics
    evidence_grounding: EvidenceGroundingMetrics
    experiment_quality: ExperimentQualityMetrics
