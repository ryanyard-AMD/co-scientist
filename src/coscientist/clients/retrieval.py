"""
httpx-based client for the retrieval API.
Modeled after ../experiment/src/repro/retrieval_client/client.py.
Active calls are added in the SCOUT epic; this stub wires settings and data contracts.
"""

from pydantic import BaseModel

import httpx

from coscientist.config import settings


class ChunkResult(BaseModel):
    chunk_id: str
    paper_id: str
    title: str
    text: str
    page_number: int
    chunk_index: int
    score: float


class QueryResponse(BaseModel):
    results: list[ChunkResult]
    total: int
    answer: str | None = None
    confidence: float | None = None


class EvidencePack(BaseModel):
    paper_id: str
    title: str
    year: int | None = None
    abstract: str | None = None
    query: str
    chunks: list[ChunkResult]
    answer: str | None = None
    confidence: float | None = None


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
        payload: dict = {"query": query, "top_k": top_k, "generate_answer": generate_answer}
        if paper_ids:
            payload["filters"] = {"paper_ids": paper_ids}
        resp = self._client.post("/api/v1/query", json=payload)
        resp.raise_for_status()
        return QueryResponse.model_validate(resp.json())

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

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
