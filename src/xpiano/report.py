from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from xpiano.analysis import AnalysisResult
from xpiano.reference import song_dir
from xpiano.schemas import validate


def _top_problems(result: AnalysisResult, limit: int = 5) -> list[str]:
    by_type_measure = Counter((event.type, event.measure)
                              for event in result.events)
    output: list[str] = []
    for (event_type, measure), count in by_type_measure.most_common(limit):
        output.append(f"M{measure} {event_type} x{count}")
    return output


def _count_by_type(result: AnalysisResult, event_type: str) -> int:
    return len([event for event in result.events if event.type == event_type])


def build_report(
    result: AnalysisResult,
    meta: dict[str, Any],
    ref_path: str | Path,
    attempt_path: str | Path,
    song_id: str | None = None,
    segment_id: str | None = None,
) -> dict[str, Any]:
    resolved_song_id = song_id or str(meta.get("song_id", "unknown"))
    resolved_segment_id = segment_id or str(
        meta.get("segments", [{}])[0].get("segment_id", "default"))
    status = "low_quality" if result.quality_tier == "too_low" else "ok"

    report = {
        "version": "0.1",
        "song_id": resolved_song_id,
        "segment_id": resolved_segment_id,
        "inputs": {
            "reference_mid": str(ref_path),
            "attempt_mid": str(attempt_path),
            "meta": meta,
        },
        "status": status,
        "summary": {
            "counts": {
                "ref_notes": len(result.ref_notes),
                "attempt_notes": len(result.attempt_notes),
                "matched": result.matched,
                "missing": _count_by_type(result, "missing_note"),
                "extra": _count_by_type(result, "extra_note"),
            },
            "match_rate": result.match_rate,
            "top_problems": _top_problems(result),
        },
        "metrics": result.metrics,
        "events": [asdict(event) for event in result.events],
        "examples": {
            "missing_first_10": [
                asdict(event) for event in result.events if event.type == "missing_note"
            ][:10],
            "extra_first_10": [
                asdict(event) for event in result.events if event.type == "extra_note"
            ][:10],
        },
    }
    errors = validate("report", report)
    if errors:
        raise ValueError(f"invalid report.json: {'; '.join(errors)}")
    return report


def save_report(report: dict[str, Any], song_id: str, data_dir: str | Path | None = None) -> Path:
    errors = validate("report", report)
    if errors:
        raise ValueError(f"invalid report.json: {'; '.join(errors)}")
    reports_dir = song_dir(song_id=song_id, data_dir=data_dir) / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = reports_dir / f"{ts}.json"
    with path.open("w", encoding="utf-8") as fp:
        json.dump(report, fp, ensure_ascii=True, indent=2)
    return path
