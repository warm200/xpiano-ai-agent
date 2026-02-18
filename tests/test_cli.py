from __future__ import annotations

from pathlib import Path

import mido
from typer.testing import CliRunner

from xpiano.cli import app

runner = CliRunner()


def test_setup_and_list_command(xpiano_home: Path) -> None:
    result = runner.invoke(
        app,
        [
            "setup",
            "--song",
            "twinkle",
            "--segment",
            "verse1",
            "--bpm",
            "80",
            "--time-sig",
            "4/4",
            "--measures",
            "4",
        ],
    )
    assert result.exit_code == 0

    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "twinkle" in result.stdout


def _recorded_midi() -> mido.MidiFile:
    mid = mido.MidiFile(ticks_per_beat=480)
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
    track.append(mido.MetaMessage("end_of_track", time=1))
    return mid


def test_record_and_report_commands(
    xpiano_home: Path,
    sample_midi_path: Path,
    monkeypatch,
) -> None:
    result = runner.invoke(
        app, ["import", "--file", str(sample_midi_path), "--song", "twinkle"])
    assert result.exit_code == 0

    monkeypatch.setattr("xpiano.cli.midi_io.record",
                        lambda **_: _recorded_midi())
    record_result = runner.invoke(
        app, ["record", "--song", "twinkle", "--segment", "default"])
    assert record_result.exit_code == 0
    assert "Saved report:" in record_result.stdout

    report_result = runner.invoke(app, ["report", "--song", "twinkle"])
    assert report_result.exit_code == 0
    assert "match_rate=" in report_result.stdout
