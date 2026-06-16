import json
import uuid
from datetime import datetime, timezone

import pytest

from coscientist.models.evidence import EvidenceRecord
from coscientist.models.ontology import OntologyTerm
from coscientist.schemas.ontology import (
    OntologyCategoryEnum,
    RelationshipCreate,
    RelationshipTypeEnum,
    TermCreate,
    TermMergeRequest,
    TermUpdate,
)
from coscientist.services import ontology as svc


def _seed_term(db, name="beamforming", category="method", keywords=None):
    now = datetime.now(timezone.utc)
    term = OntologyTerm(
        id=str(uuid.uuid4()),
        canonical_name=name,
        category=category,
        description=f"Test term {name}",
        keywords=json.dumps(keywords or [name.replace("_", " ")]),
        status="active",
        created_at=now,
        updated_at=now,
    )
    db.add(term)
    db.commit()
    db.refresh(term)
    return term


def test_create_term(db_session):
    data = TermCreate(
        canonical_name="beamforming",
        category=OntologyCategoryEnum.method,
        description="Steers beams",
        keywords=["beamforming", "beam forming"],
    )
    result = svc.create_term(db_session, data)
    assert result.canonical_name == "beamforming"
    assert result.category == OntologyCategoryEnum.method
    assert result.status == "active"
    assert "beamforming" in result.keywords


def test_create_duplicate_term_rejected(db_session):
    _seed_term(db_session)
    data = TermCreate(
        canonical_name="beamforming",
        category=OntologyCategoryEnum.method,
    )
    with pytest.raises(Exception) as exc_info:
        svc.create_term(db_session, data)
    assert exc_info.value.status_code == 409


def test_get_term(db_session):
    term = _seed_term(db_session)
    result = svc.get_term(db_session, term.id)
    assert result.id == term.id
    assert result.canonical_name == "beamforming"


def test_get_term_not_found(db_session):
    with pytest.raises(Exception) as exc_info:
        svc.get_term(db_session, "nonexistent")
    assert exc_info.value.status_code == 404


def test_get_term_by_name(db_session):
    _seed_term(db_session)
    result = svc.get_term_by_name(db_session, OntologyCategoryEnum.method, "beamforming")
    assert result.canonical_name == "beamforming"


def test_list_terms(db_session):
    _seed_term(db_session, "beamforming", "method")
    _seed_term(db_session, "acc", "method")
    _seed_term(db_session, "latency_ms", "metric")
    items, total = svc.list_terms(db_session)
    assert total == 3


def test_list_terms_filter_category(db_session):
    _seed_term(db_session, "beamforming", "method")
    _seed_term(db_session, "latency_ms", "metric")
    items, total = svc.list_terms(db_session, category=OntologyCategoryEnum.method)
    assert total == 1
    assert items[0].canonical_name == "beamforming"


def test_update_term(db_session):
    term = _seed_term(db_session)
    result = svc.update_term(db_session, term.id, TermUpdate(description="Updated desc"))
    assert result.description == "Updated desc"


def test_update_term_duplicate_name_rejected(db_session):
    _seed_term(db_session, "beamforming", "method")
    term2 = _seed_term(db_session, "acc", "method")
    with pytest.raises(Exception) as exc_info:
        svc.update_term(db_session, term2.id, TermUpdate(canonical_name="beamforming"))
    assert exc_info.value.status_code == 409


def test_delete_active_term_rejected(db_session):
    term = _seed_term(db_session)
    with pytest.raises(Exception) as exc_info:
        svc.delete_term(db_session, term.id)
    assert exc_info.value.status_code == 409


def test_delete_deprecated_term(db_session):
    term = _seed_term(db_session)
    svc.update_term(db_session, term.id, TermUpdate(status="deprecated"))
    svc.delete_term(db_session, term.id)
    with pytest.raises(Exception) as exc_info:
        svc.get_term(db_session, term.id)
    assert exc_info.value.status_code == 404


def test_create_relationship(db_session):
    t1 = _seed_term(db_session, "beamforming", "method")
    t2 = _seed_term(db_session, "acc", "method")
    data = RelationshipCreate(
        source_term_id=t1.id,
        target_term_id=t2.id,
        relationship_type=RelationshipTypeEnum.related_to,
    )
    result = svc.create_relationship(db_session, data)
    assert result.source_term_id == t1.id
    assert result.target_term_id == t2.id


def test_get_related_terms(db_session):
    t1 = _seed_term(db_session, "beamforming", "method")
    t2 = _seed_term(db_session, "acc", "method")
    svc.create_relationship(
        db_session,
        RelationshipCreate(
            source_term_id=t1.id,
            target_term_id=t2.id,
            relationship_type=RelationshipTypeEnum.related_to,
        ),
    )
    related = svc.get_related_terms(db_session, t1.id)
    assert len(related) == 1
    assert related[0].id == t2.id


def test_delete_relationship(db_session):
    t1 = _seed_term(db_session, "beamforming", "method")
    t2 = _seed_term(db_session, "acc", "method")
    rel = svc.create_relationship(
        db_session,
        RelationshipCreate(
            source_term_id=t1.id,
            target_term_id=t2.id,
            relationship_type=RelationshipTypeEnum.related_to,
        ),
    )
    svc.delete_relationship(db_session, rel.id)
    related = svc.get_related_terms(db_session, t1.id)
    assert len(related) == 0


def test_merge_terms(db_session):
    t1 = _seed_term(db_session, "beam_forming", "method", keywords=["beam forming"])
    t2 = _seed_term(db_session, "beamforming", "method", keywords=["beamforming"])
    result = svc.merge_terms(
        db_session,
        TermMergeRequest(source_term_id=t1.id, target_term_id=t2.id),
    )
    assert "beam forming" in result.keywords
    assert "beamforming" in result.keywords
    source = svc.get_term(db_session, t1.id)
    assert source.status == "deprecated"


def test_merge_updates_evidence_records(db_session):
    t1 = _seed_term(db_session, "beam_forming", "method", keywords=["beam forming"])
    t2 = _seed_term(db_session, "beamforming", "method", keywords=["beamforming"])

    now = datetime.now(timezone.utc)
    rec = EvidenceRecord(
        id=str(uuid.uuid4()),
        workspace_id="ws1",
        scout_run_id="sr1",
        query_text="test",
        paper_id="p1",
        title="Test Paper",
        chunk_id="c1",
        chunk_index=0,
        chunk_text="test text",
        score=0.9,
        method_families=json.dumps(["beam_forming", "acc"]),
        is_primary_method=False,
        evidence_strength="none",
        created_at=now,
    )
    db_session.add(rec)
    db_session.commit()

    svc.merge_terms(
        db_session,
        TermMergeRequest(source_term_id=t1.id, target_term_id=t2.id),
    )
    db_session.refresh(rec)
    families = json.loads(rec.method_families)
    assert "beamforming" in families
    assert "beam_forming" not in families


def test_merge_cross_category_rejected(db_session):
    t1 = _seed_term(db_session, "beamforming", "method")
    t2 = _seed_term(db_session, "latency_ms", "metric")
    with pytest.raises(Exception) as exc_info:
        svc.merge_terms(
            db_session,
            TermMergeRequest(source_term_id=t1.id, target_term_id=t2.id),
        )
    assert exc_info.value.status_code == 422
