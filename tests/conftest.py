from __future__ import annotations

from pathlib import Path

import mido
import pytest


@pytest.fixture()
def xpiano_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".xpiano"
    monkeypatch.setenv("XPIANO_HOME", str(home))
    return home


@pytest.fixture()
def sample_midi_path(tmp_path: Path) -> Path:
    midi_path = tmp_path / "sample.mid"
    mid = mido.MidiFile()
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage(
        "set_tempo", tempo=mido.bpm2tempo(100), time=0))
    track.append(mido.MetaMessage("time_signature",
                 numerator=4, denominator=4, time=0))
    track.append(mido.Message("note_on", note=60, velocity=80, time=0))
    track.append(mido.Message("note_off", note=60, velocity=0, time=480))
    track.append(mido.Message("note_on", note=64, velocity=80, time=0))
    track.append(mido.Message("note_off", note=64, velocity=0, time=480))
    mid.save(str(midi_path))
    return midi_path
