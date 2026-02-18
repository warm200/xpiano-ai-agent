from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from xpiano import config, midi_io, reference

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


if __name__ == "__main__":
    app()
