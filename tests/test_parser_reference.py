from __future__ import annotations

from pathlib import Path

import mido

from xpiano import parser, reference


def test_midi_to_notes_parses_note_events(sample_midi_path: Path) -> None:
    notes = parser.midi_to_notes(sample_midi_path)
    assert len(notes) == 2
    assert notes[0].pitch_name == "C4"
    assert notes[1].pitch_name == "E4"


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
