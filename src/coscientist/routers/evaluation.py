from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from coscientist.database import get_db
from coscientist.schemas.evaluation import (
    ApproachUsefulnessMetrics,
    EvaluationReport,
    EvidenceGroundingMetrics,
    ExperimentQualityMetrics,
    ProductivityMetrics,
)
from coscientist.services import evaluation as svc

router = APIRouter(prefix="/goals/{goal_id}/evaluation", tags=["evaluation"])


@router.get("", response_model=EvaluationReport)
def report(goal_id: str, db: Session = Depends(get_db)):
    return svc.get_report(db, goal_id)


@router.get("/approach-usefulness", response_model=ApproachUsefulnessMetrics)
def approach_usefulness(goal_id: str, db: Session = Depends(get_db)):
    return svc.approach_usefulness(db, goal_id)


@router.get("/evidence-grounding", response_model=EvidenceGroundingMetrics)
def evidence_grounding(goal_id: str, db: Session = Depends(get_db)):
    return svc.evidence_grounding(db, goal_id)


@router.get("/experiment-quality", response_model=ExperimentQualityMetrics)
def experiment_quality(goal_id: str, db: Session = Depends(get_db)):
    return svc.experiment_quality(db, goal_id)


@router.get("/productivity", response_model=ProductivityMetrics)
def productivity(goal_id: str, db: Session = Depends(get_db)):
    return svc.productivity(db, goal_id)
