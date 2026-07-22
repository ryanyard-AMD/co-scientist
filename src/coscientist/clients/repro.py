"""
httpx-based client for the repro experiment-runner API (default :8003).
Mirrors the RetrievalClient pattern.
"""

from __future__ import annotations

import httpx

from coscientist.config import settings


class ReproClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 30.0,
    ):
        self._base_url = (base_url or settings.repro_url).rstrip("/")
        self._api_key = api_key or settings.repro_api_key
        headers = {}
        if self._api_key:
            headers["x-api-key"] = self._api_key
        self._client = httpx.Client(
            base_url=self._base_url,
            headers=headers,
            timeout=timeout,
        )

    def submit_run(self, spec: dict, *, unsafe_draft: bool = False) -> dict:
        """POST a spec to /api/v1/runs → {run_id, status, poll}."""
        resp = self._client.post(
            "/api/v1/runs",
            json={"spec": spec, "unsafe_draft": unsafe_draft},
        )
        resp.raise_for_status()
        return resp.json()

    def list_workspaces(self) -> list[dict]:
        """GET /api/v1/workspaces → list of Workspace dicts (id, retrieval_paper_id, ...)."""
        resp = self._client.get("/api/v1/workspaces")
        resp.raise_for_status()
        return resp.json()

    def design_run(
        self,
        workspace_id: str,
        proposal: dict,
        *,
        auto_approve: bool = True,
    ) -> dict:
        """POST /api/v1/workspaces/{id}/design-run — ground a proposal in the
        workspace paper's curated spec and run it in one call (handoff P3).

        Returns ``{run_id, draft_id, spec_status, honored, dropped, quality?}``.
        """
        resp = self._client.post(
            f"/api/v1/workspaces/{workspace_id}/design-run",
            params={"auto_approve": auto_approve},
            json=proposal,
        )
        resp.raise_for_status()
        return resp.json()

    def recommend_method(
        self,
        workspace_id: str,
        proposal: dict,
        *,
        top_k: int | None = None,
        draft: bool = False,
    ) -> dict:
        """POST /api/v1/workspaces/{id}/recommend-method — rank candidate
        reproductions for a proposal's hypothesis (handoff P4).

        Corpus-wide retrieval, not scoped to the workspace paper. Returns a
        ``RecommendationResult``: ``{hypothesis, candidates[], draft_id,
        drafted_experiment_id, honored, dropped, method_family_supported}`` where
        each candidate carries ``{paper_id, title, score, rationale, runnable,
        experiment_ids, method_families, family_match}``. Never executes a run
        (no ``run_id``). ``draft`` defaults False — the runner drives its own
        design-run and doesn't need repro's convenience draft.
        """
        params: dict = {"draft": draft}
        if top_k is not None:
            params["top_k"] = top_k
        resp = self._client.post(
            f"/api/v1/workspaces/{workspace_id}/recommend-method",
            params=params,
            json=proposal,
        )
        resp.raise_for_status()
        return resp.json()

    def get_metrics_surface(self, workspace_id: str) -> dict:
        """GET /api/v1/workspaces/{id}/metrics-surface — the metrics each
        registered reproduction of the workspace paper validates (handoff P4c).

        Returns ``{paper_id, reproductions:[{experiment_id, method_families,
        metrics[]}]}``. ``reproductions`` is empty (still 200) when the paper has
        no registered reproduction.
        """
        resp = self._client.get(f"/api/v1/workspaces/{workspace_id}/metrics-surface")
        resp.raise_for_status()
        return resp.json()

    def get_run(self, run_id: str) -> dict:
        """GET /api/v1/runs/{run_id} → RunMetadata dict."""
        resp = self._client.get(f"/api/v1/runs/{run_id}")
        resp.raise_for_status()
        return resp.json()

    def get_run_metrics(self, run_id: str) -> dict:
        """GET /api/v1/reports/runs/{run_id}/metrics → raw metrics.json dict."""
        resp = self._client.get(f"/api/v1/reports/runs/{run_id}/metrics")
        resp.raise_for_status()
        return resp.json()

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
