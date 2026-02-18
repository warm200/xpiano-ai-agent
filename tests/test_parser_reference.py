from __future__ import annotations

from datetime import datetime
from pathlib import Path

import mido

from xpiano import parser, reference


def test_midi_to_notes_parses_note_events(sample_midi_path: Path) -> None:
    notes = parser.midi_to_notes(sample_midi_path)
    assert len(notes) == 2
    assert notes[0].pitch_name == "C4"
    assert notes[1].pitch_name == "E4"


def test_midi_to_notes_rejects_out_of_range_hand_split(sample_midi_path: Path) -> None:
    try:
        _ = parser.midi_to_notes(sample_midi_path, hand_split=128)
    except ValueError as exc:
        assert "hand_split must be between 0 and 127" in str(exc)
    else:
        raise AssertionError("expected ValueError for out-of-range hand_split")


def test_import_reference_creates_meta_and_notes(xpiano_home: Path, sample_midi_path: Path) -> None:
    target = reference.import_reference(sample_midi_path, song_id="twinkle")
    assert target.exists()
    assert (xpiano_home / "songs" / "twinkle" /
            "reference_notes.json").exists()
    meta = reference.load_meta("twinkle")
    assert meta["song_id"] == "twinkle"
    assert len(meta["segments"]) == 1


def test_import_reference_uses_custom_segment_id(xpiano_home: Path, sample_midi_path: Path) -> None:
    _ = reference.import_reference(sample_midi_path, song_id="twinkle", segment_id="verse1")
    meta = reference.load_meta("twinkle")
    assert meta["segments"][0]["segment_id"] == "verse1"


def test_import_reference_rejects_song_id_with_path_separator(sample_midi_path: Path) -> None:
    try:
        _ = reference.import_reference(sample_midi_path, song_id="bad/name")
    except ValueError as exc:
        assert "song_id must not contain path separators" in str(exc)
    else:
        raise AssertionError("expected ValueError for invalid song_id")


def test_import_reference_rejects_segment_id_with_path_separator(sample_midi_path: Path) -> None:
    try:
        _ = reference.import_reference(sample_midi_path, song_id="twinkle", segment_id="bad/name")
    except ValueError as exc:
        assert "segment_id must not contain path separators" in str(exc)
    else:
        raise AssertionError("expected ValueError for invalid segment_id")


def test_import_reference_rejects_out_of_range_midi_bpm(sample_midi_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "xpiano.reference._extract_midi_defaults",
        lambda path: {
            "bpm": 241.0,
            "beats_per_measure": 4,
            "beat_unit": 4,
            "measures": 2,
        },
    )
    try:
        _ = reference.import_reference(sample_midi_path, song_id="twinkle")
    except ValueError as exc:
        assert "invalid reference midi tempo" in str(exc)
    else:
        raise AssertionError("expected ValueError for out-of-range midi bpm")


def test_import_reference_rejects_unsupported_midi_beat_unit(sample_midi_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "xpiano.reference._extract_midi_defaults",
        lambda path: {
            "bpm": 120.0,
            "beats_per_measure": 4,
            "beat_unit": 32,
            "measures": 2,
        },
    )
    try:
        _ = reference.import_reference(sample_midi_path, song_id="twinkle")
    except ValueError as exc:
        assert "invalid reference midi time signature" in str(exc)
    else:
        raise AssertionError("expected ValueError for unsupported midi beat_unit")


def test_import_reference_rejects_out_of_range_midi_beats_per_measure(sample_midi_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "xpiano.reference._extract_midi_defaults",
        lambda path: {
            "bpm": 120.0,
            "beats_per_measure": 13,
            "beat_unit": 4,
            "measures": 2,
        },
    )
    try:
        _ = reference.import_reference(sample_midi_path, song_id="twinkle")
    except ValueError as exc:
        assert "beats_per_measure must be <= 12" in str(exc)
    else:
        raise AssertionError("expected ValueError for out-of-range midi beats_per_measure")


