import json
import uuid
from datetime import datetime, timezone

import pytest

from coscientist.models.ontology import OntologyTerm


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


def test_create_term(client, db_session):
    resp = client.post("/co-scientist/ontology/terms", json={
        "canonical_name": "beamforming",
        "category": "method",
        "description": "Steers beams",
        "keywords": ["beamforming", "beam forming"],
    })
    assert resp.status_code == 201
    body = resp.json()
    assert body["canonical_name"] == "beamforming"
    assert body["status"] == "active"


def test_create_duplicate_returns_409(client, db_session):
    _seed_term(db_session)
    resp = client.post("/co-scientist/ontology/terms", json={
        "canonical_name": "beamforming",
        "category": "method",
    })
    assert resp.status_code == 409


def test_list_terms(client, db_session):
    _seed_term(db_session, "beamforming", "method")
    _seed_term(db_session, "latency_ms", "metric")
    resp = client.get("/co-scientist/ontology/terms")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2


def test_list_terms_filter_category(client, db_session):
    _seed_term(db_session, "beamforming", "method")
    _seed_term(db_session, "latency_ms", "metric")
    resp = client.get("/co-scientist/ontology/terms?category=method")
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["canonical_name"] == "beamforming"


def test_get_term(client, db_session):
    term = _seed_term(db_session)
    resp = client.get(f"/co-scientist/ontology/terms/{term.id}")
    assert resp.status_code == 200
    assert resp.json()["canonical_name"] == "beamforming"


def test_get_term_not_found(client):
    resp = client.get("/co-scientist/ontology/terms/nonexistent")
    assert resp.status_code == 404


def test_patch_term(client, db_session):
    term = _seed_term(db_session)
    resp = client.patch(f"/co-scientist/ontology/terms/{term.id}", json={
        "description": "Updated description",
    })
    assert resp.status_code == 200
    assert resp.json()["description"] == "Updated description"


def test_delete_active_term_returns_409(client, db_session):
    term = _seed_term(db_session)
    resp = client.delete(f"/co-scientist/ontology/terms/{term.id}")
    assert resp.status_code == 409


def test_delete_deprecated_term(client, db_session):
    term = _seed_term(db_session)
    client.patch(f"/co-scientist/ontology/terms/{term.id}", json={"status": "deprecated"})
    resp = client.delete(f"/co-scientist/ontology/terms/{term.id}")
    assert resp.status_code == 204


def test_merge_terms(client, db_session):
    t1 = _seed_term(db_session, "beam_forming", "method", ["beam forming"])
    t2 = _seed_term(db_session, "beamforming", "method", ["beamforming"])
    resp = client.post("/co-scientist/ontology/terms/merge", json={
        "source_term_id": t1.id,
        "target_term_id": t2.id,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert "beam forming" in body["keywords"]
    assert "beamforming" in body["keywords"]


def test_create_relationship(client, db_session):
    t1 = _seed_term(db_session, "beamforming", "method")
    t2 = _seed_term(db_session, "acc", "method")
    resp = client.post("/co-scientist/ontology/relationships", json={
        "source_term_id": t1.id,
        "target_term_id": t2.id,
        "relationship_type": "related_to",
    })
    assert resp.status_code == 201
    assert resp.json()["source_term_id"] == t1.id


def test_delete_relationship(client, db_session):
    t1 = _seed_term(db_session, "beamforming", "method")
    t2 = _seed_term(db_session, "acc", "method")
    rel = client.post("/co-scientist/ontology/relationships", json={
        "source_term_id": t1.id,
        "target_term_id": t2.id,
        "relationship_type": "related_to",
    }).json()
    resp = client.delete(f"/co-scientist/ontology/relationships/{rel['id']}")
    assert resp.status_code == 204


def test_get_related_terms(client, db_session):
    t1 = _seed_term(db_session, "beamforming", "method")
    t2 = _seed_term(db_session, "acc", "method")
    client.post("/co-scientist/ontology/relationships", json={
        "source_term_id": t1.id,
        "target_term_id": t2.id,
        "relationship_type": "related_to",
    })
    resp = client.get(f"/co-scientist/ontology/terms/{t1.id}/related")
    assert resp.status_code == 200
    related = resp.json()
    assert len(related) == 1
    assert related[0]["canonical_name"] == "acc"
