from __future__ import annotations

import json
from pathlib import Path

from xpiano.report import build_history, latest_valid_report_path


def _write_report(path: Path, match_rate: float, missing: int, extra: int, segment: str = "verse1") -> None:
    payload = {
        "version": "0.1",
        "song_id": "twinkle",
        "segment_id": segment,
        "status": "ok",
        "inputs": {"reference_mid": "ref.mid", "attempt_mid": "att.mid", "meta": {}},
        "summary": {
            "counts": {
                "ref_notes": 10,
                "attempt_notes": 10,
                "matched": max(0, 10 - missing),
                "missing": missing,
                "extra": extra,
            },
            "match_rate": match_rate,
            "top_problems": [],
        },
        "metrics": {"timing": {}, "duration": {}, "dynamics": {}},
        "events": [],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_build_history_filters_and_limits(xpiano_home: Path) -> None:
    reports = xpiano_home / "songs" / "twinkle" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    _write_report(reports / "20260101_120000.json", 0.50, 5, 2, "verse1")
    _write_report(reports / "20260101_120100.json", 0.70, 3, 1, "verse1")
    _write_report(reports / "20260101_120200.json", 0.80, 2, 1, "verse2")

    rows = build_history(song_id="twinkle", segment_id="verse1",
                         attempts=5, data_dir=xpiano_home)
    assert len(rows) == 2
    assert rows[-1]["match_rate"] == 0.7

    limited = build_history(
        song_id="twinkle", segment_id=None, attempts=2, data_dir=xpiano_home)
    assert len(limited) == 2
    assert limited[0]["filename"] == "20260101_120100.json"


def test_latest_valid_report_path_skips_invalid_latest(xpiano_home: Path) -> None:
    reports = xpiano_home / "songs" / "twinkle" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    _write_report(reports / "20260101_120000.json", 0.70, 3, 1, "verse1")
    (reports / "20260101_120100.json").write_text("{bad", encoding="utf-8")

    resolved = latest_valid_report_path(song_id="twinkle", data_dir=xpiano_home)
    assert resolved.name == "20260101_120000.json"


def test_latest_valid_report_path_filters_segment(xpiano_home: Path) -> None:
    reports = xpiano_home / "songs" / "twinkle" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    _write_report(reports / "20260101_120000.json", 0.70, 3, 1, "verse1")
    _write_report(reports / "20260101_120100.json", 0.80, 2, 1, "verse2")

    resolved = latest_valid_report_path(
        song_id="twinkle",
        segment_id="verse1",
        data_dir=xpiano_home,
    )
    assert resolved.name == "20260101_120000.json"


def test_latest_valid_report_path_normalizes_whitespace_segment_id(
    xpiano_home: Path,
) -> None:
    reports = xpiano_home / "songs" / "twinkle" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    _write_report(reports / "20260101_120000.json", 0.70, 3, 1, " verse1 ")

    resolved = latest_valid_report_path(
        song_id="twinkle",
        segment_id="verse1",
        data_dir=xpiano_home,
    )
    assert resolved.name == "20260101_120000.json"


def test_build_history_rejects_non_positive_attempts(xpiano_home: Path) -> None:
    try:
        _ = build_history(song_id="twinkle", attempts=0, data_dir=xpiano_home)
    except ValueError as exc:
        assert "attempts must be > 0" in str(exc)
    else:
        raise AssertionError("expected ValueError for non-positive attempts")


def test_build_history_reads_legacy_report_without_schema(xpiano_home: Path) -> None:
    reports = xpiano_home / "songs" / "twinkle" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    legacy_payload = {
        "song_id": "twinkle",
        "segment_id": "verse1",
        "summary": {
            "counts": {
                "ref_notes": "10",
                "matched": "8",
                "missing": "2",
                "extra": "1",
            },
            "match_rate": "0.8",
        },
    }
    (reports / "20260101_120000.json").write_text(
        json.dumps(legacy_payload), encoding="utf-8"
    )

    rows = build_history(song_id="twinkle", attempts=5, data_dir=xpiano_home)
    assert len(rows) == 1
    assert rows[0]["segment_id"] == "verse1"
    assert rows[0]["match_rate"] == 0.8
    assert rows[0]["missing"] == 2
    assert rows[0]["extra"] == 1
    assert rows[0]["matched"] == 8
    assert rows[0]["ref_notes"] == 10


def test_build_history_skips_invalid_json_report(xpiano_home: Path) -> None:
    reports = xpiano_home / "songs" / "twinkle" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "20260101_120000.json").write_text("{invalid", encoding="utf-8")

    rows = build_history(song_id="twinkle", attempts=5, data_dir=xpiano_home)
    assert rows == []