def test_import_reference_refreshes_meta_tempo_from_midi(
    xpiano_home: Path,
    sample_midi_path: Path,
) -> None:
    _ = reference.import_reference(sample_midi_path, song_id="twinkle")
    meta = reference.load_meta("twinkle")
    meta["bpm"] = 80
    reference.save_meta(song_id="twinkle", meta=meta)

    _ = reference.import_reference(sample_midi_path, song_id="twinkle")
    refreshed = reference.load_meta("twinkle")
    assert refreshed["bpm"] == 100.0
    assert refreshed["time_signature"]["beats_per_measure"] == 4
    assert refreshed["time_signature"]["beat_unit"] == 4


def test_import_reference_adds_missing_segment_on_reimport(
    xpiano_home: Path,
    sample_midi_path: Path,
) -> None:
    _ = reference.import_reference(sample_midi_path, song_id="twinkle")
    _ = reference.import_reference(sample_midi_path, song_id="twinkle", segment_id="verse2")
    meta = reference.load_meta("twinkle")
    segment_ids = [str(item["segment_id"]) for item in meta["segments"]]
    assert "default" in segment_ids
    assert "verse2" in segment_ids


def test_list_songs_reports_reference(xpiano_home: Path, sample_midi_path: Path) -> None:
    reference.import_reference(sample_midi_path, song_id="twinkle")
    songs = reference.list_songs()
    assert len(songs) == 1
    assert songs[0].song_id == "twinkle"
    assert songs[0].has_reference is True


def test_save_attempt_avoids_filename_collision(xpiano_home: Path, monkeypatch) -> None:
    class _FixedDateTime:
        @classmethod
        def now(cls):
            return datetime(2026, 1, 1, 12, 0, 0)

    monkeypatch.setattr("xpiano.reference.datetime", _FixedDateTime)
    midi = mido.MidiFile(ticks_per_beat=480)
    path1 = reference.save_attempt(song_id="twinkle", midi=midi, data_dir=xpiano_home)
    path2 = reference.save_attempt(song_id="twinkle", midi=midi, data_dir=xpiano_home)
    assert path1 != path2
    assert path1.exists()
    assert path2.exists()


def test_record_reference_uses_meta_segment(
    xpiano_home: Path,
    sample_midi_path: Path,
    monkeypatch,
) -> None:
    reference.import_reference(sample_midi_path, song_id="twinkle")

    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(100), time=0))
    track.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    track.append(mido.Message("note_on", note=60, velocity=80, time=0))
    track.append(mido.Message("note_off", note=60, velocity=0, time=480))
    track.append(mido.MetaMessage("end_of_track", time=1))

    calls: list[dict] = []

    def fake_record(**kwargs):
        calls.append(kwargs)
        return midi

    monkeypatch.setattr("xpiano.reference.midi_io.record", fake_record)
    out = reference.record_reference(song_id="twinkle", segment_id="default")
    assert out.exists()
    assert len(calls) == 1
    assert calls[0]["duration_sec"] > 0
    assert calls[0]["beats_per_measure"] == 4
    assert calls[0]["beat_unit"] == 4


def test_record_reference_rejects_non_positive_count_in(
    xpiano_home: Path,
    sample_midi_path: Path,
) -> None:
    _ = reference.import_reference(sample_midi_path, song_id="twinkle")
    meta = reference.load_meta("twinkle")
    meta["segments"][0]["count_in_measures"] = 0
    try:
        reference.save_meta(song_id="twinkle", meta=meta)
    except ValueError as exc:
        assert "count_in_measures" in str(exc)
    else:
        raise AssertionError("expected ValueError for non-positive count_in_measures")


def test_record_reference_rejects_invalid_segment_range(
    xpiano_home: Path,
    sample_midi_path: Path,
) -> None:
    _ = reference.import_reference(sample_midi_path, song_id="twinkle")
    meta = reference.load_meta("twinkle")
    meta["segments"][0]["start_measure"] = 3
    meta["segments"][0]["end_measure"] = 2
    reference.save_meta(song_id="twinkle", meta=meta)
    try:
        _ = reference.record_reference(song_id="twinkle", segment_id="default")
    except ValueError as exc:
        assert "invalid segment range" in str(exc)
    else:
        raise AssertionError("expected ValueError for invalid segment range")


