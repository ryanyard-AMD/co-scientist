"""Phase 3: per-paper Method/Metric entity nodes augment record classification."""
import json

from coscientist.config import settings
from coscientist.models.evidence import EvidenceRecord
from coscientist.schemas.goal import GoalCreate, SuccessCriterion
from coscientist.schemas.scout import ScoutRunRequest
from coscientist.services import goal as goal_svc
from coscientist.services import ontology as ontology_svc
from coscientist.services import scout as scout_svc
from conftest import MockRetrievalClient, make_chunk, seed_goal_method_taxonomy

_CRITERIA = [SuccessCriterion(name="acoustic_contrast", operator=">=", target=20.0, unit="dB")]


def _create_goal(db, name="PSZ Entities Test"):
    goal = goal_svc.create(
        db,
        GoalCreate(
            name=name,
            target_application="personal_sound_zones",
            success_criteria=_CRITERIA,
        ),
    )
    seed_goal_method_taxonomy(db, goal.workspace_id)
    return goal


class _EntityClient(MockRetrievalClient):
    """Returns a chunk whose prose does NOT name pressure matching, but whose
    paper's entity nodes do — so entity augmentation is the only way the record
    can pick up the pressure_matching family and the reproduction-error metric."""

    def __init__(self):
        super().__init__(chunks=[make_chunk(
            chunk_id="c1", paper_id="paper_x",
            title="Sound Zone Results",
            text="The system was evaluated in the bright zone and dark zone across the band.",
        )], artifacts=[])

    def get_paper_entities(self, paper_id):
        if paper_id == "paper_x":
            return {
                "methods": [
                    {"name": "Pressure Matching Approach", "category": "optimization"},
                    {"name": "Least Squares", "category": "optimization"},
                ],
                "metrics": [
                    {"name": "Acoustic Contrast", "value": None},
                    {"name": "Reproduction Error", "value": None},
                ],
            }
        return {}


def test_entities_augment_method_families_and_metrics(db_session):
    ontology_svc.seed_default_ontology(db_session)
    goal = _create_goal(db_session)
    scout_svc.run_scout(db_session, goal.id, ScoutRunRequest(), retrieval_client=_EntityClient())

    rec = db_session.query(EvidenceRecord).filter(
        EvidenceRecord.paper_id == "paper_x"
    ).first()
    assert rec is not None
    families = json.loads(rec.method_families)
    metrics = json.loads(rec.metric_names)
    # "Pressure Matching Approach" node → pressure_matching canonical family,
    # even though the chunk prose never mentions it.
    assert "pressure_matching" in families
    # "Least Squares" maps to no canonical family → silently dropped.
    assert "least_squares" not in families
    # Metric nodes map into canonical metric names ("Acoustic Contrast" node →
    # acoustic_contrast_db keyword; "Reproduction Error" → bright_zone_error).
    assert "acoustic_contrast_db" in metrics
    assert "bright_zone_error" in metrics


def test_entities_additive_keyword_match_preserved(db_session):
    """A family the chunk prose DOES name must survive entity augmentation."""
    ontology_svc.seed_default_ontology(db_session)
    goal = _create_goal(db_session)

    class _Client(_EntityClient):
        def __init__(self):
            MockRetrievalClient.__init__(self, chunks=[make_chunk(
                chunk_id="c2", paper_id="paper_x",
                title="ACC paper",
                text="Acoustic contrast control maximizes the bright-zone to dark-zone energy ratio.",
            )], artifacts=[])

    scout_svc.run_scout(db_session, goal.id, ScoutRunRequest(), retrieval_client=_Client())
    rec = db_session.query(EvidenceRecord).filter(
        EvidenceRecord.paper_id == "paper_x"
    ).first()
    families = json.loads(rec.method_families)
    # Keyword match from prose kept AND entity-derived family added.
    assert "acoustic_contrast_control" in families
    assert "pressure_matching" in families


def test_entities_disabled_no_augmentation(db_session, monkeypatch):
    monkeypatch.setattr(settings, "scout_use_entities", False)
    ontology_svc.seed_default_ontology(db_session)
    goal = _create_goal(db_session)
    scout_svc.run_scout(db_session, goal.id, ScoutRunRequest(), retrieval_client=_EntityClient())

    rec = db_session.query(EvidenceRecord).filter(
        EvidenceRecord.paper_id == "paper_x"
    ).first()
    families = json.loads(rec.method_families)
    # With entities off, the entity-only family is absent.
    assert "pressure_matching" not in families


def test_entities_absent_falls_back_to_keywords(db_session):
    """Default mock returns {} for entities → records keep classify_text output."""
    ontology_svc.seed_default_ontology(db_session)
    goal = _create_goal(db_session)
    scout_svc.run_scout(db_session, goal.id, ScoutRunRequest(), retrieval_client=MockRetrievalClient())

    recs = db_session.query(EvidenceRecord).all()
    assert recs  # ran without error; enrichment was a no-op
