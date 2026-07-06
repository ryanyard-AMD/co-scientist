"""HTTP surface for ResultBundle ingestion + validation aggregation
(CS-EPIC-VALIDATION). Ingestion is driven by the external Experimentation
System (poll or webhook); reads surface aggregated outcomes per Experiment Card.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from coscientist.database import get_db
from coscientist.schemas.validation import (
    ResultBundleIngest,
    ResultBundleIngestResponse,
    ResultBundleListResponse,
    ValidationAggregationResponse,
)
from coscientist.services import result_bundle as svc

router = APIRouter(tags=["result-bundle"])


@router.post("/result-bundles", response_model=ResultBundleIngestResponse)
def ingest(body: ResultBundleIngest, db: Session = Depends(get_db)):
    return svc.ingest_result_bundle(db, body)


@router.get(
    "/experiments/{experiment_id}/validation-aggregation",
    response_model=ValidationAggregationResponse,
)
def get_aggregation(experiment_id: str, db: Session = Depends(get_db)):
    return svc.get_aggregation(db, experiment_id)


@router.get(
    "/experiments/{experiment_id}/result-bundles",
    response_model=ResultBundleListResponse,
)
def list_bundles(experiment_id: str, db: Session = Depends(get_db)):
    items, total = svc.list_bundles(db, experiment_id)
    return ResultBundleListResponse(items=items, total=total)
