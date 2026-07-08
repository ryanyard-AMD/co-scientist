import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

import coscientist.database as db_module
from coscientist.database import Base, get_db
from coscientist.main import app
from coscientist.models import approval, approach, critic, device, evidence, execution, experiment, feedback, governance, handoff, hypothesis, ontology, roadmap, score, synthesis, validation  # noqa: F401 — ensure tables created
from coscientist.clients.retrieval import (
    ArtifactResult,
    ChunkResult,
    ClaimResult,
    ClaimSearchResponse,
    ComparePaper,
    DocumentMetadata,
    PaperComparison,
    QueryResponse,
)


@pytest.fixture(scope="function")
def db_engine():
    # Use a named in-memory DB with URI so all connections share the same data
    engine = create_engine(
        "sqlite:///file::memory:?cache=shared&uri=true",
        connect_args={"check_same_thread": False, "uri": True},
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(db_engine):
    Session = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture(scope="function")
def client(db_engine, db_session):
    original_engine = db_module.engine
    db_module.engine = db_engine

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    db_module.engine = original_engine


GOAL_PAYLOAD = {
    "name": "PSZ Headphone",
    "description": "Personal sound zone for headphone form factor",
    "target_application": "personal_sound_zones",
    "success_criteria": [
        {"name": "acoustic_contrast", "operator": ">=", "target": 20.0, "unit": "dB"},
        {"name": "latency", "operator": "<=", "target": 10.0, "unit": "ms"},
    ],
    "device_constraints": {
        "speaker_count": 2,
        "form_factor": "headphone",
        "compute_budget": "low",
        "setup_time_minutes": 5,
    },
}


def make_chunk(
    chunk_id: str = "chunk_1",
    paper_id: str = "paper_1",
    title: str = "Acoustic Contrast Control for Personal Sound Zones",
    text: str = "Acoustic contrast control optimizes loudspeaker signals to maximize the acoustic energy difference between the bright zone and dark zone.",
    section_title: str | None = "Methods",
    page_number: int | None = 5,
    chunk_index: int = 0,
    score: float = 0.95,
) -> ChunkResult:
    return ChunkResult(
        chunk_id=chunk_id,
        paper_id=paper_id,
        title=title,
        text=text,
        section_title=section_title,
        page_number=page_number,
        chunk_index=chunk_index,
        score=score,
    )


def make_artifact(
    artifact_text_id: str = "art_text_1",
    artifact_id: str = "art_1",
    artifact_type: str = "table",
    paper_id: str = "paper_1",
    title: str = "Acoustic Contrast Control for Personal Sound Zones",
    text: str = "Table 2 reports acoustic contrast of 23 dB in the bright zone using acoustic contrast control across the measured frequency band.",
    section_title: str | None = "Results",
    page_number: int | None = 8,
    score: float = 0.9,
) -> ArtifactResult:
    return ArtifactResult(
        artifact_text_id=artifact_text_id,
        artifact_id=artifact_id,
        artifact_type=artifact_type,
        paper_id=paper_id,
        title=title,
        text=text,
        section_title=section_title,
        page_number=page_number,
        score=score,
    )


class MockRetrievalClient:
    def __init__(
        self,
        chunks: list[ChunkResult] | None = None,
        artifacts: list[ArtifactResult] | None = None,
        claims: list[ClaimResult] | None = None,
    ):
        self._artifacts = artifacts or []
        self._claims = claims or []
        self._chunks = chunks or [
            make_chunk(),
            make_chunk(
                chunk_id="chunk_2",
                paper_id="paper_2",
                title="Pressure Matching Sound Zones",
                text="Pressure matching minimizes reproduction error in the bright zone while maintaining dark zone attenuation.",
                score=0.88,
            ),
            make_chunk(
                chunk_id="chunk_3",
                paper_id="paper_1",
                title="Acoustic Contrast Control for Personal Sound Zones",
                text="Beamforming techniques can be combined with acoustic contrast control for improved robustness to head movement.",
                section_title="Discussion",
                page_number=12,
                chunk_index=3,
                score=0.82,
            ),
        ]

    def query_with_filters(self, query, **kwargs):
        return QueryResponse(
            results=self._chunks,
            total=len(self._chunks),
            artifact_results=self._artifacts,
        )

    def get_document(self, document_id):
        return DocumentMetadata(
            paper_id=document_id,
            title="Test Paper",
            original_filename="test.pdf",
            ingestion_status="embedded",
            year=2023,
        )

    def search_claims(self, query, **kwargs):
        return ClaimSearchResponse(
            query=query, claims=self._claims, total=len(self._claims)
        )

    def get_paper_entities(self, paper_id):
        return {}

    def get_method_entity(self, name):
        return {}

    def list_topic_clusters(self, **kwargs):
        return []

    def compare_papers(self, paper_ids, *, dimensions=None, **kwargs):
        dims = dimensions or ["problem", "methods", "results", "limitations"]
        return PaperComparison(
            papers=[ComparePaper(paper_id=pid, title=f"Paper {pid}") for pid in paper_ids],
            dimensions={d: {pid: f"{d} of {pid}" for pid in paper_ids} for d in dims},
            summary="mock comparison summary",
            cited_chunk_ids=[],
            chunks_used=len(paper_ids),
        )

    def close(self):
        pass
