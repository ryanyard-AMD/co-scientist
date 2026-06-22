from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from coscientist.database import get_db
from coscientist.schemas.validation import (
    ExperimentResultSubmission,
    ValidationResultListResponse,
    ValidationResultResponse,
)
from coscientist.services import validation as svc

router = APIRouter(prefix="/goals/{goal_id}/experiments", tags=["validation"])


@router.post("/{experiment_id}/results", response_model=ValidationResultResponse, status_code=201)
def submit_results(
    goal_id: str,
    experiment_id: str,
    body: ExperimentResultSubmission,
    db: Session = Depends(get_db),
):
    return svc.submit_results(db, experiment_id, goal_id, body)


@router.get("/{experiment_id}/results", response_model=ValidationResultResponse)
def get_result(
    goal_id: str,
    experiment_id: str,
    db: Session = Depends(get_db),
):
    result = svc.get_result(db, experiment_id, goal_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"No validation result for experiment {experiment_id!r}",
        )
    return result


@router.get("/results", response_model=ValidationResultListResponse)
def list_results(
    goal_id: str,
    db: Session = Depends(get_db),
):
    return svc.list_results(db, goal_id)
