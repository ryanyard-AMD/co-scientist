from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from coscientist.database import get_db
from coscientist.schemas.critic import (
    ApproachCritiqueRequest,
    ApproachCritiqueResponse,
    CritiqueRunResponse,
)
from coscientist.services import critic as svc

router = APIRouter(prefix="/goals/{goal_id}/critique", tags=["critic"])


@router.post("", response_model=CritiqueRunResponse, status_code=201)
def critique_approaches(goal_id: str, body: ApproachCritiqueRequest, db: Session = Depends(get_db)):
    return svc.critique_approaches(db, goal_id, body)


@router.get("", response_model=list[ApproachCritiqueResponse])
def get_critiques(
    goal_id: str,
    approach_id: str | None = Query(default=None),
    critique_run_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return svc.get_critiques(
        db, goal_id, approach_id=approach_id, critique_run_id=critique_run_id
    )
