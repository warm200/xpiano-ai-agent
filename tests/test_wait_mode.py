from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from xpiano.models import NoteEvent
from xpiano.reference import save_meta
from xpiano.wait_mode import build_pitch_sequence, run_wait_mode


def _meta() -> dict:
    return {
        "song_id": "twinkle",
        "time_signature": {"beats_per_measure": 4, "beat_unit": 4},
        "bpm": 120,
        "segments": [{"segment_id": "verse1", "start_measure": 1, "end_measure": 2}],
        "tolerance": {
            "match_tol_ms": 80,
            "timing_grades": {"great_ms": 25, "good_ms": 50, "rushed_dragged_ms": 100},
            "chord_window_ms": 50,
        },
    }


def _note(pitch: int, start_sec: float, name: str) -> NoteEvent:
    return NoteEvent(
        pitch=pitch,
        pitch_name=name,
        start_sec=start_sec,
        end_sec=start_sec + 0.4,
        dur_sec=0.4,
        velocity=80,
        hand="R",
    )


def test_build_pitch_sequence_groups_chords() -> None:
    notes = [
        _note(60, 0.0, "C4"),
        _note(64, 0.01, "E4"),
        _note(67, 0.02, "G4"),
        _note(62, 0.5, "D4"),
    ]
    steps = build_pitch_sequence(notes, _meta())
    assert len(steps) == 2
    assert steps[0].pitches == {60, 64, 67}
    assert steps[1].pitches == {62}


def test_build_pitch_sequence_rejects_non_positive_bpm() -> None:
    meta = _meta()
    meta["bpm"] = 0
    try:
        _ = build_pitch_sequence([], meta)
    except ValueError as exc:
        assert "invalid bpm" in str(exc)
    else:
        raise AssertionError("expected ValueError for non-positive bpm")


def test_build_pitch_sequence_rejects_non_positive_beats_per_measure() -> None:
    meta = _meta()
    meta["time_signature"]["beats_per_measure"] = 0
    try:
        _ = build_pitch_sequence([], meta)
    except ValueError as exc:
        assert "beats_per_measure must be > 0" in str(exc)
    else:
        raise AssertionError("expected ValueError for invalid time signature")


def test_build_pitch_sequence_rejects_negative_chord_window_ms() -> None:
    meta = _meta()
    meta["tolerance"]["chord_window_ms"] = -1
    try:
        _ = build_pitch_sequence([], meta)
    except ValueError as exc:
        assert "invalid chord_window_ms" in str(exc)
    else:
        raise AssertionError("expected ValueError for invalid chord_window_ms")


def test_run_wait_mode_with_event_stream(xpiano_home: Path) -> None:
    song_dir = xpiano_home / "songs" / "twinkle"
    song_dir.mkdir(parents=True, exist_ok=True)
    save_meta(song_id="twinkle", meta=_meta())
    notes = [
        _note(60, 0.0, "C4"),
        _note(62, 0.5, "D4"),
    ]
    (song_dir / "reference_notes.json").write_text(
        json.dumps([asdict(note) for note in notes]),
        encoding="utf-8",
    )
    result = run_wait_mode(
        song_id="twinkle",
        segment_id="verse1",
        data_dir=xpiano_home,
        event_stream=[{60}, {62}],
    )
    assert result.total_steps == 2
    assert result.completed == 2
    assert result.errors == 0


def test_run_wait_mode_filters_by_segment(xpiano_home: Path) -> None:
    song_dir = xpiano_home / "songs" / "twinkle"
    song_dir.mkdir(parents=True, exist_ok=True)
    meta = _meta()
    meta["segments"] = [
        {"segment_id": "verse1", "start_measure": 1, "end_measure": 1},
        {"segment_id": "verse2", "start_measure": 2, "end_measure": 2},
    ]
    save_meta(song_id="twinkle", meta=meta)
    notes = [
        _note(60, 0.0, "C4"),   # measure 1 @ 120bpm
        _note(62, 2.0, "D4"),   # measure 2
    ]
    (song_dir / "reference_notes.json").write_text(
        json.dumps([asdict(note) for note in notes]),
        encoding="utf-8",
    )
    result = run_wait_mode(
        song_id="twinkle",
        segment_id="verse2",
        data_dir=xpiano_home,
        event_stream=[{62}],
    )
    assert result.total_steps == 1
    assert result.completed == 1


def test_run_wait_mode_rejects_non_positive_bpm_override(xpiano_home: Path) -> None:
    song_dir = xpiano_home / "songs" / "twinkle"
    song_dir.mkdir(parents=True, exist_ok=True)
    save_meta(song_id="twinkle", meta=_meta())
    notes = [
        _note(60, 0.0, "C4"),
    ]
    (song_dir / "reference_notes.json").write_text(
        json.dumps([asdict(note) for note in notes]),
        encoding="utf-8",
    )
    try:
        _ = run_wait_mode(
            song_id="twinkle",
            segment_id="verse1",
            bpm=0,
            data_dir=xpiano_home,
            event_stream=[],
        )
    except ValueError as exc:
        assert "invalid bpm" in str(exc)
    else:
        raise AssertionError("expected ValueError for non-positive bpm override")


def test_run_wait_mode_rejects_invalid_segment_range(xpiano_home: Path) -> None:
    song_dir = xpiano_home / "songs" / "twinkle"
    song_dir.mkdir(parents=True, exist_ok=True)
    meta = _meta()
    meta["segments"] = [{"segment_id": "verse1", "start_measure": 3, "end_measure": 2}]
    save_meta(song_id="twinkle", meta=meta)
    (song_dir / "reference_notes.json").write_text("[]", encoding="utf-8")
    try:
        _ = run_wait_mode(
            song_id="twinkle",
            segment_id="verse1",
            data_dir=xpiano_home,
            event_stream=[],
        )
    except ValueError as exc:
        assert "invalid segment range" in str(exc)
    else:
        raise AssertionError("expected ValueError for invalid segment range")


def test_run_wait_mode_rejects_non_positive_segment_start(monkeypatch) -> None:
    meta = _meta()
    meta["segments"] = [{"segment_id": "verse1", "start_measure": 0, "end_measure": 1}]
    monkeypatch.setattr("xpiano.wait_mode.load_meta", lambda **kwargs: meta)
    try:
        _ = run_wait_mode(
            song_id="twinkle",
            segment_id="verse1",
            event_stream=[],
        )
    except ValueError as exc:
        assert "invalid segment range" in str(exc)
    else:
        raise AssertionError("expected ValueError for invalid segment start")


def test_run_wait_mode_rejects_invalid_reference_note_entry(xpiano_home: Path) -> None:
    song_dir = xpiano_home / "songs" / "twinkle"
    song_dir.mkdir(parents=True, exist_ok=True)
    save_meta(song_id="twinkle", meta=_meta())
    bad_note = {"pitch": 60}
    (song_dir / "reference_notes.json").write_text(
        json.dumps([bad_note]),
        encoding="utf-8",
    )
    try:
        _ = run_wait_mode(
            song_id="twinkle",
            segment_id="verse1",
            data_dir=xpiano_home,
            event_stream=[],
        )
    except ValueError as exc:
        assert "invalid reference note entry" in str(exc)
    else:
        raise AssertionError("expected ValueError for invalid reference note entry")
