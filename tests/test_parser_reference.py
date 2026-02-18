from __future__ import annotations

from pathlib import Path

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


def test_list_songs_reports_reference(xpiano_home: Path, sample_midi_path: Path) -> None:
    reference.import_reference(sample_midi_path, song_id="twinkle")
    songs = reference.list_songs()
    assert len(songs) == 1
    assert songs[0].song_id == "twinkle"
    assert songs[0].has_reference is True
