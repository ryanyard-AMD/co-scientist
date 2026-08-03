from pydantic import BaseModel, Field

from coscientist.schemas.validation import ResultBundleIngestResponse, ValidationResultResponse


class ExecutionPreflightResponse(BaseModel):
    experiment_id: str
    goal_id: str
    runnable: bool
    blocking_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    run_count: int
    method_family: str | None = None
    selected_reproduction_id: str | None = None
    repro_workspace_id: str | None = None
    candidate_paper_id: str | None = None
    candidate_title: str | None = None
    candidate_method_families: list[str] = Field(default_factory=list)
    family_match: bool | None = None
    pass_conditions: list[dict] = Field(default_factory=list)
    unmeasurable_conditions: list[str] = Field(default_factory=list)
    metric_contract: dict = Field(default_factory=dict)
    design_run_payload: dict = Field(default_factory=dict)
    recommendation: dict | None = None


class RunnerResult(BaseModel):
    experiment_id: str
    goal_id: str
    run_id: str
    simulator: str  # the repro reproduction experiment_id that was run
    repro_status: str
    raw_metrics: dict[str, float]
    measured_metrics: dict[str, float]
    validation: ValidationResultResponse | None = None
    result_bundle: ResultBundleIngestResponse | None = None
    # recommend-method provenance: which reproduction repro chose for the card's
    # hypothesis, and whether it diverged from the card's committed method_family.
    recommendation: dict | None = None


# ---------------------------------------------------------------------------
# Comparison run (task #49): a >1-approach card is decomposed into per-approach
# single-method child runs, then compared on shared metrics.
# ---------------------------------------------------------------------------

class ApproachRunSummary(BaseModel):
    """Outcome of running one approach's child card through the single-method runner."""
    approach_id: str
    child_experiment_id: str
    method_family: str | None = None
    status: str  # child card status, or "error" if the child run raised
    decision: str | None = None
    measured_metrics: dict[str, float] = Field(default_factory=dict)
    error: str | None = None


class MetricComparison(BaseModel):
    """Per-metric head-to-head across the compared approaches."""
    metric: str
    direction: str  # "higher_better" | "lower_better"
    values: dict[str, float]  # approach_id -> measured value
    best_approach_id: str | None = None


class ComparisonResult(BaseModel):
    experiment_id: str
    goal_id: str
    approach_runs: list[ApproachRunSummary]
    metric_comparisons: list[MetricComparison]
    recommended_approach_id: str | None = None
    rationale: str
    status: str  # parent card status after the comparison
