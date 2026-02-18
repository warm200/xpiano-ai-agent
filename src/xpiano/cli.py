from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from xpiano import config, midi_io, reference
from xpiano.analysis import analyze
from xpiano.display import (render_low_match, render_piano_roll_diff,
                            render_playback_indicator, render_report)
from xpiano.llm_coach import get_coaching, save_coaching, stream_coaching
from xpiano.llm_provider import create_provider
from xpiano.playback import play as playback_play
from xpiano.report import build_history, build_report, save_report
from xpiano.wait_mode import run_wait_mode

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


def _measures_str(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    start = value.get("start")
    end = value.get("end")
    if start is None or end is None:
        return None
    return f"{start}-{end}"


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
    table.add_column("Last Match")
    table.add_column("Missing/Extra")
    table.add_column("Updated")
    for song in songs:
        history_rows = build_history(
            song_id=song.song_id,
            attempts=1,
            data_dir=data_dir,
        )
        last_match = "-"
        last_problem = "-"
        if history_rows:
            latest = history_rows[-1]
            last_match = f"{latest['match_rate']:.2f}"
            last_problem = f"{latest['missing']}/{latest['extra']}"
        table.add_row(
            song.song_id,
            "yes" if song.has_reference else "no",
            str(song.segments),
            last_match,
            last_problem,
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
    cfg = config.ensure_config(data_dir=data_dir)
    meta = reference.load_meta(song_id=song, data_dir=data_dir)
    segment_cfg = _segment_meta(meta, segment_id=segment)
    ref_path = reference.reference_midi_path(song_id=song, data_dir=data_dir)

    beats_per_measure = int(meta["time_signature"]["beats_per_measure"])
    beat_unit = int(meta["time_signature"].get("beat_unit", 4))
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
        beats_per_measure=beats_per_measure,
        beat_unit=beat_unit,
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

    coaching: dict | None = None
    if result.quality_tier == "too_low":
        console.print(render_report(report_data))
        console.print(f"quality_tier={result.quality_tier}")
        console.print(render_low_match(
            match_rate=result.match_rate, song=song, segment=segment))
    elif result.quality_tier == "simplified":
        console.print(render_report(report_data))
        console.print(f"quality_tier={result.quality_tier}")
        console.print("Partial match. Showing top 3 issues first.")
    else:
        try:
            provider = create_provider(cfg)
            coaching = get_coaching(
                report=report_data,
                provider=provider,
                max_retries=int(cfg.get("llm", {}).get("max_retries", 3)),
            )
            coaching_path = save_coaching(
                coaching=coaching, song_id=song, data_dir=data_dir)
            console.print(f"Saved coaching: {coaching_path}")
        except Exception as exc:
            console.print(f"Coaching skipped: {exc}")
        console.print(render_report(report_data, coaching=coaching))
        console.print(f"quality_tier={result.quality_tier}")
    console.print(render_piano_roll_diff(report_data))


@app.command("record-ref")
def record_ref(
    song: str = typer.Option(..., "--song"),
    segment: str = typer.Option("default", "--segment"),
    input_port: str | None = typer.Option(None, "--input-port"),
    output_port: str | None = typer.Option(None, "--output-port"),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
) -> None:
    config.ensure_config(data_dir=data_dir)
    path = reference.record_reference(
        song_id=song,
        segment_id=segment,
        port=input_port,
        output_port=output_port,
        data_dir=data_dir,
    )
    console.print(f"Saved reference MIDI: {path}")


@app.command("report")
def report(
    song: str = typer.Option(..., "--song"),
    segment: str | None = typer.Option(None, "--segment"),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
) -> None:
    config.ensure_config(data_dir=data_dir)
    if segment is None:
        report_path = reference.latest_report_path(song_id=song, data_dir=data_dir)
    else:
        rows = build_history(
            song_id=song,
            segment_id=segment,
            attempts=1,
            data_dir=data_dir,
        )
        if not rows:
            console.print("No report found for segment.")
            return
        report_path = Path(rows[-1]["path"])
    with report_path.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)
    console.print(f"Report: {report_path}")
    console.print(render_report(payload))
    console.print(render_piano_roll_diff(payload))


@app.command("coach")
def coach(
    song: str = typer.Option(..., "--song"),
    segment: str | None = typer.Option(None, "--segment"),
    stream: bool = typer.Option(False, "--stream"),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
) -> None:
    cfg = config.ensure_config(data_dir=data_dir)
    if segment is None:
        report_path = reference.latest_report_path(song_id=song, data_dir=data_dir)
    else:
        rows = build_history(
            song_id=song,
            segment_id=segment,
            attempts=1,
            data_dir=data_dir,
        )
        if not rows:
            console.print("No report found for segment.")
            return
        report_path = Path(rows[-1]["path"])
    with report_path.open("r", encoding="utf-8") as fp:
        report_payload = json.load(fp)

    provider = create_provider(cfg)
    if stream:
        segment_id = str(report_payload.get("segment_id", "default"))

        class _PlaybackAdapter:
            def __init__(self, song_id: str, segment_id: str, data_dir: Path | None):
                self.song_id = song_id
                self.segment_id = segment_id
                self.data_dir = data_dir

            def play(self, **payload):
                measures_obj = payload.get("measures")
                measures = None
                if isinstance(measures_obj, dict):
                    start = measures_obj.get("start")
                    end = measures_obj.get("end")
                    if start and end:
                        measures = f"{start}-{end}"
                return playback_play(
                    source=payload.get("source", "reference"),
                    song_id=self.song_id,
                    segment_id=self.segment_id,
                    measures=measures,
                    bpm=payload.get("bpm"),
                    highlight_pitches=payload.get("highlight_pitches"),
                    data_dir=self.data_dir,
                    delay_between=float(payload.get("delay_between_sec", 1.5)),
                )

        def _on_tool(payload: dict) -> None:
            source = payload.get("source", "reference")
            measures = _measures_str(payload.get("measures"))
            console.print(f"\n{render_playback_indicator(source, measures)}")

        asyncio.run(
            stream_coaching(
                report=report_payload,
                provider=provider,
                playback_engine=_PlaybackAdapter(song, segment_id, data_dir),
                on_text=lambda text: console.print(text, end=""),
                on_tool=_on_tool,
            )
        )
        console.print()
        console.print("Streaming coaching finished.")
        return

    coaching = get_coaching(
        report=report_payload,
        provider=provider,
        max_retries=int(cfg.get("llm", {}).get("max_retries", 3)),
    )
    output_path = save_coaching(
        coaching=coaching, song_id=song, data_dir=data_dir)
    console.print(f"Saved coaching: {output_path}")
    console.print(f"Goal: {coaching.get('goal', '-')}")
    for issue in coaching.get("top_issues", [])[:3]:
        console.print(f"- {issue.get('title', '-')}")


@app.command("playback")
def playback(
    song: str = typer.Option(..., "--song"),
    segment: str = typer.Option("default", "--segment"),
    mode: str = typer.Option("reference", "--mode"),
    measures: str | None = typer.Option(None, "--measures"),
    bpm: float | None = typer.Option(None, "--bpm"),
    highlight: list[str] | None = typer.Option(None, "--highlight"),
    output_port: str | None = typer.Option(None, "--output-port"),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
) -> None:
    result = playback_play(
        source=mode,
        song_id=song,
        segment_id=segment,
        measures=measures,
        bpm=bpm,
        highlight_pitches=highlight,
        output_port=output_port,
        data_dir=data_dir,
    )
    console.print(
        f"Playback status: {result.status} ({result.duration_sec:.2f}s)")


@app.command("wait")
def wait(
    song: str = typer.Option(..., "--song"),
    segment: str = typer.Option("default", "--segment"),
    bpm: float | None = typer.Option(None, "--bpm"),
    input_port: str | None = typer.Option(None, "--input-port"),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
) -> None:
    result = run_wait_mode(
        song_id=song,
        segment_id=segment,
        bpm=bpm,
        port=input_port,
        data_dir=data_dir,
    )
    console.print(
        f"Wait mode: completed={result.completed}/{result.total_steps} errors={result.errors}"
    )


@app.command("history")
def history(
    song: str = typer.Option(..., "--song"),
    segment: str | None = typer.Option(None, "--segment"),
    attempts: int = typer.Option(5, "--attempts"),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
) -> None:
    rows = build_history(
        song_id=song,
        segment_id=segment,
        attempts=attempts,
        data_dir=data_dir,
    )
    if not rows:
        console.print("No report history.")
        return
    table = Table(title=f"History: {song}")
    table.add_column("Report")
    table.add_column("Segment")
    table.add_column("Match")
    table.add_column("Missing")
    table.add_column("Extra")
    for row in rows:
        table.add_row(
            row["filename"],
            str(row["segment_id"]),
            f"{row['match_rate']:.2f}",
            str(row["missing"]),
            str(row["extra"]),
        )
    console.print(table)


@app.command("compare")
def compare(
    song: str = typer.Option(..., "--song"),
    segment: str | None = typer.Option(None, "--segment"),
    attempts: int = typer.Option(2, "--attempts"),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
) -> None:
    rows = build_history(
        song_id=song,
        segment_id=segment,
        attempts=max(2, attempts),
        data_dir=data_dir,
    )
    if len(rows) < 2:
        console.print("Need at least 2 reports to compare.")
        return
    prev = rows[-2]
    curr = rows[-1]
    console.print(f"Compare: {prev['filename']} -> {curr['filename']}")
    delta_match = curr["match_rate"] - prev["match_rate"]
    delta_missing = curr["missing"] - prev["missing"]
    delta_extra = curr["extra"] - prev["extra"]
    console.print(
        f"match_rate: {prev['match_rate']:.2f} -> {curr['match_rate']:.2f} ({delta_match:+.2f})")
    console.print(
        f"missing: {prev['missing']} -> {curr['missing']} ({delta_missing:+d})")
    console.print(
        f"extra: {prev['extra']} -> {curr['extra']} ({delta_extra:+d})")
    if delta_match > 0 and delta_missing <= 0 and delta_extra <= 0:
        verdict = "improved"
    elif delta_match == 0 and delta_missing == 0 and delta_extra == 0:
        verdict = "stable"
    else:
        verdict = "regressed"
    console.print(f"trend: {verdict}")


if __name__ == "__main__":
    app()
