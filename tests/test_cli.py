from __future__ import annotations

import json
from pathlib import Path

import mido
from typer.testing import CliRunner

import xpiano.cli as cli_module
from xpiano.analysis import AnalysisResult
from xpiano.cli import app
from xpiano.models import AlignmentResult, AnalysisEvent, PlayResult
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


def test_setup_trims_song_and_segment_identifiers(xpiano_home: Path) -> None:
    result = runner.invoke(
        app,
        [
            "setup",
            "--song",
            " twinkle ",
            "--segment",
            " verse1 ",
            "--bpm",
            "80",
            "--time-sig",
            "4/4",
        ],
    )
    assert result.exit_code == 0
    meta_path = xpiano_home / "songs" / "twinkle" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    segment = next(item for item in meta["segments"] if item["segment_id"] == "verse1")
    assert segment["segment_id"] == "verse1"


def test_setup_accepts_measure_range(xpiano_home: Path) -> None:
    result = runner.invoke(
        app,
        [
            "setup",
            "--song",
            "twinkle",
            "--segment",
            "verse2",
            "--bpm",
            "80",
            "--time-sig",
            "4/4",
            "--measures",
            "5-8",
        ],
    )
    assert result.exit_code == 0
    meta_path = xpiano_home / "songs" / "twinkle" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    segment = next(item for item in meta["segments"] if item["segment_id"] == "verse2")
    assert segment["start_measure"] == 5
    assert segment["end_measure"] == 8


def test_setup_accepts_measure_range_with_spaces(xpiano_home: Path) -> None:
    result = runner.invoke(
        app,
        [
            "setup",
            "--song",
            "twinkle",
            "--segment",
            "verse2",
            "--measures",
            " 5 - 8 ",
        ],
    )
    assert result.exit_code == 0
    meta_path = xpiano_home / "songs" / "twinkle" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    segment = next(item for item in meta["segments"] if item["segment_id"] == "verse2")
    assert segment["start_measure"] == 5
    assert segment["end_measure"] == 8


def test_setup_preserves_existing_range_when_measures_omitted(xpiano_home: Path) -> None:
    first = runner.invoke(
        app,
        [
            "setup",
            "--song",
            "twinkle",
            "--segment",
            "verse2",
            "--bpm",
            "80",
            "--time-sig",
            "4/4",
            "--measures",
            "5-8",
        ],
    )
    assert first.exit_code == 0

    second = runner.invoke(
        app,
        [
            "setup",
            "--song",
            "twinkle",
            "--segment",
            "verse2",
            "--bpm",
            "90",
            "--time-sig",
            "4/4",
        ],
    )
    assert second.exit_code == 0
    meta_path = xpiano_home / "songs" / "twinkle" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    segment = next(item for item in meta["segments"] if item["segment_id"] == "verse2")
    assert segment["start_measure"] == 5
    assert segment["end_measure"] == 8


def test_setup_new_segment_inherits_existing_song_bounds_when_measures_omitted(
    xpiano_home: Path,
) -> None:
    first = runner.invoke(
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
            "5-8",
        ],
    )
    assert first.exit_code == 0

    second = runner.invoke(
        app,
        [
            "setup",
            "--song",
            "twinkle",
            "--segment",
            "verse2",
            "--bpm",
            "80",
            "--time-sig",
            "4/4",
        ],
    )
    assert second.exit_code == 0
    meta_path = xpiano_home / "songs" / "twinkle" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    segment = next(item for item in meta["segments"] if item["segment_id"] == "verse2")
    assert segment["start_measure"] == 5
    assert segment["end_measure"] == 8


def test_setup_preserves_existing_count_in_when_omitted(xpiano_home: Path) -> None:
    first = runner.invoke(
        app,
        [
            "setup",
            "--song",
            "twinkle",
            "--segment",
            "verse2",
            "--bpm",
            "80",
            "--time-sig",
            "4/4",
            "--count-in",
            "3",
        ],
    )
    assert first.exit_code == 0

    second = runner.invoke(
        app,
        [
            "setup",
            "--song",
            "twinkle",
            "--segment",
            "verse2",
            "--bpm",
            "90",
            "--time-sig",
            "4/4",
        ],
    )
    assert second.exit_code == 0
    meta_path = xpiano_home / "songs" / "twinkle" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    segment = next(item for item in meta["segments"] if item["segment_id"] == "verse2")
    assert segment["count_in_measures"] == 3


