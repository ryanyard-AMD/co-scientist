from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from coscientist.database import get_db
from coscientist.schemas.experiment import (
    ExperimentCardCreate,
    ExperimentCardResponse,
    ExperimentCardUpdate,
    ExperimentExportResponse,
    ExperimentGenerateRequest,
    ExperimentGenerateResponse,
    ExperimentListResponse,
    ExperimentScoreResponse,
    ExperimentStatusEnum,
    ExperimentStatusUpdate,
    ExperimentTypeEnum,
)
from coscientist.schemas.runner import RunnerResult
from coscientist.services import experiment as svc
from coscientist.services import roadmap as roadmap_svc
from coscientist.services import runner as runner_svc

router = APIRouter(prefix="/goals/{goal_id}/experiments", tags=["experiments"])


@router.post("/generate", response_model=ExperimentGenerateResponse, status_code=201)
def generate_experiments(
    goal_id: str,
    body: ExperimentGenerateRequest,
    db: Session = Depends(get_db),
):
    return svc.generate_experiments(db, goal_id, body)


@router.post("", response_model=ExperimentCardResponse, status_code=201)
def create_experiment(goal_id: str, body: ExperimentCardCreate, db: Session = Depends(get_db)):
    return svc.create(db, goal_id, body)


@router.get("", response_model=ExperimentListResponse)
def list_experiments(
    goal_id: str,
    status: ExperimentStatusEnum | None = Query(default=None),
    experiment_type: ExperimentTypeEnum | None = Query(default=None, alias="type"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    items, total = svc.list_experiments(
        db, goal_id, status=status, experiment_type=experiment_type,
        skip=skip, limit=limit,
    )
    return ExperimentListResponse(items=items, total=total)


@router.get("/{experiment_id}", response_model=ExperimentCardResponse)
def get_experiment(goal_id: str, experiment_id: str, db: Session = Depends(get_db)):
    return svc.get(db, experiment_id)


@router.patch("/{experiment_id}", response_model=ExperimentCardResponse)
def update_experiment(
    goal_id: str, experiment_id: str,
    body: ExperimentCardUpdate,
    db: Session = Depends(get_db),
):
    return svc.update(db, experiment_id, body)


@router.post("/{experiment_id}/transition", response_model=ExperimentCardResponse)
def transition_experiment(
    goal_id: str, experiment_id: str,
    body: ExperimentStatusUpdate,
    db: Session = Depends(get_db),
):
    result = svc.transition(db, experiment_id, body.status)
    if body.status in (ExperimentStatusEnum.completed, ExperimentStatusEnum.failed):
        roadmap_svc.retire_for_experiment(db, experiment_id, goal_id)
    return result


@router.post("/{experiment_id}/run", response_model=RunnerResult)
def run_experiment(
    goal_id: str, experiment_id: str,
    timeout: float | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
):
    return runner_svc.run_experiment(db, experiment_id, goal_id, timeout=timeout)


@router.post("/{experiment_id}/score", response_model=ExperimentScoreResponse)
def score_experiment(
    goal_id: str, experiment_id: str,
    db: Session = Depends(get_db),
):
    return svc.score_experiment(db, experiment_id, goal_id)


@router.get("/{experiment_id}/export", response_model=ExperimentExportResponse)
def export_experiment(
    goal_id: str, experiment_id: str,
    fmt: str = Query(default="yaml", alias="format"),
    db: Session = Depends(get_db),
):
    return svc.export_experiment(db, experiment_id, fmt)


@router.delete("/{experiment_id}", status_code=204)
def delete_experiment(goal_id: str, experiment_id: str, db: Session = Depends(get_db)):
    svc.delete(db, experiment_id)
    return Response(status_code=204)
