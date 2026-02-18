from __future__ import annotations

import json
from pathlib import Path

import mido
from typer.testing import CliRunner

from xpiano.cli import app
from xpiano.models import PlayResult
from xpiano.wait_mode import WaitModeResult

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


def test_coach_command_with_mocked_provider(
    xpiano_home: Path,
    monkeypatch,
) -> None:
    reports_dir = xpiano_home / "songs" / "twinkle" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "20260101_120000.json"
    report_payload = {
        "song_id": "twinkle",
        "segment_id": "verse1",
        "status": "ok",
        "summary": {
            "counts": {"ref_notes": 10, "attempt_notes": 10, "matched": 8, "missing": 2, "extra": 1},
            "match_rate": 0.8,
            "top_problems": ["M2 wrong_pitch x2"],
        },
        "events": [],
    }
    report_path.write_text(json.dumps(report_payload), encoding="utf-8")

    monkeypatch.setattr("xpiano.cli.create_provider", lambda cfg: object())
    monkeypatch.setattr(
        "xpiano.cli.get_coaching",
        lambda report, provider, max_retries: {
            "goal": "Fix bar 2",
            "top_issues": [{"title": "Wrong pitch", "why": "finger slip", "evidence": ["M2 wrong_pitch x2"]}],
            "drills": [
                {
                    "name": "Slow loop",
                    "minutes": 7,
                    "bpm": 45,
                    "how": ["Loop M2", "Count beats"],
                    "reps": "5x",
                    "focus_measures": "2",
                },
                {
                    "name": "Connect bars",
                    "minutes": 8,
                    "bpm": 50,
                    "how": ["Play M2-M3", "No pause"],
                    "reps": "4x",
                    "focus_measures": "2-3",
                },
            ],
            "pass_conditions": {
                "before_speed_up": ["No wrong notes", "Stable timing"],
                "speed_up_rule": "+5 BPM after 2 clean reps",
            },
            "next_recording": {"what_to_record": "M2-M3", "tips": ["Relax wrist", "Watch beat 1"]},
        },
    )

    result = runner.invoke(app, ["coach", "--song", "twinkle"])
    assert result.exit_code == 0
    assert "Saved coaching:" in result.stdout


def test_playback_command_calls_engine(monkeypatch) -> None:
    monkeypatch.setattr(
        "xpiano.cli.playback_play",
        lambda **kwargs: PlayResult(status="played", duration_sec=1.2),
    )
    result = runner.invoke(
        app,
        ["playback", "--song", "twinkle", "--segment",
            "verse1", "--mode", "reference"],
    )
    assert result.exit_code == 0
    assert "Playback status: played" in result.stdout


def test_wait_command_calls_engine(monkeypatch) -> None:
    monkeypatch.setattr(
        "xpiano.cli.run_wait_mode",
        lambda **kwargs: WaitModeResult(total_steps=4, completed=3, errors=1),
    )
    result = runner.invoke(
        app,
        ["wait", "--song", "twinkle", "--segment", "verse1"],
    )
    assert result.exit_code == 0
    assert "completed=3/4 errors=1" in result.stdout
