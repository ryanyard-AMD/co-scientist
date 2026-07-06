from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from coscientist.database import get_db
from coscientist.schemas.score import (
    ApproachScoreResponse,
    ParetoResponse,
    ScoreComparisonResponse,
    ScoreRequest,
    ScoreUpdateListResponse,
    WeightProfileEnum,
)
from coscientist.services import score as svc
from coscientist.services import score_update as score_update_svc

router = APIRouter(prefix="/goals/{goal_id}/approaches", tags=["scores"])

updates_router = APIRouter(prefix="/goals/{goal_id}/score-updates", tags=["scores"])


@updates_router.get("", response_model=ScoreUpdateListResponse)
def list_score_updates(
    goal_id: str,
    approach_id: str | None = Query(default=None),
    experiment_id: str | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return score_update_svc.list_score_updates(
        db, goal_id, approach_id=approach_id, experiment_id=experiment_id, skip=skip, limit=limit
    )


@router.post("/score-all", response_model=list[ApproachScoreResponse], status_code=201)
def score_all(
    goal_id: str,
    body: ScoreRequest,
    db: Session = Depends(get_db),
):
    return svc.score_all_approaches(db, goal_id, body.weight_profile)


@router.get("/comparison", response_model=ScoreComparisonResponse)
def comparison(
    goal_id: str,
    weight_profile: WeightProfileEnum = Query(default=WeightProfileEnum.default),
    db: Session = Depends(get_db),
):
    return svc.get_comparison(db, goal_id, weight_profile)


@router.get("/pareto", response_model=ParetoResponse)
def pareto(goal_id: str, db: Session = Depends(get_db)):
    return svc.get_pareto(db, goal_id)


@router.post("/{approach_id}/score", response_model=ApproachScoreResponse, status_code=201)
def score_approach(
    goal_id: str,
    approach_id: str,
    body: ScoreRequest,
    db: Session = Depends(get_db),
):
    return svc.score_approach(db, approach_id, body.weight_profile)


@router.get("/{approach_id}/scores", response_model=ApproachScoreResponse)
def get_scores(
    goal_id: str,
    approach_id: str,
    db: Session = Depends(get_db),
):
    return svc.get_scores(db, approach_id)


@router.post("/{approach_id}/rescore", response_model=ApproachScoreResponse)
def rescore(
    goal_id: str,
    approach_id: str,
    body: ScoreRequest,
    db: Session = Depends(get_db),
):
    return svc.rescore(db, approach_id, body.weight_profile)
