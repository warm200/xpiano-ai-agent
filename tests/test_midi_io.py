from __future__ import annotations

from contextlib import contextmanager

from xpiano import midi_io


@contextmanager
def _fake_input_port():
    class _Port:
        def iter_pending(self):
            return []

    yield _Port()


def test_record_writes_configured_time_signature(monkeypatch) -> None:
    monkeypatch.setattr("xpiano.midi_io.mido.open_input", lambda port: _fake_input_port())
    midi = midi_io.record(
        port=None,
        duration_sec=0.01,
        count_in_beats=0,
        bpm=90.0,
        beats_per_measure=3,
        beat_unit=8,
    )
    time_sig_msgs = [
        msg
        for track in midi.tracks
        for msg in track
        if getattr(msg, "type", None) == "time_signature"
    ]
    assert len(time_sig_msgs) == 1
    assert time_sig_msgs[0].numerator == 3
    assert time_sig_msgs[0].denominator == 8


def test_record_rejects_non_positive_beats_per_measure() -> None:
    try:
        _ = midi_io.record(
            port=None,
            duration_sec=0.01,
            count_in_beats=0,
            bpm=90.0,
            beats_per_measure=0,
            beat_unit=4,
        )
    except ValueError as exc:
        assert "beats_per_measure must be > 0" in str(exc)
    else:
        raise AssertionError("expected ValueError for non-positive beats_per_measure")


def test_record_rejects_non_positive_beat_unit() -> None:
    try:
        _ = midi_io.record(
            port=None,
            duration_sec=0.01,
            count_in_beats=0,
            bpm=90.0,
            beats_per_measure=4,
            beat_unit=0,
        )
    except ValueError as exc:
        assert "beat_unit must be > 0" in str(exc)
    else:
        raise AssertionError("expected ValueError for non-positive beat_unit")


def test_record_rejects_unsupported_beat_unit() -> None:
    try:
        _ = midi_io.record(
            port=None,
            duration_sec=0.01,
            count_in_beats=0,
            bpm=90.0,
            beats_per_measure=4,
            beat_unit=3,
        )
    except ValueError as exc:
        assert "beat_unit must be one of 1,2,4,8,16" in str(exc)
    else:
        raise AssertionError("expected ValueError for unsupported beat_unit")


def test_play_midi_rejects_non_positive_bpm_override() -> None:
    try:
        _ = midi_io.play_midi(
            port=None,
            midi=midi_io.mido.MidiFile(),
            bpm=0,
        )
    except ValueError as exc:
        assert "bpm must be in range 20..240" in str(exc)
    else:
        raise AssertionError("expected ValueError for non-positive bpm override")


def test_play_midi_rejects_out_of_range_bpm_override() -> None:
    try:
        _ = midi_io.play_midi(
            port=None,
            midi=midi_io.mido.MidiFile(),
            bpm=241,
        )
    except ValueError as exc:
        assert "bpm must be in range 20..240" in str(exc)
    else:
        raise AssertionError("expected ValueError for out-of-range bpm override")


def test_play_midi_rejects_negative_start_sec() -> None:
    try:
        _ = midi_io.play_midi(
            port=None,
            midi=midi_io.mido.MidiFile(),
            start_sec=-0.1,
        )
    except ValueError as exc:
        assert "start_sec must be >= 0" in str(exc)
    else:
        raise AssertionError("expected ValueError for negative start_sec")


def test_play_midi_rejects_negative_end_sec() -> None:
    try:
        _ = midi_io.play_midi(
            port=None,
            midi=midi_io.mido.MidiFile(),
            end_sec=-0.1,
        )
    except ValueError as exc:
        assert "end_sec must be >= 0" in str(exc)
    else:
        raise AssertionError("expected ValueError for negative end_sec")


def test_play_midi_rejects_end_before_start() -> None:
    try:
        _ = midi_io.play_midi(
            port=None,
            midi=midi_io.mido.MidiFile(),
            start_sec=2.0,
            end_sec=1.0,
        )
    except ValueError as exc:
        assert "end_sec must be >= start_sec" in str(exc)
    else:
        raise AssertionError("expected ValueError when end_sec < start_sec")
