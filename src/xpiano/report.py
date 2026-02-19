from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from xpiano.analysis import AnalysisResult
from xpiano.reference import song_dir
from xpiano.schemas import validate


def _coerce_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, float):
        if not math.isfinite(value):
            return default
        if not value.is_integer():
            return default
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return default
        try:
            return int(stripped)
        except ValueError:
            try:
                parsed = float(stripped)
            except ValueError:
                return default
            if not math.isfinite(parsed) or not parsed.is_integer():
                return default
            return int(parsed)
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _coerce_float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return parsed


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _normalize_segment_id(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized if normalized else None


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
    meta_segments = meta.get("segments", [])
    default_segment = "default"
    if isinstance(meta_segments, list) and meta_segments:
        first_segment = meta_segments[0]
        if isinstance(first_segment, dict):
            default_segment = str(first_segment.get("segment_id", "default"))
    resolved_segment_id = segment_id or default_segment
    status = "low_quality" if result.quality_tier in {"simplified", "too_low"} else "ok"
    if result.quality_tier == "too_low":
        top_problem_limit = 0
    elif result.quality_tier == "simplified":
        top_problem_limit = 3
    else:
        top_problem_limit = 5

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
            "top_problems": _top_problems(result, limit=top_problem_limit),
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
    suffix_idx = 1
    while path.exists():
        path = reports_dir / f"{ts}_{suffix_idx:02d}.json"
        suffix_idx += 1
    with path.open("w", encoding="utf-8") as fp:
        json.dump(report, fp, ensure_ascii=True, indent=2)
    return path


def list_reports(song_id: str, data_dir: str | Path | None = None) -> list[Path]:
    reports_dir = song_dir(song_id=song_id, data_dir=data_dir) / "reports"
    if not reports_dir.exists():
        return []
    return sorted(reports_dir.glob("*.json"))


def load_report(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as fp:
        payload = json.load(fp)
    errors = validate("report", payload)
    if errors:
        raise ValueError(f"invalid report.json: {'; '.join(errors)}")
    return payload


def latest_valid_report_path(
    song_id: str,
    segment_id: str | None = None,
    data_dir: str | Path | None = None,
) -> Path:
    target_segment = _normalize_segment_id(segment_id)
    paths = list_reports(song_id=song_id, data_dir=data_dir)
    for path in reversed(paths):
        try:
            report = load_report(path)
        except (FileNotFoundError, ValueError):
            continue
        report_segment = _normalize_segment_id(report.get("segment_id"))
        if target_segment is not None and report_segment != target_segment:
            continue
        return path
    if target_segment is None:
        raise FileNotFoundError(f"no valid reports found for song: {song_id}")
    raise FileNotFoundError(
        f"no valid reports found for song: {song_id} segment: {target_segment}"
    )


def build_history(
    song_id: str,
    segment_id: str | None = None,
    attempts: int = 5,
    data_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    if attempts <= 0:
        raise ValueError("attempts must be > 0")
    target_segment = _normalize_segment_id(segment_id)
    paths = list_reports(song_id=song_id, data_dir=data_dir)
    rows: list[dict[str, Any]] = []
    for path in paths:
        try:
            report = load_report(path)
        except FileNotFoundError:
            continue
        except ValueError:
            try:
                with path.open("r", encoding="utf-8") as fp:
                    report = json.load(fp)
            except (FileNotFoundError, ValueError):
                continue
            if not isinstance(report, dict):
                continue
        report_segment = _normalize_segment_id(report.get("segment_id"))
        if target_segment is not None and report_segment != target_segment:
            continue
        summary = _as_dict(report.get("summary"))
        counts = _as_dict(summary.get("counts"))
        matched = _coerce_int(counts.get("matched", 0))
        ref_notes = _coerce_int(counts.get("ref_notes", 0))
        match_rate = _coerce_float(summary.get("match_rate", 0.0))
        if match_rate == 0.0 and matched > 0 and ref_notes > 0:
            match_rate = matched / ref_notes
        rows.append(
            {
                "path": str(path),
                "filename": path.name,
                "segment_id": report_segment,
                "match_rate": match_rate,
                "missing": _coerce_int(counts.get("missing", 0)),
                "extra": _coerce_int(counts.get("extra", 0)),
                "matched": matched,
                "ref_notes": ref_notes,
            }
        )
    rows.sort(key=lambda item: item["filename"])
    rows = rows[-attempts:]
    return rows
