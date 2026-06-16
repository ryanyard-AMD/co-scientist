from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from coscientist.database import get_db
from coscientist.schemas.scout import (
    EvidenceGroupResponse,
    EvidenceListResponse,
    EvidenceRecordResponse,
    ScoutResultResponse,
    ScoutRunRequest,
    ScoutSummaryStats,
)
from coscientist.services import scout as svc

router = APIRouter(prefix="/goals/{goal_id}/scout", tags=["scout"])


@router.post("", response_model=ScoutResultResponse, status_code=201)
def run_scout(goal_id: str, body: ScoutRunRequest, db: Session = Depends(get_db)):
    return svc.run_scout(db, goal_id, body)


@router.get("/evidence", response_model=EvidenceListResponse)
def list_evidence(
    goal_id: str,
    scout_run_id: str | None = Query(default=None),
    method_family: str | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    items, total = svc.get_evidence(
        db, goal_id,
        scout_run_id=scout_run_id,
        method_family=method_family,
        skip=skip, limit=limit,
    )
    return EvidenceListResponse(items=items, total=total)


@router.get("/evidence/groups", response_model=EvidenceGroupResponse)
def get_evidence_groups(
    goal_id: str,
    group_by: str = Query(
        default="method_family",
        pattern="^(method_family|metric|hardware|failure_mode)$",
    ),
    scout_run_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return svc.get_evidence_groups(db, goal_id, group_by=group_by, scout_run_id=scout_run_id)


@router.get("/evidence/summary", response_model=ScoutSummaryStats)
def get_summary(
    goal_id: str,
    scout_run_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return svc.get_summary(db, goal_id, scout_run_id=scout_run_id)


@router.get("/evidence/{evidence_id}", response_model=EvidenceRecordResponse)
def get_evidence_detail(
    goal_id: str,
    evidence_id: str,
    db: Session = Depends(get_db),
):
    return svc.get_evidence_by_id(db, goal_id, evidence_id)
