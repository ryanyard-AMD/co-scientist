from unittest.mock import patch

from coscientist.config import settings
from coscientist.llm import anthropic_client


def test_anthropic_client_passes_gateway_base_url_and_headers(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "dummy")
    monkeypatch.setattr(settings, "anthropic_base_url", "https://llm-api.example.com/Anthropic")
    monkeypatch.setattr(
        settings,
        "anthropic_custom_headers",
        "Ocp-Apim-Subscription-Key: gateway-key\nX-Test: yes",
    )
    monkeypatch.setattr(settings, "llm_gateway_key", "")

    with patch("coscientist.llm.anthropic.Anthropic") as client_cls:
        anthropic_client()

    assert client_cls.call_args.kwargs == {
        "api_key": "dummy",
        "base_url": "https://llm-api.example.com/Anthropic",
        "default_headers": {
            "Ocp-Apim-Subscription-Key": "gateway-key",
            "X-Test": "yes",
        },
    }


def test_anthropic_default_headers_uses_gateway_key_when_custom_header_absent(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_custom_headers", "")
    monkeypatch.setattr(settings, "llm_gateway_key", "gateway-key")

    assert settings.anthropic_default_headers == {
        "Ocp-Apim-Subscription-Key": "gateway-key"
    }