def test_setup_new_segment_inherits_existing_count_in_when_omitted(
    xpiano_home: Path,
) -> None:
    first = runner.invoke(
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
            "--count-in",
            "3",
        ],
    )
    assert first.exit_code == 0

    second = runner.invoke(
        app,
        [
            "setup",
            "--song",
            "twinkle",
            "--segment",
            "verse2",
            "--bpm",
            "80",
            "--time-sig",
            "4/4",
        ],
    )
    assert second.exit_code == 0
    meta_path = xpiano_home / "songs" / "twinkle" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    segment = next(item for item in meta["segments"] if item["segment_id"] == "verse2")
    assert segment["count_in_measures"] == 3


def test_setup_preserves_existing_split_pitch_when_omitted(xpiano_home: Path) -> None:
    first = runner.invoke(
        app,
        [
            "setup",
            "--song",
            "twinkle",
            "--segment",
            "verse2",
            "--bpm",
            "80",
            "--time-sig",
            "4/4",
            "--split-pitch",
            "55",
        ],
    )
    assert first.exit_code == 0

    second = runner.invoke(
        app,
        [
            "setup",
            "--song",
            "twinkle",
            "--segment",
            "verse2",
            "--bpm",
            "90",
            "--time-sig",
            "4/4",
        ],
    )
    assert second.exit_code == 0
    meta_path = xpiano_home / "songs" / "twinkle" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["hand_split"]["split_pitch"] == 55


def test_setup_preserves_existing_time_signature_when_omitted(xpiano_home: Path) -> None:
    first = runner.invoke(
        app,
        [
            "setup",
            "--song",
            "twinkle",
            "--segment",
            "verse2",
            "--bpm",
            "80",
            "--time-sig",
            "3/4",
        ],
    )
    assert first.exit_code == 0

    second = runner.invoke(
        app,
        [
            "setup",
            "--song",
            "twinkle",
            "--segment",
            "verse2",
            "--bpm",
            "90",
        ],
    )
    assert second.exit_code == 0
    meta_path = xpiano_home / "songs" / "twinkle" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["time_signature"]["beats_per_measure"] == 3
    assert meta["time_signature"]["beat_unit"] == 4


def test_setup_preserves_existing_bpm_when_omitted(xpiano_home: Path) -> None:
    first = runner.invoke(
        app,
        [
            "setup",
            "--song",
            "twinkle",
            "--segment",
            "verse2",
            "--bpm",
            "88",
            "--time-sig",
            "4/4",
        ],
    )
    assert first.exit_code == 0

    second = runner.invoke(
        app,
        [
            "setup",
            "--song",
            "twinkle",
            "--segment",
            "verse2",
        ],
    )
    assert second.exit_code == 0
    meta_path = xpiano_home / "songs" / "twinkle" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["bpm"] == 88.0


def test_setup_rejects_invalid_measure_range() -> None:
    result = runner.invoke(
        app,
        [
            "setup",
            "--song",
            "twinkle",
            "--segment",
            "verse2",
            "--bpm",
            "80",
            "--time-sig",
            "4/4",
            "--measures",
            "8-5",
        ],
    )
    assert result.exit_code != 0


def test_setup_rejects_invalid_time_signature_beat_unit() -> None:
    result = runner.invoke(
        app,
        [
            "setup",
            "--song",
            "twinkle",
            "--segment",
            "verse2",
            "--time-sig",
            "4/3",
        ],
    )
    assert result.exit_code != 0


def test_setup_accepts_time_signature_with_spaces(xpiano_home: Path) -> None:
    result = runner.invoke(
        app,
        [
            "setup",
            "--song",
            "twinkle",
            "--segment",
            "verse2",
            "--time-sig",
            " 3 / 4 ",
        ],
    )
    assert result.exit_code == 0
    meta_path = xpiano_home / "songs" / "twinkle" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["time_signature"]["beats_per_measure"] == 3
    assert meta["time_signature"]["beat_unit"] == 4


def test_setup_rejects_non_positive_count_in() -> None:
    result = runner.invoke(
        app,
        [
            "setup",
            "--song",
            "twinkle",
            "--segment",
            "verse2",
            "--bpm",
            "80",
            "--time-sig",
            "4/4",
            "--count-in",
            "0",
        ],
    )
    assert result.exit_code != 0


def test_setup_rejects_out_of_range_split_pitch() -> None:
    result = runner.invoke(
        app,
        [
            "setup",
            "--song",
            "twinkle",
            "--segment",
            "verse2",
            "--bpm",
            "80",
            "--time-sig",
            "4/4",
            "--split-pitch",
            "128",
        ],
    )
    assert result.exit_code != 0


