from __future__ import annotations

import pytest

from xpiano.events import generate_events
from xpiano.models import AlignmentResult, NoteEvent


def _note(pitch: int, start_sec: float, dur_sec: float = 0.5, name: str = "C4") -> NoteEvent:
    return NoteEvent(
        pitch=pitch,
        pitch_name=name,
        start_sec=start_sec,
        end_sec=start_sec + dur_sec,
        dur_sec=dur_sec,
        velocity=80,
        hand="R",
    )


def _meta() -> dict:
    return {
        "song_id": "twinkle",
        "time_signature": {"beats_per_measure": 4, "beat_unit": 4},
        "bpm": 120,
        "segments": [{"segment_id": "default", "start_measure": 1, "end_measure": 4}],
        "tolerance": {
            "match_tol_ms": 120,
            "timing_grades": {"great_ms": 25, "good_ms": 50, "rushed_dragged_ms": 100},
            "duration_short_ratio": 0.6,
            "duration_long_ratio": 1.5,
        },
    }


def test_generate_events_merges_wrong_pitch() -> None:
    ref = [_note(60, 0.0, name="C4")]
    attempt = [_note(62, 0.0, name="D4")]
    alignment = AlignmentResult(path=[], cost=1.0, method="per_pitch_dtw")

    events = generate_events(ref=ref, attempt=attempt,
                             alignment=alignment, meta=_meta())
    assert len(events) == 1
    assert events[0].type == "wrong_pitch"
    assert events[0].pitch_name == "C4"
    assert events[0].actual_pitch_name == "D4"


def test_generate_events_timing_and_duration() -> None:
    ref = [_note(60, 0.0, dur_sec=1.0, name="C4")]
    attempt = [_note(60, 0.07, dur_sec=0.4, name="C4")]
    alignment = AlignmentResult(
        path=[(0, 0)], cost=0.07, method="per_pitch_dtw")

    events = generate_events(ref=ref, attempt=attempt,
                             alignment=alignment, meta=_meta())
    event_types = {event.type for event in events}
    assert "timing_late" in event_types
    assert "duration_short" in event_types


def test_generate_events_chord_partial_keeps_missing_and_extra() -> None:
    ref = [
        _note(60, 0.0, name="C4"),
        _note(64, 0.01, name="E4"),
        _note(67, 0.02, name="G4"),
    ]
    attempt = [
        _note(60, 0.0, name="C4"),
        _note(64, 0.01, name="E4"),
        _note(71, 0.02, name="B4"),
    ]
    alignment = AlignmentResult(path=[(0, 0), (1, 1)], cost=0.01, method="per_pitch_dtw")
    events = generate_events(ref=ref, attempt=attempt, alignment=alignment, meta=_meta())

    event_types = sorted(event.type for event in events)
    assert event_types == ["extra_note", "missing_note"]
    assert all(event.group_id is not None for event in events)
    assert all("chord partial" in (event.evidence or "") for event in events)


def test_generate_events_respects_selected_segment_start_measure() -> None:
    meta = _meta()
    meta["segments"] = [
        {"segment_id": "verse1", "start_measure": 1, "end_measure": 1},
        {"segment_id": "verse2", "start_measure": 2, "end_measure": 2},
    ]
    ref = [_note(60, 0.0, dur_sec=1.0, name="C4")]
    attempt = [_note(60, 0.07, dur_sec=1.0, name="C4")]
    alignment = AlignmentResult(path=[(0, 0)], cost=0.07, method="per_pitch_dtw")

    events = generate_events(
        ref=ref,
        attempt=attempt,
        alignment=alignment,
        meta=meta,
        segment_id="verse2",
    )
    assert len(events) == 1
    assert events[0].type == "timing_late"
    assert events[0].measure == 2


def test_generate_events_rejects_non_positive_bpm() -> None:
    meta = _meta()
    meta["bpm"] = 0
    ref = [_note(60, 0.0, dur_sec=1.0, name="C4")]
    attempt = [_note(60, 0.07, dur_sec=1.0, name="C4")]
    alignment = AlignmentResult(path=[(0, 0)], cost=0.07, method="per_pitch_dtw")
    with pytest.raises(ValueError, match="invalid bpm"):
        _ = generate_events(
            ref=ref,
            attempt=attempt,
            alignment=alignment,
            meta=meta,
        )