def test_record_reference_rejects_non_positive_segment_start(monkeypatch) -> None:
    monkeypatch.setattr(
        "xpiano.reference.load_meta",
        lambda **kwargs: {
            "song_id": "twinkle",
            "time_signature": {"beats_per_measure": 4, "beat_unit": 4},
            "bpm": 120,
            "segments": [{"segment_id": "default", "start_measure": 0, "end_measure": 1}],
        },
    )
    monkeypatch.setattr(
        "xpiano.reference.midi_io.record",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("midi_io.record should not be called")),
    )
    try:
        _ = reference.record_reference(song_id="twinkle", segment_id="default")
    except ValueError as exc:
        assert "invalid segment range" in str(exc)
    else:
        raise AssertionError("expected ValueError for non-positive segment start")


def test_record_reference_rejects_non_positive_meta_bpm(monkeypatch) -> None:
    monkeypatch.setattr(
        "xpiano.reference.load_meta",
        lambda **kwargs: {
            "song_id": "twinkle",
            "time_signature": {"beats_per_measure": 4, "beat_unit": 4},
            "bpm": 0,
            "segments": [{"segment_id": "default", "start_measure": 1, "end_measure": 1}],
        },
    )
    monkeypatch.setattr(
        "xpiano.reference.midi_io.record",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("midi_io.record should not be called")),
    )
    try:
        _ = reference.record_reference(song_id="twinkle", segment_id="default")
    except ValueError as exc:
        assert "invalid bpm" in str(exc)
    else:
        raise AssertionError("expected ValueError for non-positive bpm")


def test_record_reference_rejects_out_of_range_meta_bpm(monkeypatch) -> None:
    monkeypatch.setattr(
        "xpiano.reference.load_meta",
        lambda **kwargs: {
            "song_id": "twinkle",
            "time_signature": {"beats_per_measure": 4, "beat_unit": 4},
            "bpm": 241,
            "segments": [{"segment_id": "default", "start_measure": 1, "end_measure": 1}],
        },
    )
    monkeypatch.setattr(
        "xpiano.reference.midi_io.record",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("midi_io.record should not be called")),
    )
    try:
        _ = reference.record_reference(song_id="twinkle", segment_id="default")
    except ValueError as exc:
        assert "invalid bpm" in str(exc)
    else:
        raise AssertionError("expected ValueError for out-of-range bpm")


def test_record_reference_rejects_out_of_range_meta_beats_per_measure(monkeypatch) -> None:
    monkeypatch.setattr(
        "xpiano.reference.load_meta",
        lambda **kwargs: {
            "song_id": "twinkle",
            "time_signature": {"beats_per_measure": 13, "beat_unit": 4},
            "bpm": 120,
            "segments": [{"segment_id": "default", "start_measure": 1, "end_measure": 1}],
        },
    )
    monkeypatch.setattr(
        "xpiano.reference.midi_io.record",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("midi_io.record should not be called")),
    )
    try:
        _ = reference.record_reference(song_id="twinkle", segment_id="default")
    except ValueError as exc:
        assert "beats_per_measure must be <= 12" in str(exc)
    else:
        raise AssertionError("expected ValueError for out-of-range beats_per_measure")


def test_record_reference_rejects_unsupported_meta_beat_unit(monkeypatch) -> None:
    monkeypatch.setattr(
        "xpiano.reference.load_meta",
        lambda **kwargs: {
            "song_id": "twinkle",
            "time_signature": {"beats_per_measure": 4, "beat_unit": 3},
            "bpm": 120,
            "segments": [{"segment_id": "default", "start_measure": 1, "end_measure": 1}],
        },
    )
    monkeypatch.setattr(
        "xpiano.reference.midi_io.record",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("midi_io.record should not be called")),
    )
    try:
        _ = reference.record_reference(song_id="twinkle", segment_id="default")
    except ValueError as exc:
        assert "beat_unit must be one of 1,2,4,8,16" in str(exc)
    else:
        raise AssertionError("expected ValueError for unsupported beat_unit")
