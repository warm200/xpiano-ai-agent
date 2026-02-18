from __future__ import annotations

from types import SimpleNamespace

import pytest

from xpiano.llm_provider import ClaudeProvider, create_provider


def test_create_provider_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        create_provider({"llm": {"provider": "unknown"}})


def test_claude_provider_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError):
        ClaudeProvider(api_key=None, api_key_env="ANTHROPIC_API_KEY")


def test_claude_provider_generate(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeMessages:
        def create(self, **kwargs):
            _ = kwargs
            return SimpleNamespace(content=[SimpleNamespace(text='{"goal":"ok"}')])

    class FakeClient:
        def __init__(self, api_key: str):
            _ = api_key
            self.messages = FakeMessages()

    monkeypatch.setattr("xpiano.llm_provider.anthropic.Anthropic", FakeClient)
    provider = ClaudeProvider(api_key="test-key")
    assert provider.generate("hello") == '{"goal":"ok"}'
