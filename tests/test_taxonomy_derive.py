from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from coscientist.config import settings
from coscientist.clients.retrieval import QueryResponse
from coscientist.models.ontology import OntologyRelationship, OntologyTerm
from coscientist.schemas.goal import GoalCreate, SuccessCriterion
from coscientist.schemas.taxonomy import AgentTaxonomyOutput, InducedFamily
from coscientist.services import goal as goal_svc
from coscientist.services import ontology as ontology_svc
from coscientist.services import scout as scout_svc
from coscientist.services import taxonomy as taxonomy_svc
from conftest import MockRetrievalClient

_CRITERIA = [SuccessCriterion(name="acoustic_contrast", operator=">=", target=15.0, unit="dB")]


def _create_goal(db, name="PSZ PAL Test"):
    return goal_svc.create(
        db,
        GoalCreate(
            name=name,
            description="Spherical microphone array with a parametric array loudspeaker.",
            target_application="personal_sound_zone",
            success_criteria=_CRITERIA,
        ),
    )


def _fake_induce(*families):
    def _inner(db, goal, chunks, max_families, pinned=None, **kwargs):
        return AgentTaxonomyOutput(families=list(families))
    return _inner


_PAL = InducedFamily(
    canonical_name="parametric_array_loudspeaker",
    description="Ultrasonic self-demodulating directional loudspeaker.",
    keywords=["parametric array", "ultrasonic"],
    related_to=["spherical_microphone_array"],
)
_SPH = InducedFamily(
    canonical_name="spherical_microphone_array",
    description="Rigid spherical array for sound-field sensing.",
    keywords=["spherical microphone array", "spherical harmonics"],
    related_to=["parametric_array_loudspeaker"],
)


def _method_terms(db, workspace_id):
    return db.query(OntologyTerm).filter(
        OntologyTerm.category == "method",
        OntologyTerm.workspace_id == workspace_id,
    ).all()


def _global_method_count(db):
    return db.query(OntologyTerm).filter(
        OntologyTerm.category == "method",
        OntologyTerm.workspace_id.is_(None),
    ).count()


def test_derive_persists_goal_scoped_methods(db_session):
    ontology_svc.seed_default_ontology(db_session)
    goal = _create_goal(db_session)
    mock = MockRetrievalClient()
    with patch.object(taxonomy_svc, "_induce_taxonomy", _fake_induce(_PAL, _SPH)):
        result = taxonomy_svc.derive_taxonomy(db_session, goal.id, retrieval_client=mock)

    assert result.dry_run is False
    assert result.terms_created == 2
    assert result.relationships_created == 2  # bidirectional related_to
    scoped = _method_terms(db_session, goal.workspace_id)
    names = {t.canonical_name for t in scoped}
    assert names == {"parametric_array_loudspeaker", "spherical_microphone_array"}
    assert all(t.workspace_id == goal.workspace_id for t in scoped)
    # Global seed untouched.
    assert _global_method_count(db_session) == 7


def test_derive_dry_run_persists_nothing(db_session):
    ontology_svc.seed_default_ontology(db_session)
    goal = _create_goal(db_session)
    mock = MockRetrievalClient()
    with patch.object(taxonomy_svc, "_induce_taxonomy", _fake_induce(_PAL, _SPH)):
        result = taxonomy_svc.derive_taxonomy(
            db_session, goal.id, dry_run=True, retrieval_client=mock
        )
    assert result.dry_run is True
    assert result.terms_created == 0
    assert len(result.families) == 2
    assert _method_terms(db_session, goal.workspace_id) == []


def test_derive_idempotent_replaces_prior_goal_terms(db_session):
    ontology_svc.seed_default_ontology(db_session)
    goal = _create_goal(db_session)
    mock = MockRetrievalClient()
    with patch.object(taxonomy_svc, "_induce_taxonomy", _fake_induce(_PAL, _SPH)):
        taxonomy_svc.derive_taxonomy(db_session, goal.id, retrieval_client=mock)

    other = InducedFamily(canonical_name="wave_field_synthesis", keywords=["wave field synthesis"])
    with patch.object(taxonomy_svc, "_induce_taxonomy", _fake_induce(other)):
        result = taxonomy_svc.derive_taxonomy(db_session, goal.id, retrieval_client=mock)

    assert result.terms_created == 1
    scoped = _method_terms(db_session, goal.workspace_id)
    assert {t.canonical_name for t in scoped} == {"wave_field_synthesis"}
    # Old goal-scoped relationships cleaned up (new family has no related_to);
    # global seed relationships remain untouched.
    scoped_ids = {t.id for t in scoped}
    rels = db_session.query(OntologyRelationship).all()
    assert not any(
        r.source_term_id in scoped_ids or r.target_term_id in scoped_ids for r in rels
    )
    assert _global_method_count(db_session) == 7


