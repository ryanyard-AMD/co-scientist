import json
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from coscientist.domain import (
    FAILURE_MODES,
    HARDWARE_TERMS,
    METHOD_FAMILIES,
    METRIC_NAMES,
    RELATED_METHODS,
)
from coscientist.models.evidence import EvidenceRecord
from coscientist.models.ontology import OntologyRelationship, OntologyTerm
from coscientist.schemas.ontology import (
    OntologyCategoryEnum,
    RelationshipCreate,
    RelationshipResponse,
    TermCreate,
    TermMergeRequest,
    TermResponse,
    TermUpdate,
)


def _term_to_response(term: OntologyTerm) -> TermResponse:
    return TermResponse(
        id=term.id,
        canonical_name=term.canonical_name,
        category=OntologyCategoryEnum(term.category),
        description=term.description,
        keywords=json.loads(term.keywords),
        status=term.status,
        workspace_id=term.workspace_id,
        created_at=term.created_at,
        updated_at=term.updated_at,
    )


def _rel_to_response(rel: OntologyRelationship) -> RelationshipResponse:
    return RelationshipResponse(
        id=rel.id,
        source_term_id=rel.source_term_id,
        target_term_id=rel.target_term_id,
        relationship_type=rel.relationship_type,
        created_at=rel.created_at,
    )


def _get_term_or_404(db: Session, term_id: str) -> OntologyTerm:
    term = db.get(OntologyTerm, term_id)
    if term is None:
        raise HTTPException(status_code=404, detail=f"Term {term_id!r} not found")
    return term


def create_term(db: Session, data: TermCreate) -> TermResponse:
    existing = db.scalar(
        select(OntologyTerm).where(
            OntologyTerm.category == data.category.value,
            OntologyTerm.canonical_name == data.canonical_name,
        )
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Term {data.canonical_name!r} already exists in category {data.category.value!r}",
        )

    now = datetime.now(timezone.utc)
    term = OntologyTerm(
        id=str(uuid.uuid4()),
        canonical_name=data.canonical_name,
        category=data.category.value,
        description=data.description,
        keywords=json.dumps(data.keywords),
        status="active",
        created_at=now,
        updated_at=now,
    )
    db.add(term)
    db.commit()
    db.refresh(term)
    return _term_to_response(term)


def get_term(db: Session, term_id: str) -> TermResponse:
    return _term_to_response(_get_term_or_404(db, term_id))


def get_term_by_name(
    db: Session, category: OntologyCategoryEnum, canonical_name: str
) -> TermResponse:
    term = db.scalar(
        select(OntologyTerm).where(
            OntologyTerm.category == category.value,
            OntologyTerm.canonical_name == canonical_name,
        )
    )
    if term is None:
        raise HTTPException(
            status_code=404,
            detail=f"Term {canonical_name!r} not found in category {category.value!r}",
        )
    return _term_to_response(term)


def list_terms(
    db: Session,
    category: OntologyCategoryEnum | None = None,
    status: str | None = None,
    workspace_id: str | None = None,
    skip: int = 0,
    limit: int = 100,
) -> tuple[list[TermResponse], int]:
    q = select(OntologyTerm)
    if category is not None:
        q = q.where(OntologyTerm.category == category.value)
    if status is not None:
        q = q.where(OntologyTerm.status == status)
    if workspace_id is not None:
        q = q.where(OntologyTerm.workspace_id == workspace_id)

    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(OntologyTerm.category, OntologyTerm.canonical_name).offset(skip).limit(limit)).all()
    return [_term_to_response(r) for r in rows], total or 0


def update_term(db: Session, term_id: str, data: TermUpdate) -> TermResponse:
    term = _get_term_or_404(db, term_id)
    if data.canonical_name is not None:
        dup = db.scalar(
            select(OntologyTerm).where(
                OntologyTerm.category == term.category,
                OntologyTerm.canonical_name == data.canonical_name,
                OntologyTerm.id != term.id,
            )
        )
        if dup:
            raise HTTPException(
                status_code=409,
                detail=f"Term {data.canonical_name!r} already exists in category {term.category!r}",
            )
        term.canonical_name = data.canonical_name
    if data.description is not None:
        term.description = data.description
    if data.keywords is not None:
        term.keywords = json.dumps(data.keywords)
    if data.status is not None:
        term.status = data.status
    term.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(term)
    return _term_to_response(term)


def delete_term(db: Session, term_id: str) -> None:
    term = _get_term_or_404(db, term_id)
    if term.status != "deprecated":
        raise HTTPException(
            status_code=409,
            detail="Only deprecated terms can be deleted",
        )
    db.execute(
        select(OntologyRelationship).where(
            or_(
                OntologyRelationship.source_term_id == term_id,
                OntologyRelationship.target_term_id == term_id,
            )
        )
    )
    rels = db.scalars(
        select(OntologyRelationship).where(
            or_(
                OntologyRelationship.source_term_id == term_id,
                OntologyRelationship.target_term_id == term_id,
            )
        )
    ).all()
    for r in rels:
        db.delete(r)
    db.delete(term)
    db.commit()


