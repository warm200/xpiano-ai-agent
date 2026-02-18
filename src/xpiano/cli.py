from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from xpiano import config, midi_io, reference
from xpiano.analysis import analyze
from xpiano.report import build_report, save_report

app = typer.Typer(help="XPiano CLI")
console = Console()


def _parse_time_signature(time_sig: str) -> tuple[int, int]:
    try:
        left, right = time_sig.split("/", maxsplit=1)
        beats_per_measure = int(left)
        beat_unit = int(right)
    except ValueError as exc:
        raise typer.BadParameter("time signature must be like 4/4") from exc
    if beats_per_measure <= 0 or beat_unit <= 0:
        raise typer.BadParameter("time signature values must be > 0")
    return beats_per_measure, beat_unit


def _segment_meta(meta: dict, segment_id: str) -> dict:
    for segment in meta.get("segments", []):
        if segment.get("segment_id") == segment_id:
            return segment
    raise typer.BadParameter(f"segment not found: {segment_id}")


@app.command("devices")
def devices() -> None:
    entries = midi_io.list_devices()
    table = Table(title="MIDI Devices")
    table.add_column("Kind")
    table.add_column("Name")
    for item in entries:
        table.add_row(item.kind, item.name)
    if not entries:
        console.print("No MIDI devices found.")
        return
    console.print(table)


@app.command("setup")
def setup(
    song: str = typer.Option(..., "--song"),
    segment: str = typer.Option("default", "--segment"),
    bpm: float = typer.Option(..., "--bpm"),
    time_sig: str = typer.Option("4/4", "--time-sig"),
    measures: int = typer.Option(4, "--measures"),
    count_in: int = typer.Option(1, "--count-in"),
    split_pitch: int = typer.Option(60, "--split-pitch"),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
) -> None:
    config.ensure_config(data_dir=data_dir)
    beats_per_measure, beat_unit = _parse_time_signature(time_sig)

    try:
        meta = reference.load_meta(song_id=song, data_dir=data_dir)
    except FileNotFoundError:
        meta = {
            "song_id": song,
            "time_signature": {"beats_per_measure": beats_per_measure, "beat_unit": beat_unit},
            "bpm": bpm,
            "segments": [],
            "hand_split": {"split_pitch": split_pitch},
            "tolerance": config.load_config(data_dir=data_dir)["tolerance"],
        }
    meta["song_id"] = song
    meta["time_signature"] = {
        "beats_per_measure": beats_per_measure, "beat_unit": beat_unit}
    meta["bpm"] = bpm
    meta["hand_split"] = {"split_pitch": split_pitch}
    segments = [s for s in meta.get(
        "segments", []) if s.get("segment_id") != segment]
    segments.append(
        {
            "segment_id": segment,
            "label": segment,
            "start_measure": 1,
            "end_measure": measures,
            "count_in_measures": count_in,
        }
    )
    meta["segments"] = sorted(segments, key=lambda seg: seg["segment_id"])
    path = reference.save_meta(song_id=song, meta=meta, data_dir=data_dir)
    console.print(f"Saved setup: {path}")


@app.command("import")
def import_song(
    file: Path = typer.Option(..., "--file", exists=True, dir_okay=False),
    song: str = typer.Option(..., "--song"),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
) -> None:
    config.ensure_config(data_dir=data_dir)
    path = reference.import_reference(
        midi_path=file, song_id=song, data_dir=data_dir)
    console.print(f"Imported reference MIDI: {path}")


@app.command("list")
def list_song(data_dir: Path | None = typer.Option(None, "--data-dir")) -> None:
    config.ensure_config(data_dir=data_dir)
    songs = reference.list_songs(data_dir=data_dir)
    if not songs:
        console.print("No songs configured.")
        return
    table = Table(title="XPiano Songs")
    table.add_column("Song")
    table.add_column("Reference")
    table.add_column("Segments")
    table.add_column("Updated")
    for song in songs:
        table.add_row(
            song.song_id,
            "yes" if song.has_reference else "no",
            str(song.segments),
            song.updated_at or "-",
        )
    console.print(table)


@app.command("record")
def record(
    song: str = typer.Option(..., "--song"),
    segment: str = typer.Option("default", "--segment"),
    input_port: str | None = typer.Option(None, "--input-port"),
    output_port: str | None = typer.Option(None, "--output-port"),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
) -> None:
    config.ensure_config(data_dir=data_dir)
    meta = reference.load_meta(song_id=song, data_dir=data_dir)
    segment_cfg = _segment_meta(meta, segment_id=segment)
    ref_path = reference.reference_midi_path(song_id=song, data_dir=data_dir)

    beats_per_measure = int(meta["time_signature"]["beats_per_measure"])
    bpm = float(meta["bpm"])
    measures = int(segment_cfg["end_measure"]) - \
        int(segment_cfg["start_measure"]) + 1
    count_in_measures = int(segment_cfg.get("count_in_measures", 1))
    duration_sec = measures * beats_per_measure * (60.0 / bpm)
    count_in_beats = count_in_measures * beats_per_measure

    midi = midi_io.record(
        port=input_port,
        duration_sec=duration_sec,
        count_in_beats=count_in_beats,
        bpm=bpm,
        output_port=output_port,
    )
    attempt_path = reference.save_attempt(
        song_id=song, midi=midi, data_dir=data_dir)
    result = analyze(str(ref_path), str(attempt_path), meta)
    report_data = build_report(
        result=result,
        meta=meta,
        ref_path=ref_path,
        attempt_path=attempt_path,
        song_id=song,
        segment_id=segment,
    )
    report_path = save_report(
        report=report_data, song_id=song, data_dir=data_dir)

    console.print(f"Saved attempt: {attempt_path}")
    console.print(f"Saved report: {report_path}")
    console.print(
        f"match_rate={report_data['summary']['match_rate']:.2f} "
        f"quality_tier={result.quality_tier}"
    )

    if result.quality_tier == "too_low":
        console.print("Low match quality. Try slow playback and wait mode.")
    elif result.quality_tier == "simplified":
        console.print("Partial match. Showing top 3 issues first.")
    else:
        top = report_data["summary"].get("top_problems", [])
        if top:
            console.print("Top problems:")
            for problem in top[:3]:
                console.print(f"- {problem}")


@app.command("report")
def report(
    song: str = typer.Option(..., "--song"),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
) -> None:
    config.ensure_config(data_dir=data_dir)
    report_path = reference.latest_report_path(song_id=song, data_dir=data_dir)
    with report_path.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)
    summary = payload.get("summary", {})
    counts = summary.get("counts", {})
    console.print(f"Report: {report_path}")
    console.print(f"match_rate={summary.get('match_rate', 0):.2f}")
    console.print(
        f"ref={counts.get('ref_notes', 0)} "
        f"attempt={counts.get('attempt_notes', 0)} "
        f"matched={counts.get('matched', 0)} "
        f"missing={counts.get('missing', 0)} "
        f"extra={counts.get('extra', 0)}"
    )


if __name__ == "__main__":
    app()