def test_load_ontology_terms_goal_override(db_session):
    ontology_svc.seed_default_ontology(db_session)
    goal = _create_goal(db_session)
    mock = MockRetrievalClient()
    with patch.object(taxonomy_svc, "_induce_taxonomy", _fake_induce(_PAL, _SPH)):
        taxonomy_svc.derive_taxonomy(db_session, goal.id, retrieval_client=mock)

    all_terms, method_terms, _ = scout_svc._load_ontology_terms(db_session, goal.workspace_id)
    method_names = {t.canonical_name for t in method_terms}
    # Methods = derived (global 7 dropped); other categories stay global.
    assert method_names == {"parametric_array_loudspeaker", "spherical_microphone_array"}
    categories = {t.category for t in all_terms}
    assert {"metric", "hardware", "failure_mode"} <= categories
    assert any(t.category == "metric" and t.workspace_id is None for t in all_terms)


def test_load_ontology_terms_no_scope_uses_global(db_session):
    ontology_svc.seed_default_ontology(db_session)
    goal = _create_goal(db_session)  # no derived taxonomy
    _, method_terms, _ = scout_svc._load_ontology_terms(db_session, goal.workspace_id)
    assert len(method_terms) == 7
    assert all(t.workspace_id is None for t in method_terms)


def test_derive_no_chunks_raises(db_session):
    ontology_svc.seed_default_ontology(db_session)
    goal = _create_goal(db_session)

    class _EmptyClient(MockRetrievalClient):
        def query_with_filters(self, query, **kwargs):
            return QueryResponse(results=[], total=0, artifact_results=[])

    with pytest.raises(HTTPException) as exc:
        taxonomy_svc.derive_taxonomy(db_session, goal.id, retrieval_client=_EmptyClient())
    assert exc.value.status_code == 422


def _create_goal_pinned(db, pins, name="PSZ PAL Pinned"):
    return goal_svc.create(
        db,
        GoalCreate(
            name=name,
            description="Spherical microphone array with a parametric array loudspeaker.",
            target_application="personal_sound_zone",
            success_criteria=_CRITERIA,
            pinned_method_families=pins,
        ),
    )


def test_goal_pins_canonicalized_round_trip(db_session):
    goal = _create_goal_pinned(db_session, ["Parametric Array Loudspeaker", "spherical_microphone_array"])
    assert goal.pinned_method_families == [
        "parametric_array_loudspeaker",
        "spherical_microphone_array",
    ]
    reloaded = goal_svc.get(db_session, goal.id)
    assert reloaded.pinned_method_families == goal.pinned_method_families


def test_derive_injects_pinned_family_agent_omitted(db_session):
    ontology_svc.seed_default_ontology(db_session)
    goal = _create_goal_pinned(db_session, ["parametric_array_loudspeaker"])
    mock = MockRetrievalClient()
    # Agent returns a family set that does NOT include the pinned technology.
    with patch.object(taxonomy_svc, "_induce_taxonomy", _fake_induce(_SPH)):
        result = taxonomy_svc.derive_taxonomy(db_session, goal.id, retrieval_client=mock)
    names = {t.canonical_name for t in _method_terms(db_session, goal.workspace_id)}
    assert "parametric_array_loudspeaker" in names
    assert "spherical_microphone_array" in names
    # Pinned family is listed first in the result.
    assert result.families[0].canonical_name == "parametric_array_loudspeaker"


def test_derive_pin_override_supplements_goal_pins(db_session):
    ontology_svc.seed_default_ontology(db_session)
    goal = _create_goal_pinned(db_session, ["spherical_microphone_array"])
    mock = MockRetrievalClient()
    with patch.object(taxonomy_svc, "_induce_taxonomy", _fake_induce(_PAL)):
        taxonomy_svc.derive_taxonomy(
            db_session, goal.id, pinned=["parametric_array_loudspeaker"], retrieval_client=mock
        )
    names = {t.canonical_name for t in _method_terms(db_session, goal.workspace_id)}
    assert {"parametric_array_loudspeaker", "spherical_microphone_array"} <= names
    # Ad-hoc --pin families must persist to the goal (merged with existing pins),
    # so a later re-derive still honors them.
    reloaded = goal_svc.get(db_session, goal.id)
    assert set(reloaded.pinned_method_families) == {
        "parametric_array_loudspeaker",
        "spherical_microphone_array",
    }


def test_derive_dry_run_does_not_persist_goal_pins(db_session):
    ontology_svc.seed_default_ontology(db_session)
    goal = _create_goal_pinned(db_session, ["spherical_microphone_array"])
    mock = MockRetrievalClient()
    with patch.object(taxonomy_svc, "_induce_taxonomy", _fake_induce(_PAL)):
        taxonomy_svc.derive_taxonomy(
            db_session, goal.id, pinned=["parametric_array_loudspeaker"],
            dry_run=True, retrieval_client=mock,
        )
    reloaded = goal_svc.get(db_session, goal.id)
    assert reloaded.pinned_method_families == ["spherical_microphone_array"]


