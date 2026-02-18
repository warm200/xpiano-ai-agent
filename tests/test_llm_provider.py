from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from xpiano.llm_provider import ClaudeProvider, create_provider


def test_create_provider_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        create_provider({"llm": {"provider": "unknown"}})


def test_create_provider_rejects_non_integer_max_tool_rounds() -> None:
    with pytest.raises(ValueError, match="invalid llm.max_tool_rounds"):
        create_provider({"llm": {"provider": "claude", "max_tool_rounds": "abc"}})


def test_create_provider_rejects_non_positive_max_tool_rounds() -> None:
    with pytest.raises(ValueError, match="invalid llm.max_tool_rounds"):
        create_provider({"llm": {"provider": "claude", "max_tool_rounds": 0}})


def test_create_provider_rejects_boolean_max_tool_rounds() -> None:
    with pytest.raises(ValueError, match="invalid llm.max_tool_rounds"):
        create_provider({"llm": {"provider": "claude", "max_tool_rounds": True}})


def test_claude_provider_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError):
        ClaudeProvider(api_key=None, api_key_env="ANTHROPIC_API_KEY")


def test_claude_provider_rejects_non_positive_max_tool_rounds() -> None:
    with pytest.raises(ValueError, match="max_tool_rounds must be > 0"):
        ClaudeProvider(api_key="test-key", max_tool_rounds=0)


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


