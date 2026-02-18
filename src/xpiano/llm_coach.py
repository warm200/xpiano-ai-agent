from __future__ import annotations

import json
import math
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


def _parse_int_value(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"invalid playback {name}: expected integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise ValueError(f"invalid playback {name}: expected integer")
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError as exc:
            raise ValueError(f"invalid playback {name}: expected integer") from exc
    raise ValueError(f"invalid playback {name}: expected integer")


def _validate_playback_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("invalid playback tool payload: expected object")
    allowed = {"source", "measures", "bpm", "highlight_pitches", "delay_between_sec"}
    unknown = sorted(set(payload.keys()) - allowed)
    if unknown:
        raise ValueError(f"invalid playback tool payload keys: {', '.join(unknown)}")

    source = str(payload.get("source", ""))
    if source not in {"reference", "attempt", "comparison"}:
        raise ValueError(f"invalid playback source: {source}")

    out: dict[str, Any] = {"source": source}
    measures = payload.get("measures")
    if measures is not None:
        if not isinstance(measures, dict):
            raise ValueError("invalid playback measures: expected object")
        m_unknown = sorted(set(measures.keys()) - {"start", "end"})
        if m_unknown:
            raise ValueError(f"invalid playback measures keys: {', '.join(m_unknown)}")
        if "start" not in measures or "end" not in measures:
            raise ValueError("invalid playback measures: start and end are required together")
        start = _parse_int_value(measures["start"], name="measures.start")
        end = _parse_int_value(measures["end"], name="measures.end")
        if start <= 0 or end <= 0 or end < start:
            raise ValueError(f"invalid playback measure range: {start}-{end}")
        out["measures"] = {"start": start, "end": end}

    bpm = payload.get("bpm")
    if bpm is not None:
        bpm_value = float(bpm)
        if not math.isfinite(bpm_value) or bpm_value < 20 or bpm_value > 240:
            raise ValueError("invalid playback bpm: must be in range 20..240")
        out["bpm"] = bpm_value

    highlight = payload.get("highlight_pitches")
    if highlight is not None:
        if not isinstance(highlight, list) or not all(isinstance(item, str) for item in highlight):
            raise ValueError("invalid playback highlight_pitches: expected list[str]")
        out["highlight_pitches"] = highlight

    delay_between = payload.get("delay_between_sec")
    if delay_between is not None:
        delay_value = float(delay_between)
        if not math.isfinite(delay_value) or delay_value < 0:
            raise ValueError("invalid playback delay_between_sec: must be >= 0")
        out["delay_between_sec"] = delay_value
    return out


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
    if trimmed.startswith("{"):
        try:
            parsed, end_idx = json.JSONDecoder().raw_decode(trimmed)
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(parsed, dict) and end_idx == len(trimmed):
                return trimmed

    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, flags=re.DOTALL)
    if fenced:
        return fenced.group(1)

    decoder = json.JSONDecoder()
    for idx, char in enumerate(raw):
        if char != "{":
            continue
        try:
            payload, end_idx = decoder.raw_decode(raw[idx:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return raw[idx: idx + end_idx]

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


def parse_coaching_text(raw: str) -> tuple[dict[str, Any] | None, list[str]]:
    return _parse_and_validate(raw)


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
    if max_retries <= 0:
        raise ValueError("max_retries must be > 0")
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
    suffix_idx = 1
    while path.exists():
        path = out_dir / f"{ts}_{suffix_idx:02d}.json"
        suffix_idx += 1
    with path.open("w", encoding="utf-8") as fp:
        json.dump(coaching, fp, ensure_ascii=True, indent=2)
    return path


async def stream_coaching(
    report: dict[str, Any],
    provider: LLMProvider,
    playback_engine: Any,
    on_text: Callable[[str], None] | None = None,
    on_tool: Callable[[dict[str, Any]], None] | None = None,
) -> str:
    prompt = build_coaching_prompt(report)
    chunks: list[str] = []

    def _playback_result_payload(result: Any) -> dict[str, Any]:
        if isinstance(result, dict):
            payload: dict[str, Any] = dict(result)
            if "status" in payload:
                payload["status"] = str(payload["status"])
            duration_sec = payload.get("duration_sec")
            if duration_sec is not None:
                duration_value = float(duration_sec)
                if not math.isfinite(duration_value) or duration_value < 0:
                    raise ValueError("invalid playback result duration_sec")
                payload["duration_sec"] = duration_value
            if not payload:
                payload["status"] = "ok"
            return payload
        out_payload: dict[str, Any] = {}
        status = getattr(result, "status", None)
        if status is not None:
            out_payload["status"] = str(status)
        duration_sec = getattr(result, "duration_sec", None)
        if duration_sec is not None:
            duration_value = float(duration_sec)
            if not math.isfinite(duration_value) or duration_value < 0:
                raise ValueError("invalid playback result duration_sec")
            out_payload["duration_sec"] = duration_value
        if not out_payload:
            out_payload["status"] = "ok"
        return out_payload

    def _on_tool_use(event: dict[str, Any]) -> dict[str, Any]:
        payload = event.get("input", {})
        if not payload:
            raise ValueError("invalid playback tool payload: missing input")
        validated_payload = _validate_playback_payload(payload)
        if on_tool is not None:
            on_tool(validated_payload)
        playback_result = playback_engine.play(**validated_payload)
        return _playback_result_payload(playback_result)

    async for event in provider.stream_with_tool_results(
        prompt=prompt,
        tools=[PLAYBACK_TOOL_SCHEMA],
        on_tool_use=_on_tool_use,
    ):
        event_type = event.get("type")
        if event_type == "text_delta":
            text = str(event.get("text", ""))
            if text:
                chunks.append(text)
                if on_text is not None:
                    on_text(text)
    return "".join(chunks)