def merge_terms(db: Session, data: TermMergeRequest) -> TermResponse:
    source = _get_term_or_404(db, data.source_term_id)
    target = _get_term_or_404(db, data.target_term_id)

    if source.category != target.category:
        raise HTTPException(
            status_code=422,
            detail="Cannot merge terms from different categories",
        )

    # Merge keywords
    target_kw = json.loads(target.keywords)
    source_kw = json.loads(source.keywords)
    merged = list(dict.fromkeys(target_kw + source_kw))
    target.keywords = json.dumps(merged)
    target.updated_at = datetime.now(timezone.utc)

    # Move relationships from source to target
    source_rels = db.scalars(
        select(OntologyRelationship).where(
            OntologyRelationship.source_term_id == source.id
        )
    ).all()
    for rel in source_rels:
        if rel.target_term_id == target.id:
            db.delete(rel)
        else:
            rel.source_term_id = target.id

    target_rels = db.scalars(
        select(OntologyRelationship).where(
            OntologyRelationship.target_term_id == source.id
        )
    ).all()
    for rel in target_rels:
        if rel.source_term_id == target.id:
            db.delete(rel)
        else:
            rel.target_term_id = target.id

    # Update EvidenceRecord JSON fields that reference the source canonical name
    _category_to_field = {
        "method": "method_families",
        "metric": "metric_names",
        "hardware": "hardware_assumptions",
        "failure_mode": "failure_modes",
    }
    field_name = _category_to_field.get(source.category)
    if field_name:
        col = getattr(EvidenceRecord, field_name)
        records = db.scalars(
            select(EvidenceRecord).where(col.contains(source.canonical_name))
        ).all()
        for rec in records:
            raw = json.loads(getattr(rec, field_name) or "[]")
            updated = [target.canonical_name if v == source.canonical_name else v for v in raw]
            updated = list(dict.fromkeys(updated))
            setattr(rec, field_name, json.dumps(updated))

    # Deprecate source
    source.status = "deprecated"
    source.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(target)
    return _term_to_response(target)


def create_relationship(db: Session, data: RelationshipCreate) -> RelationshipResponse:
    _get_term_or_404(db, data.source_term_id)
    _get_term_or_404(db, data.target_term_id)

    now = datetime.now(timezone.utc)
    rel = OntologyRelationship(
        id=str(uuid.uuid4()),
        source_term_id=data.source_term_id,
        target_term_id=data.target_term_id,
        relationship_type=data.relationship_type.value,
        created_at=now,
    )
    db.add(rel)
    db.commit()
    db.refresh(rel)
    return _rel_to_response(rel)


def delete_relationship(db: Session, rel_id: str) -> None:
    rel = db.get(OntologyRelationship, rel_id)
    if rel is None:
        raise HTTPException(status_code=404, detail=f"Relationship {rel_id!r} not found")
    db.delete(rel)
    db.commit()


def get_related_terms(db: Session, term_id: str) -> list[TermResponse]:
    _get_term_or_404(db, term_id)
    rels = db.scalars(
        select(OntologyRelationship).where(
            or_(
                OntologyRelationship.source_term_id == term_id,
                OntologyRelationship.target_term_id == term_id,
            )
        )
    ).all()

    related_ids = set()
    for r in rels:
        if r.source_term_id == term_id:
            related_ids.add(r.target_term_id)
        else:
            related_ids.add(r.source_term_id)

    if not related_ids:
        return []

    terms = db.scalars(
        select(OntologyTerm).where(OntologyTerm.id.in_(related_ids))
    ).all()
    return [_term_to_response(t) for t in terms]


def get_all_terms_by_category(
    db: Session, category: OntologyCategoryEnum
) -> list[OntologyTerm]:
    return list(
        db.scalars(
            select(OntologyTerm).where(
                OntologyTerm.category == category.value,
                OntologyTerm.status == "active",
            )
        ).all()
    )


def seed_default_ontology(db: Session) -> dict[str, int]:
    """Idempotently seed ontology terms and method relationships from domain dicts.

    Returns counts of terms and relationships newly created.
    """
    category_dicts = {
        "method": METHOD_FAMILIES,
        "metric": METRIC_NAMES,
        "hardware": HARDWARE_TERMS,
        "failure_mode": FAILURE_MODES,
    }
    now = datetime.now(timezone.utc)
    terms_added = 0
    for category, mapping in category_dicts.items():
        for canonical, keywords in mapping.items():
            existing = db.scalar(
                select(OntologyTerm).where(
                    OntologyTerm.category == category,
                    OntologyTerm.canonical_name == canonical,
                )
            )
            if existing:
                continue
            db.add(OntologyTerm(
                id=str(uuid.uuid4()),
                canonical_name=canonical,
                category=category,
                keywords=json.dumps(keywords),
                status="active",
                created_at=now,
                updated_at=now,
            ))
            terms_added += 1
    db.flush()

    method_ids = {
        t.canonical_name: t.id
        for t in db.scalars(
            select(OntologyTerm).where(OntologyTerm.category == "method")
        ).all()
    }
    existing_pairs = {
        (r.source_term_id, r.target_term_id)
        for r in db.scalars(select(OntologyRelationship)).all()
    }
    rels_added = 0
    for source, targets in RELATED_METHODS.items():
        src_id = method_ids.get(source)
        if not src_id:
            continue
        for target in targets:
            tgt_id = method_ids.get(target)
            if not tgt_id or (src_id, tgt_id) in existing_pairs:
                continue
            db.add(OntologyRelationship(
                id=str(uuid.uuid4()),
                source_term_id=src_id,
                target_term_id=tgt_id,
                relationship_type="related_to",
                created_at=now,
            ))
            existing_pairs.add((src_id, tgt_id))
            rels_added += 1
    db.commit()
    return {"terms_added": terms_added, "relationships_added": rels_added}
