from __future__ import annotations

from xpiano.alignment import DTWAligner, HMMAligner
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


def test_hmm_aligner_matches_with_global_tempo_drift() -> None:
    ref = [_note(60, 0.0), _note(62, 1.0), _note(64, 2.0), _note(65, 3.0)]
    attempt = [_note(60, 0.2), _note(62, 1.5), _note(64, 2.8), _note(65, 4.0)]

    result = HMMAligner().align_offline(ref, attempt)
    assert result.method == "hmm_viterbi"
    assert result.path == [(0, 0), (1, 1), (2, 2), (3, 3)]
    assert result.warp_scale is not None
    assert result.warp_offset_sec is not None


def test_hmm_aligner_skips_inserted_wrong_pitch_without_drifting() -> None:
    ref = [_note(60, 0.0), _note(62, 0.5), _note(64, 1.0), _note(65, 1.5)]
    attempt = [
        _note(60, 0.0),
        _note(70, 0.25),  # inserted error note
        _note(62, 0.52),
        _note(64, 1.04),
        _note(65, 1.55),
    ]

    result = HMMAligner().align_offline(ref, attempt)
    assert result.path == [(0, 0), (1, 2), (2, 3), (3, 4)]
