from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from xpiano.llm_provider import LLMProvider
from xpiano.reference import song_dir
from xpiano.schemas import LLM_OUTPUT_SCHEMA, validate

PLAYBACK_TOOL_SCHEMA = {
    "name": "playback_control",
    "description": "Play a MIDI snippet to demonstrate a problem or comparison.",
    "parameters": {
        "type": "object",
        "required": ["source"],
        "properties": {
            "source": {"type": "string", "enum": ["reference", "attempt", "comparison"]},
            "measures": {
                "type": "object",
                "properties": {
                    "start": {"type": "integer", "minimum": 1},
                    "end": {"type": "integer", "minimum": 1},
                },
                "additionalProperties": False,
            },
            "bpm": {"type": "number", "minimum": 20, "maximum": 240},
            "highlight_pitches": {"type": "array", "items": {"type": "string"}},
            "delay_between_sec": {"type": "number", "default": 1.5},
        },
        "additionalProperties": False,
    },
}


def build_coaching_prompt(report: dict[str, Any]) -> str:
    compact_report = {
        "song_id": report.get("song_id"),
        "segment_id": report.get("segment_id"),
        "status": report.get("status"),
        "summary": report.get("summary", {}),
        "top_events": report.get("events", [])[:25],
    }
    return (
        "You are XPiano coach. Return strict JSON only.\n"
        "No markdown fences. No extra commentary.\n"
        "Target schema keys: goal, top_issues, drills, pass_conditions, next_recording, optional tool_calls.\n"
        "Drills total around 15 minutes.\n"
        f"Report:\n{json.dumps(compact_report, ensure_ascii=False)}\n"
    )


def _extract_json_text(raw: str) -> str:
    trimmed = raw.strip()
    if trimmed.startswith("{") and trimmed.endswith("}"):
        return trimmed

    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, flags=re.DOTALL)
    if fenced:
        return fenced.group(1)

    first = raw.find("{")
    last = raw.rfind("}")
    if first != -1 and last != -1 and last > first:
        return raw[first:last + 1]
    return trimmed


def _parse_and_validate(raw: str) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        payload = json.loads(_extract_json_text(raw))
    except json.JSONDecodeError as exc:
        return None, [f"json parse failed: {exc}"]
    if not isinstance(payload, dict):
        return None, ["top-level JSON must be an object"]
    schema_errors = validate("llm_output", payload)
    if schema_errors:
        return None, schema_errors
    return payload, []


def _build_correction_prompt(previous_raw: str, errors: list[str]) -> str:
    return (
        "Your previous output failed JSON schema validation.\n"
        f"Errors:\n- {'; '.join(errors)}\n"
        "Fix and return one valid JSON object only.\n"
        f"Previous output:\n{previous_raw}\n"
    )


def fallback_output(report: dict[str, Any]) -> dict[str, Any]:
    summary = report.get("summary", {})
    top_problems = summary.get("top_problems", [])[:2]
    if not top_problems:
        top_problems = ["Stabilize note accuracy", "Stabilize rhythm"]
    match_rate = float(summary.get("match_rate", 0.0))

    issues = [
        {
            "title": str(top_problems[0]),
            "why": "Most frequent error cluster in the latest attempt.",
            "evidence": [str(top_problems[0])],
        }
    ]
    if len(top_problems) > 1:
        issues.append(
            {
                "title": str(top_problems[1]),
                "why": "Second most common issue from event counts.",
                "evidence": [str(top_problems[1])],
            }
        )

    output = {
        "goal": "Raise stable match quality before increasing speed.",
        "top_issues": issues[:3],
        "drills": [
            {
                "name": "Slow pulse lock",
                "minutes": 7,
                "bpm": 40,
                "how": [
                    "Play only the target segment with metronome.",
                    "Pause and restart if any wrong or missed note appears.",
                ],
                "reps": "5 clean reps",
                "focus_measures": "target segment",
            },
            {
                "name": "Chunk repeat",
                "minutes": 8,
                "bpm": 45,
                "how": [
                    "Split into 1-2 measure chunks.",
                    "Repeat each chunk until two consecutive clean takes.",
                ],
                "reps": "2 consecutive clean takes per chunk",
                "focus_measures": "problem measures",
            },
        ],
        "pass_conditions": {
            "before_speed_up": [
                "No missing notes for 2 consecutive takes.",
                "No wrong-pitch events in target segment.",
            ],
            "speed_up_rule": "Increase BPM by +5 after meeting both conditions.",
        },
        "next_recording": {
            "what_to_record": "Same segment at current drill BPM.",
            "tips": [
                f"Current match_rate={match_rate:.2f}; keep speed conservative.",
                "Use count-in and keep consistent hand balance.",
            ],
        },
    }
    errors = validate("llm_output", output)
    if errors:
        raise ValueError(f"fallback llm output invalid: {'; '.join(errors)}")
    return output


def get_coaching(
    report: dict[str, Any],
    provider: LLMProvider,
    max_retries: int = 3,
) -> dict[str, Any]:
    prompt = build_coaching_prompt(report)
    last_raw = ""
    for _ in range(max_retries):
        last_raw = provider.generate(
            prompt=prompt, output_schema=LLM_OUTPUT_SCHEMA)
        payload, errors = _parse_and_validate(last_raw)
        if not errors and payload is not None:
            return payload
        prompt = _build_correction_prompt(previous_raw=last_raw, errors=errors)
    return fallback_output(report)


def save_coaching(
    coaching: dict[str, Any],
    song_id: str,
    data_dir: str | Path | None = None,
) -> Path:
    errors = validate("llm_output", coaching)
    if errors:
        raise ValueError(f"invalid llm_output.json: {'; '.join(errors)}")
    out_dir = song_dir(song_id=song_id, data_dir=data_dir) / "coaching"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"{ts}.json"
    with path.open("w", encoding="utf-8") as fp:
        json.dump(coaching, fp, ensure_ascii=True, indent=2)
    return path


async def stream_coaching(
    report: dict[str, Any],
    provider: LLMProvider,
    playback_engine: Any,
    on_text: Callable[[str], None] | None = None,
) -> str:
    prompt = build_coaching_prompt(report)
    chunks: list[str] = []
    async for event in provider.stream(prompt=prompt, tools=[PLAYBACK_TOOL_SCHEMA]):
        event_type = event.get("type")
        if event_type == "text_delta":
            text = str(event.get("text", ""))
            if text:
                chunks.append(text)
                if on_text is not None:
                    on_text(text)
            continue
        if event_type == "tool_use":
            payload = event.get("input", {})
            if payload:
                playback_engine.play(**payload)
    return "".join(chunks)
