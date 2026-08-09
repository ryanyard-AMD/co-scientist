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


class ProductivityMetrics(BaseModel):
    goal_id: str
    agent_action_count: int
    minutes_per_agent_action: int
    estimated_time_saved_minutes: int
    estimated_time_saved_hours: float
    positive_feedback: int
    total_feedback: int
    satisfaction_rate: float | None


class HandoffSuccessMetrics(BaseModel):
    goal_id: str
    approved_experiments: int
    attempted_handoffs: int
    successful_handoffs: int
    failed_handoffs: int
    handoff_success_rate: float
    handoff_success_target: float
    handoff_success_meets_target: bool
    successful_run_requests: int
    retried_run_requests: int
    retry_successes: int
    retry_success_rate: float | None


class ExecutionTraceabilityMetrics(BaseModel):
    goal_id: str
    total_run_requests: int
    linked_to_goal: int
    linked_to_experiment: int
    linked_to_approach: int
    hypothesis_applicable: int
    linked_to_hypothesis: int
    linked_to_approval: int
    fully_traceable: int
    traceability_rate: float
    traceability_target: float
    traceability_meets_target: bool
    untraceable_run_request_ids: list[str]


class DuplicateIngestionMetrics(BaseModel):
    goal_id: str
    total_result_bundles: int
    distinct_ingestion_keys: int
    duplicate_bundle_count: int
    total_score_updates: int
    distinct_score_update_keys: int
    duplicate_score_update_count: int
    meets_target: bool


class StatusFreshnessMetrics(BaseModel):
    goal_id: str
    total_run_requests: int
    in_flight_run_requests: int
    stale_run_requests: int
    max_staleness_seconds: float | None
    mean_staleness_seconds: float | None
    threshold_seconds: int
    meets_target: bool
    stale_run_request_ids: list[str]


class CallbackHealthMetrics(BaseModel):
    goal_id: str
    total_control_plane_run_requests: int
    terminal_control_plane_run_requests: int
    callback_result_bundles: int
    callback_received_run_requests: int
    missing_callback_results: int
    callback_ingest_rate: float
    callback_ingest_target: float
    callback_ingest_meets_target: bool
    missing_run_request_ids: list[str]


class FailedRunUsefulnessMetrics(BaseModel):
    goal_id: str
    failed_run_count: int
    with_failure_reason: int
    with_artifacts: int
    retryable_count: int
    with_roadmap_action: int
    useful_count: int
    usefulness_rate: float
    usefulness_target: float
    meets_target: bool


class BatchAggregationQualityMetrics(BaseModel):
    goal_id: str
    total_batches: int
    completed_batches: int
    batch_completion_rate: float
    total_aggregations: int
    partial_aggregations: int
    partial_aggregation_rate: float
    mixed_aggregations: int
    mixed_outcome_rate: float


class EvaluationReport(BaseModel):
    goal_id: str
    approach_usefulness: ApproachUsefulnessMetrics
    evidence_grounding: EvidenceGroundingMetrics
    experiment_quality: ExperimentQualityMetrics
    productivity: ProductivityMetrics
    handoff_success: HandoffSuccessMetrics
    execution_traceability: ExecutionTraceabilityMetrics
    duplicate_ingestion: DuplicateIngestionMetrics
    status_freshness: StatusFreshnessMetrics
    callback_health: CallbackHealthMetrics
    failed_run_usefulness: FailedRunUsefulnessMetrics
    batch_aggregation_quality: BatchAggregationQualityMetrics

    @property
    def gate_results(self) -> list[bool]:
        """The pass/fail gates shown on the evaluation page, in display order.
        Duplicate ingestion contributes two gates (bundles, score updates) to
        mirror the two badges rendered there; batch aggregation and productivity
        have no target and are excluded."""
        return [
            self.approach_usefulness.usefulness_meets_target,
            self.approach_usefulness.traceability_meets_target,
            self.evidence_grounding.grounding_meets_target,
            self.evidence_grounding.unsupported_meets_target,
            self.experiment_quality.acceptance_meets_target,
            self.experiment_quality.validity_meets_target,
            self.handoff_success.handoff_success_meets_target,
            self.execution_traceability.traceability_meets_target,
            self.duplicate_ingestion.duplicate_bundle_count == 0,
            self.duplicate_ingestion.duplicate_score_update_count == 0,
            self.status_freshness.meets_target,
            self.callback_health.callback_ingest_meets_target,
            self.failed_run_usefulness.meets_target,
        ]

    @property
    def gates_total(self) -> int:
        return len(self.gate_results)

    @property
    def gates_passing(self) -> int:
        return sum(self.gate_results)
