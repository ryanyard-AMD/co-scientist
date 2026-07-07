from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from coscientist.database import get_db
from coscientist.schemas.governance import (
    AgentActionLogListResponse,
    AgentActionLogResponse,
    EvidenceLabelResponse,
    ExecutionAuditActionEnum,
    ExecutionAuditLogListResponse,
)
from coscientist.services import governance as svc

router = APIRouter(prefix="/goals/{goal_id}/agent-logs", tags=["governance"])

audit_router = APIRouter(prefix="/goals/{goal_id}/execution-audit", tags=["governance"])

label_router = APIRouter(prefix="/goals/{goal_id}/experiments", tags=["governance"])


@label_router.get("/{experiment_id}/evidence-label", response_model=EvidenceLabelResponse)
def experiment_evidence_label(
    goal_id: str, experiment_id: str, db: Session = Depends(get_db)
):
    return svc.experiment_evidence_label(db, experiment_id)


@audit_router.get("", response_model=ExecutionAuditLogListResponse)
def list_execution_audit(
    goal_id: str,
    experiment_id: str | None = Query(default=None),
    action: ExecutionAuditActionEnum | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return svc.list_execution_audit(
        db, goal_id, experiment_id=experiment_id, action=action, skip=skip, limit=limit
    )


@router.get("", response_model=AgentActionLogListResponse)
def list_agent_logs(
    goal_id: str,
    service: str | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return svc.list_logs(db, goal_id, service=service, skip=skip, limit=limit)


@router.get("/{log_id}", response_model=AgentActionLogResponse)
def get_agent_log(goal_id: str, log_id: str, db: Session = Depends(get_db)):
    return svc.get_log(db, log_id, goal_id)
