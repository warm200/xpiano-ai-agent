from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from xpiano.cli import app
from xpiano.models import PlayResult

runner = CliRunner()


def test_practice_command_calls_play_midi(
    sample_midi_path: Path,
    monkeypatch,
) -> None:
    calls: list[dict] = []

    def _fake_play_midi(**kwargs):
        calls.append(kwargs)
        return PlayResult(status="played", duration_sec=1.2)

    monkeypatch.setattr("xpiano.cli.midi_io.play_midi", _fake_play_midi)
    result = runner.invoke(
        app,
        [
            "practice",
            "--file",
            str(sample_midi_path),
            "--output-port",
            "out-1",
            "--bpm",
            "90",
            "--start-sec",
            "0.5",
            "--end-sec",
            "2.0",
        ],
    )
    assert result.exit_code == 0
    assert "Practice status: played" in result.stdout
    assert len(calls) == 1
    assert calls[0]["port"] == "out-1"
    assert calls[0]["bpm"] == 90
    assert calls[0]["start_sec"] == 0.5
    assert calls[0]["end_sec"] == 2.0
    assert calls[0]["highlight_pitches"] is None


def test_practice_command_rejects_non_positive_bpm(sample_midi_path: Path) -> None:
    result = runner.invoke(
        app,
        ["practice", "--file", str(sample_midi_path), "--bpm", "0"],
    )
    assert result.exit_code != 0


def test_practice_command_rejects_out_of_range_bpm(sample_midi_path: Path) -> None:
    result = runner.invoke(
        app,
        ["practice", "--file", str(sample_midi_path), "--bpm", "241"],
    )
    assert result.exit_code != 0


def test_practice_command_rejects_negative_start_sec(sample_midi_path: Path) -> None:
    result = runner.invoke(
        app,
        ["practice", "--file", str(sample_midi_path), "--start-sec", "-0.1"],
    )
    assert result.exit_code != 0


def test_practice_command_rejects_negative_end_sec(sample_midi_path: Path) -> None:
    result = runner.invoke(
        app,
        ["practice", "--file", str(sample_midi_path), "--end-sec", "-0.1"],
    )
    assert result.exit_code != 0


def test_practice_command_rejects_end_before_start(sample_midi_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "practice",
            "--file",
            str(sample_midi_path),
            "--start-sec",
            "2.0",
            "--end-sec",
            "1.9",
        ],
    )
    assert result.exit_code != 0


def test_practice_command_surfaces_runtime_error(
    sample_midi_path: Path,
    monkeypatch,
) -> None:
    def _raise(**kwargs):
        _ = kwargs
        raise RuntimeError("player unavailable")

    monkeypatch.setattr("xpiano.cli.midi_io.play_midi", _raise)
    result = runner.invoke(
        app,
        ["practice", "--file", str(sample_midi_path)],
    )
    assert result.exit_code != 0
    assert result.exception is not None
    assert not isinstance(result.exception, RuntimeError)