def test_setup_rejects_non_positive_bpm() -> None:
    result = runner.invoke(
        app,
        [
            "setup",
            "--song",
            "twinkle",
            "--segment",
            "verse2",
            "--bpm",
            "0",
            "--time-sig",
            "4/4",
        ],
    )
    assert result.exit_code != 0


def test_setup_rejects_empty_segment() -> None:
    result = runner.invoke(
        app,
        [
            "setup",
            "--song",
            "twinkle",
            "--segment",
            "",
            "--bpm",
            "80",
            "--time-sig",
            "4/4",
        ],
    )
    assert result.exit_code != 0


def test_setup_rejects_segment_with_path_separator() -> None:
    result = runner.invoke(
        app,
        [
            "setup",
            "--song",
            "twinkle",
            "--segment",
            "verse/1",
            "--bpm",
            "80",
            "--time-sig",
            "4/4",
        ],
    )
    assert result.exit_code != 0


def test_setup_rejects_segment_dotdot() -> None:
    result = runner.invoke(
        app,
        [
            "setup",
            "--song",
            "twinkle",
            "--segment",
            "..",
            "--bpm",
            "80",
            "--time-sig",
            "4/4",
        ],
    )
    assert result.exit_code != 0


def test_setup_rejects_empty_song() -> None:
    result = runner.invoke(
        app,
        [
            "setup",
            "--song",
            "",
            "--segment",
            "verse1",
            "--bpm",
            "80",
            "--time-sig",
            "4/4",
        ],
    )
    assert result.exit_code != 0


def test_setup_rejects_song_with_path_separator() -> None:
    result = runner.invoke(
        app,
        [
            "setup",
            "--song",
            "foo/bar",
            "--segment",
            "verse1",
            "--bpm",
            "80",
            "--time-sig",
            "4/4",
        ],
    )
    assert result.exit_code != 0


def test_setup_rejects_song_dotdot() -> None:
    result = runner.invoke(
        app,
        [
            "setup",
            "--song",
            "..",
            "--segment",
            "verse1",
            "--bpm",
            "80",
            "--time-sig",
            "4/4",
        ],
    )
    assert result.exit_code != 0


def test_list_shows_latest_report_stats(xpiano_home: Path) -> None:
    setup_result = runner.invoke(
        app,
        ["setup", "--song", "twinkle", "--segment", "verse1", "--bpm", "80", "--time-sig", "4/4", "--measures", "4"],
    )
    assert setup_result.exit_code == 0

    reports_dir = xpiano_home / "songs" / "twinkle" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_payload = {
        "version": "0.1",
        "song_id": "twinkle",
        "segment_id": "verse1",
        "status": "ok",
        "inputs": {"reference_mid": "ref.mid", "attempt_mid": "attempt.mid", "meta": {}},
        "summary": {
            "counts": {"ref_notes": 10, "attempt_notes": 9, "matched": 8, "missing": 2, "extra": 1},
            "match_rate": 0.8,
            "top_problems": [],
        },
        "metrics": {"timing": {}, "duration": {}, "dynamics": {}},
        "events": [],
    }
    (reports_dir / "20260101_120000.json").write_text(json.dumps(report_payload), encoding="utf-8")

    list_result = runner.invoke(app, ["list"])
    assert list_result.exit_code == 0
    assert "0.80" in list_result.stdout
    assert "2/1" in list_result.stdout


def test_import_command_accepts_segment(sample_midi_path: Path, xpiano_home: Path) -> None:
    result = runner.invoke(
        app,
        ["import", "--file", str(sample_midi_path), "--song", "twinkle", "--segment", "verse1"],
    )
    assert result.exit_code == 0
    meta_path = xpiano_home / "songs" / "twinkle" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["segments"][0]["segment_id"] == "verse1"


def test_import_command_trims_song_and_segment(sample_midi_path: Path, xpiano_home: Path) -> None:
    result = runner.invoke(
        app,
        ["import", "--file", str(sample_midi_path), "--song", " twinkle ", "--segment", " verse1 "],
    )
    assert result.exit_code == 0
    meta_path = xpiano_home / "songs" / "twinkle" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["song_id"] == "twinkle"
    assert meta["segments"][0]["segment_id"] == "verse1"


def test_import_command_rejects_song_with_path_separator(sample_midi_path: Path) -> None:
    result = runner.invoke(
        app,
        ["import", "--file", str(sample_midi_path), "--song", "foo/bar"],
    )
    assert result.exit_code != 0


