import anthropic

from coscientist.config import settings


def anthropic_client() -> anthropic.Anthropic:
    """Anthropic client configured for direct Anthropic or an Anthropic-compatible gateway.

    Mirrors the retrieval project's gateway pattern: `ANTHROPIC_API_KEY` may be a
    dummy value when `ANTHROPIC_BASE_URL` points at the gateway and auth is
    supplied via `ANTHROPIC_CUSTOM_HEADERS`/`LLM_GATEWAY_KEY`.
    """
    kwargs: dict = {"api_key": settings.anthropic_api_key}
    if settings.anthropic_base_url:
        kwargs["base_url"] = settings.anthropic_base_url
    headers = settings.anthropic_default_headers
    if headers:
        kwargs["default_headers"] = headers
    return anthropic.Anthropic(**kwargs)
