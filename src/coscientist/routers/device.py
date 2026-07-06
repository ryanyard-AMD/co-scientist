from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from coscientist.database import get_db
from coscientist.schemas.device import (
    DeviceConceptCardListResponse,
    DeviceConceptCardResponse,
    DeviceConceptComparisonResponse,
    DeviceConceptExportResponse,
    DeviceConceptGenerateRequest,
    DeviceConceptGenerateResponse,
    DeviceConceptStatusEnum,
    DeviceConceptTransitionRequest,
    DeviceEvidenceUpdateListResponse,
    DeviceExecutionEvidenceResponse,
)
from coscientist.services import device as device_svc
from coscientist.services import device_evidence as device_evidence_svc

router = APIRouter(prefix="/goals/{goal_id}/devices", tags=["device"])


@router.post("/generate", status_code=201, response_model=DeviceConceptGenerateResponse)
def generate_devices(
    goal_id: str,
    request: DeviceConceptGenerateRequest,
    db: Session = Depends(get_db),
):
    return device_svc.generate(db, goal_id, request)


@router.get("/compare", response_model=DeviceConceptComparisonResponse)
def compare_devices(
    goal_id: str,
    ids: str = Query(..., description="Comma-separated device IDs"),
    db: Session = Depends(get_db),
):
    device_ids = [i.strip() for i in ids.split(",") if i.strip()]
    return device_svc.compare(db, goal_id, device_ids)


@router.get("/evidence-updates", response_model=DeviceEvidenceUpdateListResponse)
def list_device_evidence_updates(
    goal_id: str,
    device_id: str | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return device_evidence_svc.list_evidence_updates(
        db, goal_id, device_id=device_id, skip=skip, limit=limit
    )


@router.get("", response_model=DeviceConceptCardListResponse)
def list_devices(
    goal_id: str,
    status: DeviceConceptStatusEnum | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return device_svc.list_devices(db, goal_id, status, skip, limit)


@router.get("/{device_id}", response_model=DeviceConceptCardResponse)
def get_device(
    goal_id: str,
    device_id: str,
    db: Session = Depends(get_db),
):
    return device_svc.get(db, device_id, goal_id)


@router.get("/{device_id}/execution-evidence", response_model=DeviceExecutionEvidenceResponse)
def device_execution_evidence(
    goal_id: str,
    device_id: str,
    db: Session = Depends(get_db),
):
    device_svc._get_or_404(db, device_id, goal_id)
    return device_evidence_svc.build_execution_evidence(db, device_id)


@router.post("/{device_id}/transition", response_model=DeviceConceptCardResponse)
def transition_device(
    goal_id: str,
    device_id: str,
    body: DeviceConceptTransitionRequest,
    db: Session = Depends(get_db),
):
    return device_svc.transition(db, device_id, goal_id, body.status)


@router.get("/{device_id}/export", response_model=DeviceConceptExportResponse)
def export_device(
    goal_id: str,
    device_id: str,
    format: str = Query(default="markdown", pattern="^(markdown|json)$"),
    db: Session = Depends(get_db),
):
    return device_svc.export_device(db, device_id, goal_id, format)


@router.delete("/{device_id}", status_code=204)
def delete_device(
    goal_id: str,
    device_id: str,
    db: Session = Depends(get_db),
):
    device_svc.delete(db, device_id, goal_id)
    return Response(status_code=204)