def test_import_command_rejects_empty_segment(sample_midi_path: Path) -> None:
    result = runner.invoke(
        app,
        ["import", "--file", str(sample_midi_path), "--song", "twinkle", "--segment", ""],
    )
    assert result.exit_code != 0


def test_import_command_rejects_segment_with_path_separator(sample_midi_path: Path) -> None:
    result = runner.invoke(
        app,
        ["import", "--file", str(sample_midi_path), "--song", "twinkle", "--segment", "verse/1"],
    )
    assert result.exit_code != 0


def test_playback_command_rejects_empty_segment() -> None:
    result = runner.invoke(
        app,
        ["playback", "--song", "twinkle", "--segment", "", "--mode", "reference"],
    )
    assert result.exit_code != 0


def test_report_command_rejects_empty_segment() -> None:
    result = runner.invoke(
        app,
        ["report", "--song", "twinkle", "--segment", ""],
    )
    assert result.exit_code != 0


def test_report_command_rejects_empty_song() -> None:
    result = runner.invoke(
        app,
        ["report", "--song", ""],
    )
    assert result.exit_code != 0


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


def test_record_command_requires_setup_and_reference(xpiano_home: Path) -> None:
    _ = xpiano_home
    result = runner.invoke(app, ["record", "--song", "twinkle", "--segment", "default"])
    assert result.exit_code != 0


def test_record_passes_segment_context_to_analyze(
    sample_midi_path: Path,
    monkeypatch,
) -> None:
    result = runner.invoke(
        app, ["import", "--file", str(sample_midi_path), "--song", "twinkle"])
    assert result.exit_code == 0

    monkeypatch.setattr("xpiano.cli.midi_io.record", lambda **_: _recorded_midi())
    captured: dict[str, object] = {}
    original_analyze = cli_module.analyze

    def _capture(*args, **kwargs):
        captured.update(kwargs)
        return original_analyze(*args, **kwargs)

    monkeypatch.setattr("xpiano.cli.analyze", _capture)

    record_result = runner.invoke(
        app, ["record", "--song", "twinkle", "--segment", "default"])
    assert record_result.exit_code == 0
    assert captured["segment_id"] == "default"
    assert captured["attempt_is_segment_relative"] is True


def test_report_command_with_segment_filter(xpiano_home: Path) -> None:
    reports_dir = xpiano_home / "songs" / "twinkle" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    def _write(name: str, segment: str, match_rate: float) -> None:
        payload = {
            "version": "0.1",
            "song_id": "twinkle",
            "segment_id": segment,
            "status": "ok",
            "inputs": {"reference_mid": "ref.mid", "attempt_mid": "attempt.mid", "meta": {}},
            "summary": {
                "counts": {"ref_notes": 10, "attempt_notes": 10, "matched": 9, "missing": 1, "extra": 0},
                "match_rate": match_rate,
                "top_problems": [],
            },
            "metrics": {"timing": {}, "duration": {}, "dynamics": {}},
            "events": [],
        }
        (reports_dir / name).write_text(json.dumps(payload), encoding="utf-8")

    _write("20260101_120000.json", "verse1", 0.55)
    _write("20260101_120100.json", "verse2", 0.80)

    result = runner.invoke(app, ["report", "--song", "twinkle", "--segment", "verse2"])
    assert result.exit_code == 0
    assert "match_rate=0.80" in result.stdout


def test_report_command_without_reports_prints_message(xpiano_home: Path) -> None:
    _ = xpiano_home
    result = runner.invoke(app, ["report", "--song", "twinkle"])
    assert result.exit_code == 0
    assert "No report history." in result.stdout


def test_report_command_invalid_report_schema_returns_error(xpiano_home: Path) -> None:
    reports_dir = xpiano_home / "songs" / "twinkle" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    bad_payload = {"song_id": "twinkle"}
    (reports_dir / "20260101_120000.json").write_text(json.dumps(bad_payload), encoding="utf-8")
    result = runner.invoke(app, ["report", "--song", "twinkle"])
    assert result.exit_code != 0


def test_record_ref_command(sample_midi_path: Path, monkeypatch) -> None:
    result = runner.invoke(
        app, ["import", "--file", str(sample_midi_path), "--song", "twinkle"])
    assert result.exit_code == 0
    monkeypatch.setattr("xpiano.cli.midi_io.record",
                        lambda **_: _recorded_midi())
    record_ref_result = runner.invoke(
        app, ["record-ref", "--song", "twinkle", "--segment", "default"])
    assert record_ref_result.exit_code == 0
    assert "Saved reference MIDI:" in record_ref_result.stdout


