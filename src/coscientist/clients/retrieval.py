"""
httpx-based client for the retrieval API.
Modeled after ../experiment/src/repro/retrieval_client/client.py.
"""

from __future__ import annotations

import httpx
from pydantic import BaseModel

from coscientist.config import settings


class MetadataFilter(BaseModel):
    paper_ids: list[str] | None = None
    authors: list[str] | None = None
    year_min: int | None = None
    year_max: int | None = None
    source_ids: list[str] | None = None
    source_types: list[str] | None = None
    source_collection: str | None = None
    source_tag: str | None = None


class ChunkResult(BaseModel):
    chunk_id: str
    paper_id: str
    title: str
    text: str
    section_title: str | None = None
    page_number: int | None = None
    chunk_index: int
    score: float
    vector_score: float | None = None
    fulltext_score: float | None = None
    source_id: str | None = None
    source_type: str | None = None


class ArtifactResult(BaseModel):
    artifact_text_id: str
    artifact_id: str
    artifact_type: str
    paper_id: str
    title: str
    text: str
    representation_type: str | None = None
    page_number: int | None = None
    section_title: str | None = None
    file_uri: str | None = None
    thumbnail_uri: str | None = None
    score: float = 0.0
    vector_score: float | None = None
    fulltext_score: float | None = None


class QueryResponse(BaseModel):
    results: list[ChunkResult]
    total: int
    answer: str | None = None
    confidence: float | None = None
    artifact_results: list[ArtifactResult] = []


class ClaimRelationship(BaseModel):
    relation: str  # SUPPORTS | CONTRADICTS | EXTENDS
    target_claim_id: str
    rationale: str = ""


class ClaimResult(BaseModel):
    claim_id: str
    text: str
    claim_type: str  # finding | hypothesis | contribution | limitation
    paper_id: str
    title: str | None = None
    chunk_ids: list[str] = []
    confidence: float | None = None
    score: float = 0.0
    vector_score: float | None = None
    fulltext_score: float | None = None
    relationships: list[ClaimRelationship] = []


class ClaimSearchResponse(BaseModel):
    query: str
    claims: list[ClaimResult] = []
    total: int = 0


class EvidencePack(BaseModel):
    paper_id: str
    title: str
    year: int | None = None
    abstract: str | None = None
    query: str
    chunks: list[ChunkResult]
    answer: str | None = None
    confidence: float | None = None


class DocumentMetadata(BaseModel):
    paper_id: str
    title: str
    original_filename: str
    ingestion_status: str
    abstract: str | None = None
    year: int | None = None
    source_id: str | None = None
    source_type: str | None = None


class RetrievalClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 30.0,
    ):
        self._base_url = (base_url or settings.retrieval_url).rstrip("/")
        self._api_key = api_key or settings.retrieval_api_key
        headers = {}
        if self._api_key:
            headers["X-Api-Key"] = self._api_key
        self._client = httpx.Client(
            base_url=self._base_url,
            headers=headers,
            timeout=timeout,
        )

    def query(
        self,
        query: str,
        *,
        top_k: int = 10,
        paper_ids: list[str] | None = None,
        generate_answer: bool = False,
    ) -> QueryResponse:
        filters = MetadataFilter(paper_ids=paper_ids) if paper_ids else None
        return self.query_with_filters(
            query, top_k=top_k, filters=filters, generate_answer=generate_answer,
        )

    def query_with_filters(
        self,
        query: str,
        *,
        top_k: int = 20,
        filters: MetadataFilter | None = None,
        expand_graph: bool = True,
        rerank: bool = True,
        generate_answer: bool = False,
    ) -> QueryResponse:
        payload: dict = {
            "query": query,
            "top_k": top_k,
            "expand_graph": expand_graph,
            "rerank": rerank,
            "generate_answer": generate_answer,
        }
        if filters:
            filter_dict = filters.model_dump(exclude_none=True)
            if filter_dict:
                payload["filters"] = filter_dict
        resp = self._client.post("/api/v1/query", json=payload)
        resp.raise_for_status()
        return QueryResponse.model_validate(resp.json())

    def search_claims(
        self,
        query: str,
        *,
        top_k: int = 25,
        filters: MetadataFilter | None = None,
    ) -> ClaimSearchResponse:
        """Query-time claim retrieval across the corpus.

        Returns typed claims (finding/hypothesis/contribution/limitation) grounded
        to chunk_ids, each with SUPPORTS/CONTRADICTS/EXTENDS edges to other claims.
        """
        payload: dict = {"query": query, "top_k": top_k}
        if filters:
            filter_dict = filters.model_dump(exclude_none=True)
            if filter_dict:
                payload["filters"] = filter_dict
        resp = self._client.post("/api/v1/claims/search", json=payload)
        resp.raise_for_status()
        return ClaimSearchResponse.model_validate(resp.json())

    def get_evidence_pack(
        self,
        paper_id: str,
        query: str,
        *,
        top_k: int = 20,
        generate_answer: bool = True,
    ) -> EvidencePack:
        qr = self.query(
            query,
            top_k=top_k,
            paper_ids=[paper_id],
            generate_answer=generate_answer,
        )
        chunks = [c for c in qr.results if c.paper_id == paper_id]
        title = chunks[0].title if chunks else ""
        return EvidencePack(
            paper_id=paper_id,
            title=title,
            query=query,
            chunks=chunks,
            answer=qr.answer,
            confidence=qr.confidence,
        )

    def get_document(self, document_id: str) -> DocumentMetadata:
        resp = self._client.get(f"/api/v1/documents/{document_id}")
        resp.raise_for_status()
        return DocumentMetadata.model_validate(resp.json())

    def get_paper_entities(self, paper_id: str) -> dict:
        resp = self._client.get(f"/api/v1/entities/papers/{paper_id}")
        resp.raise_for_status()
        return resp.json()

    def get_method_entity(self, name: str) -> dict:
        """Method entity node: {name, description, category, entity_type, papers}."""
        resp = self._client.get(f"/api/v1/entities/methods/{name}")
        resp.raise_for_status()
        return resp.json()

    def list_topic_clusters(self, *, k: int = 8, timeout: float | None = None) -> list[dict]:
        """k-means embedding clusters over the whole corpus (noisy, whole-corpus).

        This endpoint recomputes clusters on demand and can be slow, so callers
        pass a bounded timeout and treat failures as "no hint".
        """
        resp = self._client.get(
            "/api/v1/advanced/topics/clusters", params={"k": k}, timeout=timeout
        )
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
