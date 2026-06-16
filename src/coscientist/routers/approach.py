from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from coscientist.database import get_db
from coscientist.schemas.approach import (
    ApproachCardCreate,
    ApproachCardResponse,
    ApproachCardUpdate,
    ApproachGenerateRequest,
    ApproachGenerateResponse,
    ApproachListResponse,
    ApproachMergeRequest,
    ApproachStatusEnum,
    ApproachStatusUpdate,
    DuplicateWarning,
)
from coscientist.services import approach as svc

router = APIRouter(prefix="/goals/{goal_id}/approaches", tags=["approaches"])


@router.post("/generate", response_model=ApproachGenerateResponse, status_code=201)
def generate_approaches(
    goal_id: str,
    body: ApproachGenerateRequest,
    db: Session = Depends(get_db),
):
    return svc.generate_approaches(db, goal_id, body)


@router.get("/duplicates", response_model=list[DuplicateWarning])
def find_duplicates(goal_id: str, db: Session = Depends(get_db)):
    return svc.find_duplicates(db, goal_id)


@router.post("/merge", response_model=ApproachCardResponse)
def merge_approaches(goal_id: str, body: ApproachMergeRequest, db: Session = Depends(get_db)):
    return svc.merge_approaches(db, body)


@router.post("", response_model=ApproachCardResponse, status_code=201)
def create_approach(goal_id: str, body: ApproachCardCreate, db: Session = Depends(get_db)):
    return svc.create(db, goal_id, body)


@router.get("", response_model=ApproachListResponse)
def list_approaches(
    goal_id: str,
    status: ApproachStatusEnum | None = Query(default=None),
    method_family: str | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    items, total = svc.list_approaches(
        db, goal_id, status=status, method_family=method_family, skip=skip, limit=limit,
    )
    return ApproachListResponse(items=items, total=total)


@router.get("/{approach_id}", response_model=ApproachCardResponse)
def get_approach(goal_id: str, approach_id: str, db: Session = Depends(get_db)):
    return svc.get(db, approach_id)


@router.patch("/{approach_id}", response_model=ApproachCardResponse)
def update_approach(goal_id: str, approach_id: str, body: ApproachCardUpdate, db: Session = Depends(get_db)):
    return svc.update(db, approach_id, body)


@router.post("/{approach_id}/transition", response_model=ApproachCardResponse)
def transition_approach(
    goal_id: str,
    approach_id: str,
    body: ApproachStatusUpdate,
    db: Session = Depends(get_db),
):
    return svc.transition(db, approach_id, body.status)


@router.delete("/{approach_id}", status_code=204)
def delete_approach(goal_id: str, approach_id: str, db: Session = Depends(get_db)):
    svc.delete(db, approach_id)
    return Response(status_code=204)
