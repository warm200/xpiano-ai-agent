from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, AsyncIterator

from xpiano.llm_coach import (build_coaching_prompt, fallback_output,
                              get_coaching, save_coaching, stream_coaching)
from xpiano.llm_provider import LLMProvider
from xpiano.schemas import validate


class FakeProvider(LLMProvider):
    def __init__(self, responses: list[str]):
        self._responses = responses
        self.calls = 0

    def generate(self, prompt: str, output_schema: dict | None = None) -> str:
        _ = prompt
        _ = output_schema
        idx = min(self.calls, len(self._responses) - 1)
        self.calls += 1
        return self._responses[idx]

    async def stream(self, prompt: str, tools: list[dict] | None = None) -> AsyncIterator[dict[str, Any]]:
        _ = prompt
        _ = tools
        yield {"type": "text_delta", "text": "ok"}


class FakeStreamProvider(LLMProvider):
    def generate(self, prompt: str, output_schema: dict | None = None) -> str:
        _ = prompt
        _ = output_schema
        return "{}"

    async def stream(self, prompt: str, tools: list[dict] | None = None) -> AsyncIterator[dict[str, Any]]:
        _ = prompt
        _ = tools
        yield {"type": "text_delta", "text": "issue found"}
        yield {
            "type": "tool_use",
            "input": {
                "source": "reference",
                "measures": {"start": 2, "end": 3},
                "bpm": 45,
                "highlight_pitches": ["E4"],
            },
        }


class FakeInvalidToolProvider(LLMProvider):
    def generate(self, prompt: str, output_schema: dict | None = None) -> str:
        _ = prompt
        _ = output_schema
        return "{}"

    async def stream(self, prompt: str, tools: list[dict] | None = None) -> AsyncIterator[dict[str, Any]]:
        _ = prompt
        _ = tools
        yield {"type": "text_delta", "text": "issue found"}
        yield {
            "type": "tool_use",
            "input": {
                "source": "bad",
            },
        }


def _report() -> dict[str, Any]:
    return {
        "song_id": "twinkle",
        "segment_id": "verse1",
        "status": "ok",
        "summary": {
            "counts": {"ref_notes": 10, "attempt_notes": 10, "matched": 8, "missing": 2, "extra": 1},
            "match_rate": 0.8,
            "top_problems": ["M2 wrong_pitch x2", "M3 timing_late x3"],
        },
        "events": [],
    }


def _valid_output_json() -> str:
    payload = {
        "goal": "Stabilize M2 pitch accuracy.",
        "top_issues": [
            {
                "title": "Wrong pitch in M2",
                "why": "Most frequent issue.",
                "evidence": ["M2 wrong_pitch x2"],
            }
        ],
        "drills": [
            {
                "name": "Slow fix",
                "minutes": 7,
                "bpm": 45,
                "how": ["Loop M2", "Count beats aloud"],
                "reps": "5 clean reps",
                "focus_measures": "2",
            },
            {
                "name": "Link bars",
                "minutes": 8,
                "bpm": 50,
                "how": ["Connect M2-M3", "No pause between bars"],
                "reps": "4 reps",
                "focus_measures": "2-3",
            },
        ],
        "pass_conditions": {
            "before_speed_up": ["No wrong notes in M2", "Stable rhythm in M3"],
            "speed_up_rule": "+5 BPM after two clean takes",
        },
        "next_recording": {
            "what_to_record": "M2-M3",
            "tips": ["Keep wrists loose", "Lock beat 1"],
        },
    }
    return json.dumps(payload)


def test_build_coaching_prompt_includes_summary() -> None:
    prompt = build_coaching_prompt(_report())
    assert "top_issues" in prompt
    assert "match_rate" in prompt


def test_get_coaching_valid_first_try() -> None:
    provider = FakeProvider([_valid_output_json()])
    output = get_coaching(report=_report(), provider=provider)
    assert validate("llm_output", output) == []
    assert provider.calls == 1


def test_get_coaching_retry_then_success() -> None:
    provider = FakeProvider(["not json", _valid_output_json()])
    output = get_coaching(report=_report(), provider=provider, max_retries=3)
    assert validate("llm_output", output) == []
    assert provider.calls == 2


def test_get_coaching_fallback_after_retries() -> None:
    provider = FakeProvider(["not json", "still bad", "nope"])
    output = get_coaching(report=_report(), provider=provider, max_retries=3)
    assert validate("llm_output", output) == []


def test_get_coaching_rejects_non_positive_max_retries() -> None:
    provider = FakeProvider([_valid_output_json()])
    try:
        _ = get_coaching(report=_report(), provider=provider, max_retries=0)
    except ValueError as exc:
        assert "max_retries must be > 0" in str(exc)
    else:
        raise AssertionError("expected ValueError for non-positive max_retries")


def test_fallback_output_schema_valid() -> None:
    output = fallback_output(_report())
    assert validate("llm_output", output) == []


def test_save_coaching_writes_file(xpiano_home) -> None:
    output = fallback_output(_report())
    path = save_coaching(output, song_id="twinkle")
    assert path.exists()


def test_save_coaching_avoids_filename_collision(xpiano_home, monkeypatch) -> None:
    class _FixedDateTime:
        @classmethod
        def now(cls):
            return datetime(2026, 1, 1, 12, 0, 0)

    monkeypatch.setattr("xpiano.llm_coach.datetime", _FixedDateTime)
    output = fallback_output(_report())
    path1 = save_coaching(output, song_id="twinkle", data_dir=xpiano_home)
    path2 = save_coaching(output, song_id="twinkle", data_dir=xpiano_home)
    assert path1 != path2
    assert path1.exists()
    assert path2.exists()


def test_stream_coaching_calls_playback_engine() -> None:
    class Playback:
        def __init__(self):
            self.calls = 0

        def play(self, **kwargs):
            _ = kwargs
            self.calls += 1

    provider = FakeStreamProvider()
    playback = Playback()
    streamed: list[str] = []
    tool_events: list[dict] = []
    text = asyncio.run(
        stream_coaching(
            report=_report(),
            provider=provider,
            playback_engine=playback,
            on_text=lambda chunk: streamed.append(chunk),
            on_tool=lambda payload: tool_events.append(payload),
        )
    )
    assert playback.calls == 1
    assert "issue found" in text
    assert streamed == ["issue found"]
    assert len(tool_events) == 1


def test_stream_coaching_rejects_invalid_tool_payload() -> None:
    class Playback:
        def __init__(self):
            self.calls = 0

        def play(self, **kwargs):
            _ = kwargs
            self.calls += 1

    provider = FakeInvalidToolProvider()
    playback = Playback()
    try:
        _ = asyncio.run(
            stream_coaching(
                report=_report(),
                provider=provider,
                playback_engine=playback,
            )
        )
    except ValueError as exc:
        assert "invalid playback source" in str(exc)
    else:
        raise AssertionError("expected ValueError for invalid tool payload")
    assert playback.calls == 0
