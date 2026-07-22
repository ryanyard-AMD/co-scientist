from pydantic import BaseModel

from coscientist.schemas.validation import ValidationResultResponse


class RunnerResult(BaseModel):
    experiment_id: str
    goal_id: str
    run_id: str
    simulator: str  # the repro reproduction experiment_id that was run
    repro_status: str
    raw_metrics: dict[str, float]
    measured_metrics: dict[str, float]
    validation: ValidationResultResponse
    # recommend-method provenance: which reproduction repro chose for the card's
    # hypothesis, and whether it diverged from the card's committed method_family.
    recommendation: dict | None = None