def test_build_history_recomputes_non_finite_match_rate_from_counts(
    xpiano_home: Path,
) -> None:
    reports = xpiano_home / "songs" / "twinkle" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    legacy_payload = {
        "song_id": "twinkle",
        "segment_id": "verse1",
        "summary": {
            "counts": {"ref_notes": 10, "matched": 5, "missing": 5, "extra": 0},
            "match_rate": "nan",
        },
    }
    (reports / "20260101_120000.json").write_text(
        json.dumps(legacy_payload), encoding="utf-8"
    )

    rows = build_history(song_id="twinkle", attempts=5, data_dir=xpiano_home)
    assert len(rows) == 1
    assert rows[0]["match_rate"] == 0.5


def test_build_history_ignores_non_finite_count_values(
    xpiano_home: Path,
) -> None:
    reports = xpiano_home / "songs" / "twinkle" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    legacy_payload = {
        "song_id": "twinkle",
        "segment_id": "verse1",
        "summary": {
            "counts": {
                "ref_notes": float("inf"),
                "matched": 5,
                "missing": 1,
                "extra": 0,
            },
            "match_rate": "nan",
        },
    }
    (reports / "20260101_120000.json").write_text(
        json.dumps(legacy_payload), encoding="utf-8"
    )

    rows = build_history(song_id="twinkle", attempts=5, data_dir=xpiano_home)
    assert len(rows) == 1
    assert rows[0]["ref_notes"] == 0
    assert rows[0]["match_rate"] == 0.0


def test_build_history_handles_non_object_summary_and_counts(
    xpiano_home: Path,
) -> None:
    reports = xpiano_home / "songs" / "twinkle" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    legacy_payload = {
        "song_id": "twinkle",
        "segment_id": "verse1",
        "summary": ["bad-shape"],
    }
    (reports / "20260101_120000.json").write_text(
        json.dumps(legacy_payload), encoding="utf-8"
    )

    rows = build_history(song_id="twinkle", attempts=5, data_dir=xpiano_home)
    assert len(rows) == 1
    assert rows[0]["segment_id"] == "verse1"
    assert rows[0]["match_rate"] == 0.0
    assert rows[0]["matched"] == 0
    assert rows[0]["ref_notes"] == 0


def test_build_history_parses_decimal_integer_strings(
    xpiano_home: Path,
) -> None:
    reports = xpiano_home / "songs" / "twinkle" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    legacy_payload = {
        "song_id": "twinkle",
        "segment_id": "verse1",
        "summary": {
            "counts": {
                "ref_notes": "10.0",
                "matched": "8.0",
                "missing": "2.0",
                "extra": "1.0",
            },
            "match_rate": "0.8",
        },
    }
    (reports / "20260101_120000.json").write_text(
        json.dumps(legacy_payload), encoding="utf-8"
    )

    rows = build_history(song_id="twinkle", attempts=5, data_dir=xpiano_home)
    assert len(rows) == 1
    assert rows[0]["ref_notes"] == 10
    assert rows[0]["matched"] == 8
    assert rows[0]["missing"] == 2
    assert rows[0]["extra"] == 1


def test_build_history_normalizes_whitespace_segment_id(
    xpiano_home: Path,
) -> None:
    reports = xpiano_home / "songs" / "twinkle" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    _write_report(reports / "20260101_120000.json", 0.70, 3, 1, " verse1 ")

    rows = build_history(
        song_id="twinkle",
        segment_id="verse1",
        attempts=5,
        data_dir=xpiano_home,
    )
    assert len(rows) == 1
    assert rows[0]["segment_id"] == "verse1"
