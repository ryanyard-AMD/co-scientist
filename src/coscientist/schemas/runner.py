from pydantic import BaseModel

from coscientist.schemas.validation import ValidationResultResponse


class RunnerResult(BaseModel):
    experiment_id: str
    goal_id: str
    run_id: str
    simulator: str
    repro_status: str
    raw_metrics: dict[str, float]
    measured_metrics: dict[str, float]
    validation: ValidationResultResponse
