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