def test_generate_events_rejects_out_of_range_bpm() -> None:
    meta = _meta()
    meta["bpm"] = 241
    ref = [_note(60, 0.0, dur_sec=1.0, name="C4")]
    attempt = [_note(60, 0.07, dur_sec=1.0, name="C4")]
    alignment = AlignmentResult(path=[(0, 0)], cost=0.07, method="per_pitch_dtw")
    with pytest.raises(ValueError, match="invalid bpm"):
        _ = generate_events(
            ref=ref,
            attempt=attempt,
            alignment=alignment,
            meta=meta,
        )


def test_generate_events_rejects_non_positive_beats_per_measure() -> None:
    meta = _meta()
    meta["time_signature"]["beats_per_measure"] = 0
    ref = [_note(60, 0.0, dur_sec=1.0, name="C4")]
    attempt = [_note(60, 0.07, dur_sec=1.0, name="C4")]
    alignment = AlignmentResult(path=[(0, 0)], cost=0.07, method="per_pitch_dtw")
    with pytest.raises(ValueError, match="beats_per_measure must be > 0"):
        _ = generate_events(
            ref=ref,
            attempt=attempt,
            alignment=alignment,
            meta=meta,
        )


def test_generate_events_rejects_negative_chord_window_ms() -> None:
    meta = _meta()
    meta["tolerance"]["chord_window_ms"] = -1
    ref = [_note(60, 0.0, dur_sec=1.0, name="C4")]
    attempt = [_note(60, 0.07, dur_sec=1.0, name="C4")]
    alignment = AlignmentResult(path=[(0, 0)], cost=0.07, method="per_pitch_dtw")
    with pytest.raises(ValueError, match="invalid chord_window_ms"):
        _ = generate_events(
            ref=ref,
            attempt=attempt,
            alignment=alignment,
            meta=meta,
        )


def test_generate_events_rejects_negative_match_tol_ms() -> None:
    meta = _meta()
    meta["tolerance"]["match_tol_ms"] = -1
    ref = [_note(60, 0.0, dur_sec=1.0, name="C4")]
    attempt = [_note(60, 0.07, dur_sec=1.0, name="C4")]
    alignment = AlignmentResult(path=[(0, 0)], cost=0.07, method="per_pitch_dtw")
    with pytest.raises(ValueError, match="invalid match_tol_ms"):
        _ = generate_events(
            ref=ref,
            attempt=attempt,
            alignment=alignment,
            meta=meta,
        )


def test_generate_events_rejects_inverted_duration_ratios() -> None:
    meta = _meta()
    meta["tolerance"]["duration_short_ratio"] = 1.6
    meta["tolerance"]["duration_long_ratio"] = 1.5
    ref = [_note(60, 0.0, dur_sec=1.0, name="C4")]
    attempt = [_note(60, 0.07, dur_sec=1.0, name="C4")]
    alignment = AlignmentResult(path=[(0, 0)], cost=0.07, method="per_pitch_dtw")
    with pytest.raises(ValueError, match="invalid duration ratios"):
        _ = generate_events(
            ref=ref,
            attempt=attempt,
            alignment=alignment,
            meta=meta,
        )


def test_generate_events_rejects_invalid_timing_grades_order() -> None:
    meta = _meta()
    meta["tolerance"]["timing_grades"] = {
        "great_ms": 60,
        "good_ms": 40,
        "rushed_dragged_ms": 100,
    }
    ref = [_note(60, 0.0, dur_sec=1.0, name="C4")]
    attempt = [_note(60, 0.07, dur_sec=1.0, name="C4")]
    alignment = AlignmentResult(path=[(0, 0)], cost=0.07, method="per_pitch_dtw")
    with pytest.raises(ValueError, match="invalid timing_grades"):
        _ = generate_events(
            ref=ref,
            attempt=attempt,
            alignment=alignment,
            meta=meta,
        )


def test_generate_events_rejects_non_positive_segment_start_measure() -> None:
    meta = _meta()
    meta["segments"] = [{"segment_id": "verse1", "start_measure": 0, "end_measure": 1}]
    ref = [_note(60, 0.0, dur_sec=1.0, name="C4")]
    attempt = [_note(60, 0.07, dur_sec=1.0, name="C4")]
    alignment = AlignmentResult(path=[(0, 0)], cost=0.07, method="per_pitch_dtw")
    with pytest.raises(ValueError, match="invalid segment start_measure"):
        _ = generate_events(
            ref=ref,
            attempt=attempt,
            alignment=alignment,
            meta=meta,
            segment_id="verse1",
        )
