from __future__ import annotations

import asyncio
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


def test_claude_provider_stream_normalizes_events(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeToolBlock:
        type = "tool_use"
        name = "playback_control"
        input = {"source": "reference", "measures": {"start": 2, "end": 3}}

    class FakeEventText:
        type = "text"
        text = "hello"

    class FakeEventToolStop:
        type = "content_block_stop"
        content_block = FakeToolBlock()

    class FakeStreamManager:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            _ = exc_type
            _ = exc
            _ = tb
            return None

        def __iter__(self):
            yield FakeEventText()
            yield FakeEventToolStop()

    class FakeMessages:
        def __init__(self):
            self.stream_kwargs = None

        def create(self, **kwargs):
            _ = kwargs
            return SimpleNamespace(content=[SimpleNamespace(text="ok")])

        def stream(self, **kwargs):
            self.stream_kwargs = kwargs
            return FakeStreamManager()

    fake_messages = FakeMessages()

    class FakeClient:
        def __init__(self, api_key: str):
            _ = api_key
            self.messages = fake_messages

    async def _collect(provider: ClaudeProvider) -> list[dict]:
        out: list[dict] = []
        async for event in provider.stream(
            "hello",
            tools=[{"name": "playback_control", "description": "x",
                    "parameters": {"type": "object"}}],
        ):
            out.append(event)
        return out

    monkeypatch.setattr("xpiano.llm_provider.anthropic.Anthropic", FakeClient)
    provider = ClaudeProvider(api_key="test-key")
    events = asyncio.run(_collect(provider))
    assert events[0]["type"] == "text_delta"
    assert events[1]["type"] == "tool_use"
    sent_tools = fake_messages.stream_kwargs["tools"]
    assert sent_tools[0]["input_schema"]["type"] == "object"