def test_record_ref_command_requires_setup(xpiano_home: Path) -> None:
    _ = xpiano_home
    result = runner.invoke(app, ["record-ref", "--song", "twinkle", "--segment", "default"])
    assert result.exit_code != 0


def test_record_full_tier_saves_coaching(
    sample_midi_path: Path,
    monkeypatch,
) -> None:
    result = runner.invoke(
        app, ["import", "--file", str(sample_midi_path), "--song", "twinkle"])
    assert result.exit_code == 0

    monkeypatch.setattr("xpiano.cli.midi_io.record",
                        lambda **_: _recorded_midi())
    monkeypatch.setattr("xpiano.cli.create_provider", lambda cfg: object())
    monkeypatch.setattr(
        "xpiano.cli.get_coaching",
        lambda **kwargs: {
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
    monkeypatch.setattr(
        "xpiano.cli.save_coaching",
        lambda coaching, song_id, data_dir=None: Path(
            "/tmp/fake_coaching.json"),
    )

    record_result = runner.invoke(
        app, ["record", "--song", "twinkle", "--segment", "default"])
    assert record_result.exit_code == 0
    assert "Saved coaching:" in record_result.stdout


def test_record_full_tier_falls_back_when_provider_unavailable(
    sample_midi_path: Path,
    monkeypatch,
) -> None:
    result = runner.invoke(
        app, ["import", "--file", str(sample_midi_path), "--song", "twinkle"])
    assert result.exit_code == 0

    monkeypatch.setattr("xpiano.cli.midi_io.record",
                        lambda **_: _recorded_midi())
    monkeypatch.setattr("xpiano.cli.create_provider", lambda cfg: (_ for _ in ()).throw(ValueError("missing key")))
    monkeypatch.setattr(
        "xpiano.cli.save_coaching",
        lambda coaching, song_id, data_dir=None: Path("/tmp/fallback_coaching.json"),
    )

    record_result = runner.invoke(
        app, ["record", "--song", "twinkle", "--segment", "default"])
    assert record_result.exit_code == 0
    assert "Provider unavailable" in record_result.stdout
    assert "Saved coaching:" in record_result.stdout


def test_record_too_low_skips_piano_roll_diff(
    sample_midi_path: Path,
    monkeypatch,
) -> None:
    result = runner.invoke(
        app, ["import", "--file", str(sample_midi_path), "--song", "twinkle"])
    assert result.exit_code == 0

    monkeypatch.setattr("xpiano.cli.midi_io.record", lambda **_: _recorded_midi())
    monkeypatch.setattr("xpiano.cli.render_piano_roll_diff", lambda *args, **kwargs: "SHOULD_NOT_PRINT")

    def _fake_analyze(*args, **kwargs):
        _ = args, kwargs
        return AnalysisResult(
            ref_notes=[],
            attempt_notes=[],
            events=[
                AnalysisEvent(
                    type="missing_note",
                    measure=1,
                    beat=1.0,
                    pitch=60,
                    pitch_name="C4",
                    hand="R",
                    severity="high",
                )
            ],
            metrics={"timing": {}, "duration": {}, "dynamics": {}},
            match_rate=0.1,
            quality_tier="too_low",
            alignment=AlignmentResult(path=[], cost=0.0, method="test"),
            matched=0,
        )

    monkeypatch.setattr("xpiano.cli.analyze", _fake_analyze)
    record_result = runner.invoke(
        app, ["record", "--song", "twinkle", "--segment", "default"])
    assert record_result.exit_code == 0
    assert "quality_tier=too_low" in record_result.stdout
    assert "SHOULD_NOT_PRINT" not in record_result.stdout


def test_record_rejects_invalid_segment_range(
    sample_midi_path: Path,
    xpiano_home: Path,
) -> None:
    result = runner.invoke(
        app, ["import", "--file", str(sample_midi_path), "--song", "twinkle"])
    assert result.exit_code == 0
    meta_path = xpiano_home / "songs" / "twinkle" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["segments"][0]["start_measure"] = 4
    meta["segments"][0]["end_measure"] = 2
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    record_result = runner.invoke(
        app, ["record", "--song", "twinkle", "--segment", "default"])
    assert record_result.exit_code != 0


def test_coach_command_with_mocked_provider(
    xpiano_home: Path,
    monkeypatch,
) -> None:
    reports_dir = xpiano_home / "songs" / "twinkle" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "20260101_120000.json"
    report_payload = {
        "version": "0.1",
        "song_id": "twinkle",
        "segment_id": "verse1",
        "status": "ok",
        "inputs": {"reference_mid": "ref.mid", "attempt_mid": "att.mid", "meta": {}},
        "summary": {
            "counts": {"ref_notes": 10, "attempt_notes": 10, "matched": 8, "missing": 2, "extra": 1},
            "match_rate": 0.8,
            "top_problems": ["M2 wrong_pitch x2"],
        },
        "metrics": {"timing": {}, "duration": {}, "dynamics": {}},
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


def test_coach_command_without_reports_prints_message(xpiano_home: Path) -> None:
    _ = xpiano_home
    result = runner.invoke(app, ["coach", "--song", "twinkle"])
    assert result.exit_code == 0
    assert "No report history." in result.stdout


def test_coach_command_invalid_report_schema_returns_error(xpiano_home: Path) -> None:
    reports_dir = xpiano_home / "songs" / "twinkle" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    bad_payload = {"song_id": "twinkle"}
    (reports_dir / "20260101_120000.json").write_text(json.dumps(bad_payload), encoding="utf-8")
    result = runner.invoke(app, ["coach", "--song", "twinkle"])
    assert result.exit_code != 0


def test_coach_command_with_segment_filter(
    xpiano_home: Path,
    monkeypatch,
) -> None:
    reports_dir = xpiano_home / "songs" / "twinkle" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_payload_1 = {
        "version": "0.1",
        "song_id": "twinkle",
        "segment_id": "verse1",
        "status": "ok",
        "inputs": {"reference_mid": "ref.mid", "attempt_mid": "att.mid", "meta": {}},
        "summary": {
            "counts": {"ref_notes": 10, "attempt_notes": 10, "matched": 7, "missing": 3, "extra": 1},
            "match_rate": 0.7,
            "top_problems": ["M1 wrong_pitch x2"],
        },
        "metrics": {"timing": {}, "duration": {}, "dynamics": {}},
        "events": [],
    }
    report_payload_2 = {
        "version": "0.1",
        "song_id": "twinkle",
        "segment_id": "verse2",
        "status": "ok",
        "inputs": {"reference_mid": "ref.mid", "attempt_mid": "att.mid", "meta": {}},
        "summary": {
            "counts": {"ref_notes": 10, "attempt_notes": 10, "matched": 9, "missing": 1, "extra": 0},
            "match_rate": 0.9,
            "top_problems": ["M2 timing_late x1"],
        },
        "metrics": {"timing": {}, "duration": {}, "dynamics": {}},
        "events": [],
    }
    (reports_dir / "20260101_120000.json").write_text(json.dumps(report_payload_1), encoding="utf-8")
    (reports_dir / "20260101_120100.json").write_text(json.dumps(report_payload_2), encoding="utf-8")

    monkeypatch.setattr("xpiano.cli.create_provider", lambda cfg: object())
    monkeypatch.setattr(
        "xpiano.cli.get_coaching",
        lambda report, provider, max_retries: {
            "goal": f"work on {report['segment_id']}",
            "top_issues": [{"title": "Issue", "why": "why", "evidence": ["x"]}],
            "drills": [
                {"name": "D1", "minutes": 7, "bpm": 45, "how": ["a", "b"], "reps": "5x", "focus_measures": "1"},
                {"name": "D2", "minutes": 8, "bpm": 50, "how": ["a", "b"], "reps": "4x", "focus_measures": "2"},
            ],
            "pass_conditions": {"before_speed_up": ["a", "b"], "speed_up_rule": "+5"},
            "next_recording": {"what_to_record": "seg", "tips": ["a", "b"]},
        },
    )
    monkeypatch.setattr(
        "xpiano.cli.save_coaching",
        lambda coaching, song_id, data_dir=None: Path("/tmp/fake_coaching.json"),
    )
    result = runner.invoke(app, ["coach", "--song", "twinkle", "--segment", "verse2"])
    assert result.exit_code == 0
    assert "Goal: work on verse2" in result.stdout


def test_coach_command_falls_back_when_provider_unavailable(
    xpiano_home: Path,
    monkeypatch,
) -> None:
    reports_dir = xpiano_home / "songs" / "twinkle" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_payload = {
        "version": "0.1",
        "song_id": "twinkle",
        "segment_id": "verse1",
        "status": "ok",
        "inputs": {"reference_mid": "ref.mid", "attempt_mid": "att.mid", "meta": {}},
        "summary": {
            "counts": {"ref_notes": 10, "attempt_notes": 10, "matched": 7, "missing": 3, "extra": 1},
            "match_rate": 0.7,
            "top_problems": ["M1 wrong_pitch x2"],
        },
        "metrics": {"timing": {}, "duration": {}, "dynamics": {}},
        "events": [],
    }
    (reports_dir / "20260101_120000.json").write_text(json.dumps(report_payload), encoding="utf-8")

    monkeypatch.setattr("xpiano.cli.create_provider", lambda cfg: (_ for _ in ()).throw(ValueError("missing key")))
    monkeypatch.setattr(
        "xpiano.cli.save_coaching",
        lambda coaching, song_id, data_dir=None: Path("/tmp/fake_coaching.json"),
    )
    result = runner.invoke(app, ["coach", "--song", "twinkle"])
    assert result.exit_code == 0
    assert "Provider unavailable" in result.stdout
    assert "Saved coaching:" in result.stdout


def test_coach_stream_command(
    xpiano_home: Path,
    monkeypatch,
) -> None:
    reports_dir = xpiano_home / "songs" / "twinkle" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "20260101_120000.json"
    report_payload = {
        "version": "0.1",
        "song_id": "twinkle",
        "segment_id": "verse1",
        "status": "ok",
        "inputs": {"reference_mid": "ref.mid", "attempt_mid": "att.mid", "meta": {}},
        "summary": {
            "counts": {"ref_notes": 10, "attempt_notes": 10, "matched": 8, "missing": 2, "extra": 1},
            "match_rate": 0.8,
            "top_problems": ["M2 wrong_pitch x2"],
        },
        "metrics": {"timing": {}, "duration": {}, "dynamics": {}},
        "events": [],
    }
    report_path.write_text(json.dumps(report_payload), encoding="utf-8")

    monkeypatch.setattr("xpiano.cli.create_provider", lambda cfg: object())

    async def _fake_stream(**kwargs):
        _ = kwargs
        return None

    monkeypatch.setattr("xpiano.cli.stream_coaching", _fake_stream)
    result = runner.invoke(app, ["coach", "--song", "twinkle", "--stream"])
    assert result.exit_code == 0
    assert "Streaming coaching finished." in result.stdout


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


def test_playback_command_requires_song_setup(xpiano_home: Path) -> None:
    _ = xpiano_home
    result = runner.invoke(
        app,
        ["playback", "--song", "twinkle", "--segment", "verse1", "--mode", "reference"],
    )
    assert result.exit_code != 0


def test_playback_command_invalid_measures_returns_error(monkeypatch) -> None:
    def _raise(**kwargs):
        _ = kwargs
        raise ValueError("invalid measure range: 3-2")

    monkeypatch.setattr("xpiano.cli.playback_play", _raise)
    result = runner.invoke(
        app,
        ["playback", "--song", "twinkle", "--segment", "verse1", "--mode", "reference", "--measures", "3-2"],
    )
    assert result.exit_code != 0


def test_playback_command_rejects_invalid_mode() -> None:
    result = runner.invoke(
        app,
        ["playback", "--song", "twinkle", "--segment", "verse1", "--mode", "invalid"],
    )
    assert result.exit_code != 0


def test_playback_command_invalid_highlight_returns_error(monkeypatch) -> None:
    def _raise(**kwargs):
        _ = kwargs
        raise ValueError("invalid highlight pitches: H9")

    monkeypatch.setattr("xpiano.cli.playback_play", _raise)
    result = runner.invoke(
        app,
        ["playback", "--song", "twinkle", "--segment", "verse1", "--mode", "reference", "--highlight", "H9"],
    )
    assert result.exit_code != 0


def test_playback_command_rejects_non_positive_bpm() -> None:
    result = runner.invoke(
        app,
        ["playback", "--song", "twinkle", "--segment", "verse1", "--mode", "reference", "--bpm", "0"],
    )
    assert result.exit_code != 0


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


def test_wait_command_requires_song_setup(xpiano_home: Path) -> None:
    _ = xpiano_home
    result = runner.invoke(
        app,
        ["wait", "--song", "twinkle", "--segment", "verse1"],
    )
    assert result.exit_code != 0


def test_wait_command_rejects_non_positive_bpm() -> None:
    result = runner.invoke(
        app,
        ["wait", "--song", "twinkle", "--segment", "verse1", "--bpm", "0"],
    )
    assert result.exit_code != 0


def test_wait_command_rejects_invalid_segment_range(xpiano_home: Path) -> None:
    setup = runner.invoke(
        app,
        ["setup", "--song", "twinkle", "--segment", "verse1", "--bpm", "80", "--time-sig", "4/4", "--measures", "1-2"],
    )
    assert setup.exit_code == 0
    meta_path = xpiano_home / "songs" / "twinkle" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["segments"][0]["start_measure"] = 3
    meta["segments"][0]["end_measure"] = 2
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    result = runner.invoke(
        app,
        ["wait", "--song", "twinkle", "--segment", "verse1"],
    )
    assert result.exit_code != 0


def test_history_and_compare_commands(monkeypatch) -> None:
    rows = [
        {
            "filename": "20260101_120000.json",
            "segment_id": "verse1",
            "match_rate": 0.5,
            "missing": 5,
            "extra": 2,
            "matched": 5,
            "ref_notes": 10,
        },
        {
            "filename": "20260101_120100.json",
            "segment_id": "verse1",
            "match_rate": 0.8,
            "missing": 2,
            "extra": 1,
            "matched": 8,
            "ref_notes": 10,
        },
    ]
    monkeypatch.setattr("xpiano.cli.build_history", lambda **kwargs: rows)

    history_result = runner.invoke(app, ["history", "--song", "twinkle"])
    assert history_result.exit_code == 0
    assert "20260101_120000.json" in history_result.stdout

    compare_result = runner.invoke(app, ["compare", "--song", "twinkle"])
    assert compare_result.exit_code == 0
    assert "match_rate: 0.50 -> 0.80 (+0.30)" in compare_result.stdout
    assert "trend: improved" in compare_result.stdout


def test_compare_accepts_latest_attempt_selector(monkeypatch) -> None:
    rows = [
        {"filename": "a.json", "segment_id": "verse1", "match_rate": 0.4, "missing": 6, "extra": 2, "matched": 4, "ref_notes": 10},
        {"filename": "b.json", "segment_id": "verse1", "match_rate": 0.7, "missing": 3, "extra": 1, "matched": 7, "ref_notes": 10},
    ]
    captured: dict[str, object] = {}

    def _fake_build_history(**kwargs):
        captured.update(kwargs)
        return rows

    monkeypatch.setattr("xpiano.cli.build_history", _fake_build_history)
    result = runner.invoke(app, ["compare", "--song", "twinkle", "--attempts", "latest-3"])
    assert result.exit_code == 0
    assert captured["attempts"] == 3


def test_compare_accepts_latest_attempt_selector_with_spaces(monkeypatch) -> None:
    rows = [
        {"filename": "a.json", "segment_id": "verse1", "match_rate": 0.4, "missing": 6, "extra": 2, "matched": 4, "ref_notes": 10},
        {"filename": "b.json", "segment_id": "verse1", "match_rate": 0.7, "missing": 3, "extra": 1, "matched": 7, "ref_notes": 10},
    ]
    captured: dict[str, object] = {}

    def _fake_build_history(**kwargs):
        captured.update(kwargs)
        return rows

    monkeypatch.setattr("xpiano.cli.build_history", _fake_build_history)
    result = runner.invoke(app, ["compare", "--song", "twinkle", "--attempts", " latest-3 "])
    assert result.exit_code == 0
    assert captured["attempts"] == 3


def test_compare_accepts_latest_attempt_selector_with_spaced_dash(monkeypatch) -> None:
    rows = [
        {"filename": "a.json", "segment_id": "verse1", "match_rate": 0.4, "missing": 6, "extra": 2, "matched": 4, "ref_notes": 10},
        {"filename": "b.json", "segment_id": "verse1", "match_rate": 0.7, "missing": 3, "extra": 1, "matched": 7, "ref_notes": 10},
    ]
    captured: dict[str, object] = {}

    def _fake_build_history(**kwargs):
        captured.update(kwargs)
        return rows

    monkeypatch.setattr("xpiano.cli.build_history", _fake_build_history)
    result = runner.invoke(app, ["compare", "--song", "twinkle", "--attempts", "latest - 3"])
    assert result.exit_code == 0
    assert captured["attempts"] == 3


def test_history_rejects_invalid_attempt_selector() -> None:
    result = runner.invoke(app, ["history", "--song", "twinkle", "--attempts", "latest-0"])
    assert result.exit_code != 0


def test_history_rejects_malformed_attempt_selector() -> None:
    result = runner.invoke(app, ["history", "--song", "twinkle", "--attempts", "latest--3"])
    assert result.exit_code != 0
