from __future__ import annotations

from xpiano.alignment import DTWAligner
from xpiano.models import NoteEvent


def _note(pitch: int, start_sec: float) -> NoteEvent:
    return NoteEvent(
        pitch=pitch,
        pitch_name="C4",
        start_sec=start_sec,
        end_sec=start_sec + 0.5,
        dur_sec=0.5,
        velocity=80,
        hand="R",
    )


def test_dtw_aligner_matches_same_pitch_sequences() -> None:
    ref = [_note(60, 0.0), _note(60, 1.0), _note(60, 2.0)]
    attempt = [_note(60, 0.02), _note(60, 1.03), _note(60, 1.98)]

    result = DTWAligner().align_offline(ref, attempt)
    assert result.method == "per_pitch_dtw"
    assert result.path == [(0, 0), (1, 1), (2, 2)]


def test_dtw_aligner_handles_missing_notes() -> None:
    ref = [_note(60, 0.0), _note(60, 1.0), _note(60, 2.0)]
    attempt = [_note(60, 0.0), _note(60, 2.0)]

    result = DTWAligner().align_offline(ref, attempt)
    assert len(result.path) == 2
    assert result.path[0] == (0, 0)
