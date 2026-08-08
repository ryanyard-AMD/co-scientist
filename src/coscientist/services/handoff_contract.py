"""Shared helpers for the co-scientist -> Experimentation System contract."""

from coscientist.config import settings


def public_base_url() -> str:
    """External base URL runners can use to call back into co-scientist."""
    return (settings.public_base_url or f"http://localhost:{settings.port}").rstrip("/")


def result_bundle_endpoint() -> str:
    """Absolute ResultBundle ingestion URL included in RunRequest handoffs."""
    prefix = settings.api_prefix.rstrip("/")
    return f"{public_base_url()}{prefix}/result-bundles"
