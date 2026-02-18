from __future__ import annotations

from collections import defaultdict
from typing import Any


def render_low_match(match_rate: float, song: str, segment: str) -> str:
    return (
        f"Match quality too low ({match_rate:.2f}).\n"
        f"Try:\n"
        f"  xpiano playback --song {song} --segment {segment} --mode reference --bpm 40\n"
        f"  xpiano wait --song {song} --segment {segment}\n"
    )


def render_report(report: dict[str, Any], coaching: dict[str, Any] | None = None) -> str:
    summary = report.get("summary", {})
    counts = summary.get("counts", {})
    lines = [
        f"match_rate={summary.get('match_rate', 0):.2f}",
        (
            f"ref={counts.get('ref_notes', 0)} "
            f"attempt={counts.get('attempt_notes', 0)} "
            f"matched={counts.get('matched', 0)} "
            f"missing={counts.get('missing', 0)} "
            f"extra={counts.get('extra', 0)}"
        ),
    ]
    for problem in summary.get("top_problems", [])[:5]:
        lines.append(f"- {problem}")

    if coaching:
        lines.append(f"Goal: {coaching.get('goal', '-')}")
        for issue in coaching.get("top_issues", [])[:3]:
            lines.append(f"  issue: {issue.get('title', '-')}")
    return "\n".join(lines)


def render_piano_roll_diff(report: dict[str, Any], max_measures: int = 3) -> str:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for event in report.get("events", []):
        measure = int(event.get("measure", 0))
        if measure > 0:
            grouped[measure].append(event)

    if not grouped:
        return "No event diff."

    out: list[str] = []
    for measure in sorted(grouped.keys())[:max_measures]:
        out.append(f"Measure {measure}:")
        for event in grouped[measure][:8]:
            if event.get("type") == "wrong_pitch":
                actual = event.get("actual_pitch_name")
                expected = event.get("pitch_name")
                out.append(
                    f"  beat {event.get('beat', 0):.2f}: "
                    f"wrong {actual} -> expected {expected}"
                )
            else:
                out.append(
                    f"  beat {event.get('beat', 0):.2f}: {event.get('type')} {event.get('pitch_name', '')}".rstrip(
                    )
                )
    return "\n".join(out)


def render_wait_step(measure: int, beat: float, pitch_names: list[str]) -> str:
    expected = " ".join(pitch_names) if pitch_names else "(none)"
    return f"▶ M{measure} Beat{beat:.2f}: {expected}"