def test_claude_provider_stream_falls_back_to_generate(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeMessages:
        def create(self, **kwargs):
            _ = kwargs
            return SimpleNamespace(content=[SimpleNamespace(text='{"goal":"fallback"}')])

        def stream(self, **kwargs):
            _ = kwargs
            raise RuntimeError("stream failed")

    class FakeClient:
        def __init__(self, api_key: str):
            _ = api_key
            self.messages = FakeMessages()

    async def _collect(provider: ClaudeProvider) -> list[dict]:
        out: list[dict] = []
        async for event in provider.stream("hello"):
            out.append(event)
        return out

    monkeypatch.setattr("xpiano.llm_provider.anthropic.Anthropic", FakeClient)
    provider = ClaudeProvider(api_key="test-key")
    events = asyncio.run(_collect(provider))
    assert events == [{"type": "text_delta", "text": '{"goal":"fallback"}'}]


def test_claude_provider_stream_with_tool_results_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeTextBlock:
        def __init__(self, text: str):
            self.type = "text"
            self.text = text

    class FakeToolUseBlock:
        type = "tool_use"
        id = "toolu_123"
        name = "playback_control"
        input = {"source": "reference", "measures": {"start": 2, "end": 2}}

    class FakeMessages:
        def __init__(self):
            self.calls: list[dict] = []
            self._idx = 0

        def create(self, **kwargs):
            self.calls.append(kwargs)
            if self._idx == 0:
                self._idx += 1
                return SimpleNamespace(content=[FakeTextBlock("intro"), FakeToolUseBlock()])
            return SimpleNamespace(content=[FakeTextBlock("done")])

        def stream(self, **kwargs):
            _ = kwargs
            raise AssertionError("stream fallback should not be used in this test")

    fake_messages = FakeMessages()

    class FakeClient:
        def __init__(self, api_key: str):
            _ = api_key
            self.messages = fake_messages

    async def _collect(provider: ClaudeProvider) -> list[dict]:
        out: list[dict] = []
        async for event in provider.stream_with_tool_results(
            prompt="hello",
            tools=[{"name": "playback_control", "parameters": {"type": "object"}}],
            on_tool_use=lambda event: {
                "status": "played",
                "duration_sec": 1.2,
                "echo_source": event["input"]["source"],
            },
        ):
            out.append(event)
        return out

    monkeypatch.setattr("xpiano.llm_provider.anthropic.Anthropic", FakeClient)
    provider = ClaudeProvider(api_key="test-key")
    events = asyncio.run(_collect(provider))
    assert [event["type"] for event in events] == ["text_delta", "tool_use", "text_delta"]
    second_call_messages = fake_messages.calls[1]["messages"]
    user_blocks = [
        block
        for message in second_call_messages
        if message.get("role") == "user" and isinstance(message.get("content"), list)
        for block in message["content"]
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]
    assert len(user_blocks) == 1
    assert '"status": "played"' in user_blocks[0]["content"]


def test_claude_provider_stream_with_tool_results_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeEventText:
        type = "text"
        text = "fallback-text"

    class FakeStreamManager:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            _ = exc_type, exc, tb
            return None

        def __iter__(self):
            yield FakeEventText()

    class FakeMessages:
        def create(self, **kwargs):
            _ = kwargs
            raise RuntimeError("create failed")

        def stream(self, **kwargs):
            _ = kwargs
            return FakeStreamManager()

    class FakeClient:
        def __init__(self, api_key: str):
            _ = api_key
            self.messages = FakeMessages()

    async def _collect(provider: ClaudeProvider) -> list[dict]:
        out: list[dict] = []
        async for event in provider.stream_with_tool_results(
            prompt="hello",
            tools=None,
            on_tool_use=lambda event: {"status": "played"},
        ):
            out.append(event)
        return out

    monkeypatch.setattr("xpiano.llm_provider.anthropic.Anthropic", FakeClient)
    provider = ClaudeProvider(api_key="test-key")
    events = asyncio.run(_collect(provider))
    assert events == [{"type": "text_delta", "text": "fallback-text"}]


def test_claude_provider_stream_with_tool_results_propagates_tool_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeToolUseBlock:
        type = "tool_use"
        id = "toolu_123"
        name = "playback_control"
        input = {"source": "reference"}

    class FakeMessages:
        def create(self, **kwargs):
            _ = kwargs
            return SimpleNamespace(content=[FakeToolUseBlock()])

        def stream(self, **kwargs):
            _ = kwargs
            raise AssertionError("fallback stream should not run for tool errors")

    class FakeClient:
        def __init__(self, api_key: str):
            _ = api_key
            self.messages = FakeMessages()

    async def _run(provider: ClaudeProvider) -> None:
        async for _ in provider.stream_with_tool_results(
            prompt="hello",
            tools=[{"name": "playback_control", "parameters": {"type": "object"}}],
            on_tool_use=lambda event: (_ for _ in ()).throw(ValueError("tool failed")),
        ):
            pass

    monkeypatch.setattr("xpiano.llm_provider.anthropic.Anthropic", FakeClient)
    provider = ClaudeProvider(api_key="test-key")
    with pytest.raises(ValueError, match="tool failed"):
        asyncio.run(_run(provider))


def test_claude_provider_stream_with_tool_results_propagates_serialization_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeToolUseBlock:
        type = "tool_use"
        id = "toolu_123"
        name = "playback_control"
        input = {"source": "reference"}

    class FakeMessages:
        def create(self, **kwargs):
            _ = kwargs
            return SimpleNamespace(content=[FakeToolUseBlock()])

        def stream(self, **kwargs):
            _ = kwargs
            raise AssertionError("fallback stream should not run for serialization errors")

    class FakeClient:
        def __init__(self, api_key: str):
            _ = api_key
            self.messages = FakeMessages()

    async def _run(provider: ClaudeProvider) -> None:
        async for _ in provider.stream_with_tool_results(
            prompt="hello",
            tools=[{"name": "playback_control", "parameters": {"type": "object"}}],
            on_tool_use=lambda event: {"status": "played", "duration_sec": float("nan")},
        ):
            pass

    monkeypatch.setattr("xpiano.llm_provider.anthropic.Anthropic", FakeClient)
    provider = ClaudeProvider(api_key="test-key")
    with pytest.raises(ValueError, match="Out of range float values are not JSON compliant"):
        asyncio.run(_run(provider))


def test_claude_provider_stream_with_tool_results_stops_after_max_rounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeToolUseBlock:
        type = "tool_use"
        id = "toolu_123"
        name = "playback_control"
        input = {"source": "reference"}

    class FakeMessages:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            _ = kwargs
            self.calls += 1
            return SimpleNamespace(content=[FakeToolUseBlock()])

        def stream(self, **kwargs):
            _ = kwargs
            raise AssertionError("fallback stream should not run for max-round guard")

    fake_messages = FakeMessages()

    class FakeClient:
        def __init__(self, api_key: str):
            _ = api_key
            self.messages = fake_messages

    async def _collect(provider: ClaudeProvider) -> list[dict]:
        out: list[dict] = []
        async for event in provider.stream_with_tool_results(
            prompt="hello",
            tools=[{"name": "playback_control", "parameters": {"type": "object"}}],
            on_tool_use=lambda event: {"status": "played", "source": event["input"]["source"]},
        ):
            out.append(event)
        return out

    monkeypatch.setattr("xpiano.llm_provider.anthropic.Anthropic", FakeClient)
    provider = ClaudeProvider(api_key="test-key", max_tool_rounds=2)
    events = asyncio.run(_collect(provider))
    assert fake_messages.calls == 2
    assert any(
        event.get("type") == "text_delta"
        and "too many tool rounds" in str(event.get("text", ""))
        for event in events
    )
