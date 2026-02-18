from __future__ import annotations

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
