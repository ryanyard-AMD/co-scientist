from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from coscientist.database import get_db
from coscientist.schemas.ontology import (
    OntologyCategoryEnum,
    RelationshipCreate,
    RelationshipResponse,
    TermCreate,
    TermListResponse,
    TermMergeRequest,
    TermResponse,
    TermUpdate,
)
from coscientist.services import ontology as svc

router = APIRouter(prefix="/ontology", tags=["ontology"])


@router.post("/terms", response_model=TermResponse, status_code=201)
def create_term(body: TermCreate, db: Session = Depends(get_db)):
    return svc.create_term(db, body)


@router.get("/terms", response_model=TermListResponse)
def list_terms(
    category: OntologyCategoryEnum | None = Query(default=None),
    status: str | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    items, total = svc.list_terms(db, category=category, status=status, skip=skip, limit=limit)
    return TermListResponse(items=items, total=total)


@router.get("/terms/{term_id}", response_model=TermResponse)
def get_term(term_id: str, db: Session = Depends(get_db)):
    return svc.get_term(db, term_id)


@router.patch("/terms/{term_id}", response_model=TermResponse)
def update_term(term_id: str, body: TermUpdate, db: Session = Depends(get_db)):
    return svc.update_term(db, term_id, body)


@router.delete("/terms/{term_id}", status_code=204)
def delete_term(term_id: str, db: Session = Depends(get_db)):
    svc.delete_term(db, term_id)
    return Response(status_code=204)


@router.post("/terms/merge", response_model=TermResponse)
def merge_terms(body: TermMergeRequest, db: Session = Depends(get_db)):
    return svc.merge_terms(db, body)


@router.get("/terms/{term_id}/related", response_model=list[TermResponse])
def get_related_terms(term_id: str, db: Session = Depends(get_db)):
    return svc.get_related_terms(db, term_id)


@router.post("/relationships", response_model=RelationshipResponse, status_code=201)
def create_relationship(body: RelationshipCreate, db: Session = Depends(get_db)):
    return svc.create_relationship(db, body)


@router.delete("/relationships/{rel_id}", status_code=204)
def delete_relationship(rel_id: str, db: Session = Depends(get_db)):
    svc.delete_relationship(db, rel_id)
    return Response(status_code=204)
