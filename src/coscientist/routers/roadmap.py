from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from coscientist.database import get_db
from coscientist.schemas.roadmap import (
    ResearchRoadmapItemResponse,
    ResearchRoadmapListResponse,
    RoadmapGenerateRequest,
    RoadmapLaneEnum,
    RoadmapStatusEnum,
    RoadmapTransitionRequest,
)
from coscientist.services import roadmap as roadmap_svc

router = APIRouter(prefix="/goals/{goal_id}/roadmap", tags=["roadmap"])


@router.post("/generate", status_code=201, response_model=ResearchRoadmapListResponse)
def generate_roadmap(
    goal_id: str,
    request: RoadmapGenerateRequest,
    db: Session = Depends(get_db),
):
    return roadmap_svc.generate(db, goal_id)


@router.get("", response_model=ResearchRoadmapListResponse)
def list_roadmap(
    goal_id: str,
    lane: RoadmapLaneEnum | None = Query(default=None),
    status: RoadmapStatusEnum | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return roadmap_svc.get_roadmap(db, goal_id, lane, status, skip, limit)


@router.get("/{item_id}", response_model=ResearchRoadmapItemResponse)
def get_roadmap_item(
    goal_id: str,
    item_id: str,
    db: Session = Depends(get_db),
):
    return roadmap_svc.get_item(db, item_id, goal_id)


@router.post("/{item_id}/transition", response_model=ResearchRoadmapItemResponse)
def transition_roadmap_item(
    goal_id: str,
    item_id: str,
    body: RoadmapTransitionRequest,
    db: Session = Depends(get_db),
):
    return roadmap_svc.transition_item(db, item_id, goal_id, body.status)
