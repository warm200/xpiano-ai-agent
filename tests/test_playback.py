from __future__ import annotations

from pathlib import Path

import mido
import pytest

from xpiano.models import PlayResult
from xpiano.playback import play
from xpiano.reference import save_meta


def _write_simple_midi(path: Path) -> None:
    mid = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage(
        "set_tempo", tempo=mido.bpm2tempo(120), time=0))
    track.append(mido.MetaMessage("time_signature",
                 numerator=4, denominator=4, time=0))
    track.append(mido.Message("note_on", note=60, velocity=80, time=0))
    track.append(mido.Message("note_off", note=60, velocity=0, time=480))
    track.append(mido.MetaMessage("end_of_track", time=1))
    mid.save(str(path))


def _meta() -> dict:
    return {
        "song_id": "twinkle",
        "time_signature": {"beats_per_measure": 4, "beat_unit": 4},
        "bpm": 120,
        "segments": [{"segment_id": "verse1", "start_measure": 1, "end_measure": 4}],
        "tolerance": {"match_tol_ms": 80, "timing_grades": {"great_ms": 25, "good_ms": 50, "rushed_dragged_ms": 100}},
    }


def _meta_segment2() -> dict:
    return {
        "song_id": "twinkle",
        "time_signature": {"beats_per_measure": 4, "beat_unit": 4},
        "bpm": 120,
        "segments": [{"segment_id": "verse2", "start_measure": 2, "end_measure": 3}],
        "tolerance": {"match_tol_ms": 80, "timing_grades": {"great_ms": 25, "good_ms": 50, "rushed_dragged_ms": 100}},
    }


def test_play_reference_mode_slices_measures(xpiano_home: Path, monkeypatch) -> None:
    song_dir = xpiano_home / "songs" / "twinkle"
    song_dir.mkdir(parents=True, exist_ok=True)
    ref_mid = song_dir / "reference.mid"
    _write_simple_midi(ref_mid)
    save_meta(song_id="twinkle", meta=_meta())

    captured: dict = {}

    def fake_play_midi(**kwargs):
        captured.update(kwargs)
        return PlayResult(status="played", duration_sec=1.0)

    monkeypatch.setattr("xpiano.playback.midi_io.play_midi", fake_play_midi)
    result = play(
        source="reference",
        song_id="twinkle",
        segment_id="verse1",
        measures="2-3",
        data_dir=xpiano_home,
    )
    assert result.status == "played"
    assert captured["start_sec"] == 2.0
    assert captured["end_sec"] == 6.0


def test_play_comparison_mode_calls_twice(xpiano_home: Path, monkeypatch) -> None:
    song_dir = xpiano_home / "songs" / "twinkle"
    attempts_dir = song_dir / "attempts"
    attempts_dir.mkdir(parents=True, exist_ok=True)
    ref_mid = song_dir / "reference.mid"
    attempt_mid = attempts_dir / "20260101_120000.mid"
    _write_simple_midi(ref_mid)
    _write_simple_midi(attempt_mid)
    save_meta(song_id="twinkle", meta=_meta())

    calls: list[dict] = []

    def fake_play_midi(**kwargs):
        calls.append(kwargs)
        return PlayResult(status="played", duration_sec=1.0)

    monkeypatch.setattr("xpiano.playback.midi_io.play_midi", fake_play_midi)
    result = play(
        source="comparison",
        song_id="twinkle",
        segment_id="verse1",
        data_dir=xpiano_home,
        delay_between=0.1,
    )
    assert result.status == "played"
    assert len(calls) == 2


def test_play_reference_uses_absolute_measure_time(xpiano_home: Path, monkeypatch) -> None:
    song_dir = xpiano_home / "songs" / "twinkle"
    song_dir.mkdir(parents=True, exist_ok=True)
    ref_mid = song_dir / "reference.mid"
    _write_simple_midi(ref_mid)
    save_meta(song_id="twinkle", meta=_meta_segment2())

    captured: dict = {}

    def fake_play_midi(**kwargs):
        captured.update(kwargs)
        return PlayResult(status="played", duration_sec=1.0)

    monkeypatch.setattr("xpiano.playback.midi_io.play_midi", fake_play_midi)
    _ = play(
        source="reference",
        song_id="twinkle",
        segment_id="verse2",
        measures="2-2",
        data_dir=xpiano_home,
    )
    assert captured["start_sec"] == 2.0
    assert captured["end_sec"] == 4.0


