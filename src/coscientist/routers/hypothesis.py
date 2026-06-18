from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from coscientist.database import get_db
from coscientist.schemas.hypothesis import (
    HypothesisCardCreate,
    HypothesisCardResponse,
    HypothesisCardUpdate,
    HypothesisGenerateRequest,
    HypothesisGenerateResponse,
    HypothesisListResponse,
    HypothesisStatusEnum,
    HypothesisStatusUpdate,
    HypothesisTypeEnum,
)
from coscientist.services import hypothesis as svc

router = APIRouter(prefix="/goals/{goal_id}/hypotheses", tags=["hypotheses"])


@router.post("/generate", response_model=HypothesisGenerateResponse, status_code=201)
def generate_hypotheses(
    goal_id: str,
    body: HypothesisGenerateRequest,
    db: Session = Depends(get_db),
):
    return svc.generate_hypotheses(db, goal_id, body)


@router.post("", response_model=HypothesisCardResponse, status_code=201)
def create_hypothesis(goal_id: str, body: HypothesisCardCreate, db: Session = Depends(get_db)):
    return svc.create(db, goal_id, body)


@router.get("", response_model=HypothesisListResponse)
def list_hypotheses(
    goal_id: str,
    status: HypothesisStatusEnum | None = Query(default=None),
    hypothesis_type: HypothesisTypeEnum | None = Query(default=None, alias="type"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    items, total = svc.list_hypotheses(
        db, goal_id, status=status, hypothesis_type=hypothesis_type,
        skip=skip, limit=limit,
    )
    return HypothesisListResponse(items=items, total=total)


@router.get("/{hypothesis_id}", response_model=HypothesisCardResponse)
def get_hypothesis(goal_id: str, hypothesis_id: str, db: Session = Depends(get_db)):
    return svc.get(db, hypothesis_id)


@router.patch("/{hypothesis_id}", response_model=HypothesisCardResponse)
def update_hypothesis(
    goal_id: str, hypothesis_id: str,
    body: HypothesisCardUpdate,
    db: Session = Depends(get_db),
):
    return svc.update(db, hypothesis_id, body)


@router.post("/{hypothesis_id}/transition", response_model=HypothesisCardResponse)
def transition_hypothesis(
    goal_id: str, hypothesis_id: str,
    body: HypothesisStatusUpdate,
    db: Session = Depends(get_db),
):
    return svc.transition(db, hypothesis_id, body.status)


@router.delete("/{hypothesis_id}", status_code=204)
def delete_hypothesis(goal_id: str, hypothesis_id: str, db: Session = Depends(get_db)):
    svc.delete(db, hypothesis_id)
    return Response(status_code=204)
