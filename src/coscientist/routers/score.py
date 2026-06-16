from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from coscientist.database import get_db
from coscientist.schemas.score import (
    ApproachScoreResponse,
    ParetoResponse,
    ScoreComparisonResponse,
    ScoreRequest,
    WeightProfileEnum,
)
from coscientist.services import score as svc

router = APIRouter(prefix="/goals/{goal_id}/approaches", tags=["scores"])


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