def test_play_comparison_uses_relative_attempt_and_absolute_reference(xpiano_home: Path, monkeypatch) -> None:
    song_dir = xpiano_home / "songs" / "twinkle"
    attempts_dir = song_dir / "attempts"
    attempts_dir.mkdir(parents=True, exist_ok=True)
    ref_mid = song_dir / "reference.mid"
    attempt_mid = attempts_dir / "20260101_120000.mid"
    _write_simple_midi(ref_mid)
    _write_simple_midi(attempt_mid)
    save_meta(song_id="twinkle", meta=_meta_segment2())

    calls: list[dict] = []

    def fake_play_midi(**kwargs):
        calls.append(kwargs)
        return PlayResult(status="played", duration_sec=1.0)

    monkeypatch.setattr("xpiano.playback.midi_io.play_midi", fake_play_midi)
    _ = play(
        source="comparison",
        song_id="twinkle",
        segment_id="verse2",
        measures="2-2",
        data_dir=xpiano_home,
        delay_between=0.01,
    )
    assert len(calls) == 2
    assert calls[0]["start_sec"] == 0.0
    assert calls[0]["end_sec"] == 2.0
    assert calls[1]["start_sec"] == 2.0
    assert calls[1]["end_sec"] == 4.0


def test_play_rejects_reverse_measure_range(xpiano_home: Path) -> None:
    song_dir = xpiano_home / "songs" / "twinkle"
    song_dir.mkdir(parents=True, exist_ok=True)
    _write_simple_midi(song_dir / "reference.mid")
    save_meta(song_id="twinkle", meta=_meta())
    with pytest.raises(ValueError, match="invalid measure range"):
        play(
            source="reference",
            song_id="twinkle",
            segment_id="verse1",
            measures="3-2",
            data_dir=xpiano_home,
        )


def test_play_rejects_measure_outside_segment(xpiano_home: Path) -> None:
    song_dir = xpiano_home / "songs" / "twinkle"
    song_dir.mkdir(parents=True, exist_ok=True)
    _write_simple_midi(song_dir / "reference.mid")
    save_meta(song_id="twinkle", meta=_meta_segment2())
    with pytest.raises(ValueError, match="outside segment"):
        play(
            source="reference",
            song_id="twinkle",
            segment_id="verse2",
            measures="1-2",
            data_dir=xpiano_home,
        )


def test_play_rejects_invalid_highlight_pitch(xpiano_home: Path) -> None:
    song_dir = xpiano_home / "songs" / "twinkle"
    song_dir.mkdir(parents=True, exist_ok=True)
    _write_simple_midi(song_dir / "reference.mid")
    save_meta(song_id="twinkle", meta=_meta())
    with pytest.raises(ValueError, match="invalid highlight pitches"):
        play(
            source="reference",
            song_id="twinkle",
            segment_id="verse1",
            highlight_pitches=["H9"],
            data_dir=xpiano_home,
        )


def test_play_accepts_comma_separated_highlight_pitch_values(xpiano_home: Path, monkeypatch) -> None:
    song_dir = xpiano_home / "songs" / "twinkle"
    song_dir.mkdir(parents=True, exist_ok=True)
    _write_simple_midi(song_dir / "reference.mid")
    save_meta(song_id="twinkle", meta=_meta())

    captured: dict = {}

    def fake_play_midi(**kwargs):
        captured.update(kwargs)
        return PlayResult(status="played", duration_sec=1.0)

    monkeypatch.setattr("xpiano.playback.midi_io.play_midi", fake_play_midi)
    result = play(
        source="reference",
        song_id="twinkle",
        segment_id="verse1",
        highlight_pitches=["C4,E4"],
        data_dir=xpiano_home,
    )
    assert result.status == "played"
    assert captured["highlight_pitches"] == {60, 64}


def test_play_rejects_invalid_segment_range(xpiano_home: Path) -> None:
    song_dir = xpiano_home / "songs" / "twinkle"
    song_dir.mkdir(parents=True, exist_ok=True)
    _write_simple_midi(song_dir / "reference.mid")
    meta = _meta()
    meta["segments"][0]["start_measure"] = 4
    meta["segments"][0]["end_measure"] = 2
    save_meta(song_id="twinkle", meta=meta)
    with pytest.raises(ValueError, match="invalid segment range"):
        play(
            source="reference",
            song_id="twinkle",
            segment_id="verse1",
            data_dir=xpiano_home,
        )
