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
