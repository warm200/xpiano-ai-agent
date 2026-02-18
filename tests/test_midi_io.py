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