def _fake_anthropic_capture(captured):
    """Fake anthropic.Anthropic whose messages.create records the system prompt."""
    tool_use = SimpleNamespace(type="tool_use", input={
        "families": [{"canonical_name": "acoustic_contrast_control",
                      "keywords": ["acoustic contrast"]}],
    })
    message = SimpleNamespace(
        content=[tool_use],
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )

    class _Messages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return message

    class _Client:
        def __init__(self, **kwargs):
            self.messages = _Messages()

    return _Client


class _MethodNodeClient(MockRetrievalClient):
    def get_paper_entities(self, paper_id):
        if paper_id == "paper_1":
            return {"methods": [
                {"name": "Acoustic Contrast Control", "category": "audio"},
                {"name": "Beamforming", "category": "audio"},
            ]}
        return {}


def test_method_node_hints_injected_into_prompt(db_session, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    goal = _create_goal(db_session)
    captured: dict = {}
    with patch.object(taxonomy_svc.anthropic, "Anthropic", _fake_anthropic_capture(captured)):
        taxonomy_svc.derive_taxonomy(
            db_session, goal.id, dry_run=True, retrieval_client=_MethodNodeClient()
        )
    system = captured["system"]
    assert "METHOD entity nodes" in system
    assert "Acoustic Contrast Control" in system
    assert "Beamforming" in system


def test_no_method_hints_when_entities_empty(db_session, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    goal = _create_goal(db_session)
    captured: dict = {}
    # Default mock's get_paper_entities returns {} → no method nodes to ground on.
    with patch.object(taxonomy_svc.anthropic, "Anthropic", _fake_anthropic_capture(captured)):
        taxonomy_svc.derive_taxonomy(
            db_session, goal.id, dry_run=True, retrieval_client=MockRetrievalClient()
        )
    assert "METHOD entity nodes" not in captured["system"]


def test_topic_clusters_gated_off_by_default(db_session, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    goal = _create_goal(db_session)
    called = {"clusters": False}

    class _ClusterClient(MockRetrievalClient):
        def list_topic_clusters(self, **kwargs):
            called["clusters"] = True
            return [{"terms": ["a", "b"]}]

    captured: dict = {}
    with patch.object(taxonomy_svc.anthropic, "Anthropic", _fake_anthropic_capture(captured)):
        taxonomy_svc.derive_taxonomy(
            db_session, goal.id, dry_run=True, retrieval_client=_ClusterClient()
        )
    assert called["clusters"] is False
    assert "topic clusters" not in captured["system"]


def test_topic_clusters_injected_when_enabled(db_session, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(settings, "taxonomy_use_topic_clusters", True)
    goal = _create_goal(db_session)

    class _ClusterClient(MockRetrievalClient):
        def list_topic_clusters(self, **kwargs):
            return [{"terms": ["contrast", "bright zone", "dark zone"]}]

    captured: dict = {}
    with patch.object(taxonomy_svc.anthropic, "Anthropic", _fake_anthropic_capture(captured)):
        taxonomy_svc.derive_taxonomy(
            db_session, goal.id, dry_run=True, retrieval_client=_ClusterClient()
        )
    system = captured["system"]
    assert "topic clusters" in system
    assert "contrast, bright zone, dark zone" in system


def test_cluster_failure_degrades_gracefully(db_session, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(settings, "taxonomy_use_topic_clusters", True)
    goal = _create_goal(db_session)

    class _BoomClient(MockRetrievalClient):
        def list_topic_clusters(self, **kwargs):
            raise RuntimeError("cluster endpoint timed out")

    captured: dict = {}
    with patch.object(taxonomy_svc.anthropic, "Anthropic", _fake_anthropic_capture(captured)):
        result = taxonomy_svc.derive_taxonomy(
            db_session, goal.id, dry_run=True, retrieval_client=_BoomClient()
        )
    # A failed cluster fetch must not break derivation nor add a cluster hint.
    assert result.dry_run is True
    assert "topic clusters" not in captured["system"]


def test_normalize_pins_survive_truncation(db_session):
    raw = [InducedFamily(canonical_name=f"corpus_family_{i}", keywords=[f"kw{i}"]) for i in range(5)]
    families = taxonomy_svc._normalize_families(
        raw, max_families=3, pinned=["parametric_array_loudspeaker"]
    )
    names = [f.canonical_name for f in families]
    assert len(families) == 3
    assert names[0] == "parametric_array_loudspeaker"
    # Only 2 corpus families fit alongside the pin.
    assert sum(1 for n in names if n.startswith("corpus_family_")) == 2
