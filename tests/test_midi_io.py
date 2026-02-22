from __future__ import annotations

from contextlib import contextmanager
from threading import Event

import mido

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


def test_record_skips_realtime_messages(monkeypatch) -> None:
    @contextmanager
    def _fake_input_port_with_realtime():
        class _Port:
            def __init__(self) -> None:
                self.calls = 0

            def iter_pending(self):
                self.calls += 1
                if self.calls == 1:
                    return [
                        mido.Message("clock"),
                        mido.Message("note_on", note=60, velocity=100, channel=0),
                    ]
                return []

        yield _Port()

    monkeypatch.setattr(
        "xpiano.midi_io.mido.open_input",
        lambda port: _fake_input_port_with_realtime(),
    )
    midi = midi_io.record(
        port=None,
        duration_sec=0.01,
        count_in_beats=0,
        bpm=90.0,
        beats_per_measure=4,
        beat_unit=4,
    )
    message_types = [msg.type for msg in midi.tracks[0] if not msg.is_meta]
    assert "clock" not in message_types
    assert "note_on" in message_types


def test_record_stops_when_enter_event_is_set(monkeypatch) -> None:
    @contextmanager
    def _fake_input_port_with_notes():
        class _Port:
            def iter_pending(self):
                return [mido.Message("note_on", note=60, velocity=100, channel=0)]

        yield _Port()

    stop_event = Event()
    stop_event.set()
    monkeypatch.setattr(
        "xpiano.midi_io._start_enter_listener",
        lambda stop_on_enter: stop_event if stop_on_enter else None,
    )
    monkeypatch.setattr(
        "xpiano.midi_io.mido.open_input",
        lambda port: _fake_input_port_with_notes(),
    )
    midi = midi_io.record(
        port=None,
        duration_sec=None,
        count_in_beats=0,
        bpm=90.0,
        beats_per_measure=4,
        beat_unit=4,
        stop_on_enter=True,
    )
    note_events = [msg for msg in midi.tracks[0] if not msg.is_meta]
    assert note_events == []


def test_list_devices_returns_empty_when_backend_queries_fail(monkeypatch) -> None:
    monkeypatch.setattr(
        "xpiano.midi_io.mido.get_input_names",
        lambda: (_ for _ in ()).throw(OSError("input backend unavailable")),
    )
    monkeypatch.setattr(
        "xpiano.midi_io.mido.get_output_names",
        lambda: (_ for _ in ()).throw(RuntimeError("output backend unavailable")),
    )
    devices = midi_io.list_devices()
    assert devices == []


def test_list_devices_keeps_output_when_input_query_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        "xpiano.midi_io.mido.get_input_names",
        lambda: (_ for _ in ()).throw(OSError("input backend unavailable")),
    )
    monkeypatch.setattr("xpiano.midi_io.mido.get_output_names", lambda: ["Mock Out"])
    devices = midi_io.list_devices()
    assert len(devices) == 1
    assert devices[0].kind == "output"
    assert devices[0].name == "Mock Out"


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


def test_record_rejects_non_positive_bpm() -> None:
    try:
        _ = midi_io.record(
            port=None,
            duration_sec=0.01,
            count_in_beats=0,
            bpm=0,
            beats_per_measure=4,
            beat_unit=4,
        )
    except ValueError as exc:
        assert "bpm must be in range 20..240" in str(exc)
    else:
        raise AssertionError("expected ValueError for non-positive bpm")


def test_record_rejects_out_of_range_bpm() -> None:
    try:
        _ = midi_io.record(
            port=None,
            duration_sec=0.01,
            count_in_beats=0,
            bpm=241,
            beats_per_measure=4,
            beat_unit=4,
        )
    except ValueError as exc:
        assert "bpm must be in range 20..240" in str(exc)
    else:
        raise AssertionError("expected ValueError for out-of-range bpm")


def test_record_rejects_out_of_range_beats_per_measure() -> None:
    try:
        _ = midi_io.record(
            port=None,
            duration_sec=0.01,
            count_in_beats=0,
            bpm=90.0,
            beats_per_measure=13,
            beat_unit=4,
        )
    except ValueError as exc:
        assert "beats_per_measure must be <= 12" in str(exc)
    else:
        raise AssertionError("expected ValueError for out-of-range beats_per_measure")


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


def test_record_rejects_non_positive_tail_idle_sec() -> None:
    try:
        _ = midi_io.record(
            port=None,
            duration_sec=0.01,
            count_in_beats=0,
            bpm=90.0,
            beats_per_measure=4,
            beat_unit=4,
            tail_idle_sec=0,
        )
    except ValueError as exc:
        assert "tail_idle_sec must be > 0" in str(exc)
    else:
        raise AssertionError("expected ValueError for non-positive tail_idle_sec")


def test_record_extends_until_idle_after_planned_duration(monkeypatch) -> None:
    @contextmanager
    def _fake_input_port_with_late_note():
        class _Port:
            def __init__(self) -> None:
                self.calls = 0

            def iter_pending(self):
                self.calls += 1
                if self.calls == 1:
                    return [mido.Message("note_on", note=60, velocity=90, channel=0)]
                if self.calls == 3:
                    # Arrives after planned duration, should still be captured.
                    return [mido.Message("note_on", note=62, velocity=90, channel=0)]
                return []

        yield _Port()

    clock = {"now": 0.0}

    def _mono() -> float:
        return clock["now"]

    def _sleep(sec: float) -> None:
        # Advance quickly to avoid slow test loops.
        clock["now"] += max(0.02, float(sec))

    monkeypatch.setattr(
        "xpiano.midi_io.mido.open_input",
        lambda port: _fake_input_port_with_late_note(),
    )
    monkeypatch.setattr("xpiano.midi_io.time.monotonic", _mono)
    monkeypatch.setattr("xpiano.midi_io.time.sleep", _sleep)

    midi = midi_io.record(
        port=None,
        duration_sec=0.01,
        count_in_beats=0,
        bpm=90.0,
        beats_per_measure=4,
        beat_unit=4,
        tail_idle_sec=0.5,
    )

    note_events = [msg for msg in midi.tracks[0] if not msg.is_meta]
    notes = [msg.note for msg in note_events if msg.type == "note_on"]
    assert notes == [60, 62]


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


def test_play_midi_returns_no_device_when_output_query_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        "xpiano.midi_io.mido.get_output_names",
        lambda: (_ for _ in ()).throw(RuntimeError("output backend unavailable")),
    )
    result = midi_io.play_midi(
        port=None,
        midi=midi_io.mido.MidiFile(),
    )
    assert result.status == "no_device"
    assert result.duration_sec == 0.0
