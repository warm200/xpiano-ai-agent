from __future__ import annotations

import asyncio
import math
import re
import time
from pathlib import Path
from typing import Any, Literal

import mido
import pretty_midi
import typer
from rich.console import Console
from rich.table import Table

from xpiano import config, midi_io, reference
from xpiano.analysis import analyze
from xpiano.display import (render_low_match, render_piano_roll_diff,
                            render_playback_indicator, render_report,
                            render_streaming_text, render_wait_step)
from xpiano.llm_coach import (fallback_output, get_coaching,
                              parse_coaching_text, save_coaching,
                              stream_coaching)
from xpiano.llm_provider import create_provider
from xpiano.playback import play as playback_play
from xpiano.report import (build_history, build_report,
                           latest_valid_report_path, load_report, save_report)
from xpiano.wait_mode import run_wait_mode

app = typer.Typer(help="XPiano CLI")
console = Console()
_ATTEMPTS_PATTERN = re.compile(r"^(?:latest\s*-\s*)?(\d+)$", re.IGNORECASE)


def _parse_time_signature(time_sig: str) -> tuple[int, int]:
    try:
        left, right = time_sig.split("/", maxsplit=1)
        beats_per_measure = int(left.strip())
        beat_unit = int(right.strip())
    except ValueError as exc:
        raise typer.BadParameter("time signature must be like 4/4") from exc
    if beats_per_measure <= 0 or beat_unit <= 0:
        raise typer.BadParameter("time signature values must be > 0")
    if beats_per_measure > 12:
        raise typer.BadParameter("time signature beats per measure must be <= 12")
    if beat_unit not in {1, 2, 4, 8, 16}:
        raise typer.BadParameter("time signature beat unit must be one of 1,2,4,8,16")
    return beats_per_measure, beat_unit


def _parse_measures(value: str) -> tuple[int, int]:
    if "-" in value:
        try:
            start_raw, end_raw = value.split("-", maxsplit=1)
            start = int(start_raw.strip())
            end = int(end_raw.strip())
        except ValueError as exc:
            raise typer.BadParameter("measures must be N or START-END (e.g. 4 or 1-4)") from exc
    else:
        try:
            end = int(value.strip())
        except ValueError as exc:
            raise typer.BadParameter("measures must be N or START-END (e.g. 4 or 1-4)") from exc
        start = 1
    if start <= 0 or end <= 0 or end < start:
        raise typer.BadParameter("measures must be positive and end >= start")
    return start, end


def _parse_attempts(value: str) -> int:
    normalized = value.strip()
    match = _ATTEMPTS_PATTERN.match(normalized)
    if match is None:
        raise typer.BadParameter("attempts must be N or latest-N")
    parsed = int(match.group(1))
    if parsed <= 0:
        raise typer.BadParameter("attempts must be > 0")
    return parsed


def _default_segment_bounds(meta: dict) -> tuple[int, int]:
    segments = meta.get("segments", [])
    if not segments:
        return 1, 4
    starts = [int(item.get("start_measure", 1)) for item in segments]
    ends = [int(item.get("end_measure", starts[idx])) for idx, item in enumerate(segments)]
    return min(starts), max(ends)


def _default_count_in(meta: dict) -> int:
    segments = meta.get("segments", [])
    if not segments:
        return 1
    return int(segments[0].get("count_in_measures", 1))


def _require_segment(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise typer.BadParameter("segment must be non-empty")
    if cleaned in {".", ".."}:
        raise typer.BadParameter("segment must not be '.' or '..'")
    if "/" in cleaned or "\\" in cleaned:
        raise typer.BadParameter("segment must not contain path separators")
    return cleaned


def _require_optional_segment(value: str | None) -> str | None:
    if value is None:
        return None
    return _require_segment(value)


def _require_song(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise typer.BadParameter("song must be non-empty")
    if cleaned in {".", ".."}:
        raise typer.BadParameter("song must not be '.' or '..'")
    if "/" in cleaned or "\\" in cleaned:
        raise typer.BadParameter("song must not contain path separators")
    return cleaned


def _segment_meta(meta: dict, segment_id: str) -> dict:
    for segment in meta.get("segments", []):
        if segment.get("segment_id") == segment_id:
            start_measure = int(segment.get("start_measure", 1))
            end_measure = int(segment.get("end_measure", start_measure))
            if start_measure <= 0 or end_measure < start_measure:
                raise typer.BadParameter(
                    f"invalid segment range for {segment_id}: {start_measure}-{end_measure}"
                )
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


def _resolve_max_retries(cfg: dict) -> int:
    raw_value = cfg.get("llm", {}).get("max_retries", 3)
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        return 3
    if parsed <= 0:
        return 3
    return parsed


def _coerce_float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return parsed


def _coerce_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, float):
        if not math.isfinite(value):
            return default
        if not value.is_integer():
            return default
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return default
        try:
            return int(stripped)
        except ValueError:
            try:
                parsed = float(stripped)
            except ValueError:
                return default
            if not math.isfinite(parsed) or not parsed.is_integer():
                return default
            return int(parsed)
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _row_text(row: dict, key: str, default: str = "-") -> str:
    value = row.get(key, default)
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


class _PlaybackAdapter:
    def __init__(
        self,
        song_id: str,
        segment_id: str,
        data_dir: Path | None,
        output_port: str | None = None,
    ):
        self.song_id = song_id
        self.segment_id = segment_id
        self.data_dir = data_dir
        self.output_port = output_port

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
            output_port=self.output_port,
        )


def _stream_coaching_text(
    report_payload: dict,
    provider,
    song_id: str,
    segment_id: str,
    data_dir: Path | None,
    output_port: str | None = None,
) -> str:
    adapter = _PlaybackAdapter(
        song_id=song_id,
        segment_id=segment_id,
        data_dir=data_dir,
        output_port=output_port,
    )

    def _on_tool(payload: dict) -> None:
        source = payload.get("source", "reference")
        measures = _measures_str(payload.get("measures"))
        console.print(f"\n{render_playback_indicator(source, measures)}")

    text = asyncio.run(
        stream_coaching(
            report=report_payload,
            provider=provider,
            playback_engine=adapter,
            on_text=lambda chunk: console.print(render_streaming_text(chunk), end=""),
            on_tool=_on_tool,
        )
    )
    console.print()
    return str(text)


def _play_attempt_file(
    attempt_path: str,
    output_port: str | None,
    bpm: float | None,
) -> tuple[str, float]:
    midi = mido.MidiFile(attempt_path)
    result = midi_io.play_midi(
        port=output_port,
        midi=midi,
        bpm=bpm,
        start_sec=0.0,
        end_sec=None,
        highlight_pitches=None,
    )
    return result.status, result.duration_sec


def _resolve_attempt_path(
    attempt_path: str,
    report_path: Path,
    data_dir: Path | None,
) -> Path:
    raw = Path(attempt_path.strip()).expanduser()
    if raw.is_absolute():
        if raw.is_file():
            return raw
        by_report_name = (report_path.parent / raw.name).resolve()
        if by_report_name.is_file():
            return by_report_name
        attempts_sibling = (report_path.parent.parent /
                            "attempts" / raw.name).resolve()
        if attempts_sibling.is_file():
            return attempts_sibling
        return raw
    report_relative = (report_path.parent / raw).resolve()
    if report_relative.is_file():
        return report_relative
    if data_dir is not None:
        data_relative = (data_dir / raw).resolve()
        if data_relative.is_file():
            return data_relative
    return raw.resolve()


def _resolve_report_path_from_row(
    row: dict,
    song_id: str,
    data_dir: Path | None,
    exclude_filename: str | None = None,
) -> Path | None:
    raw_path = row.get("path")
    if raw_path:
        candidate = Path(str(raw_path))
        if candidate.is_absolute():
            if candidate.is_file():
                return candidate
        else:
            cwd_candidate = candidate.resolve()
            if cwd_candidate.is_file():
                return cwd_candidate
            if data_dir is not None:
                data_candidate = (data_dir / candidate).resolve()
                if data_candidate.is_file():
                    return data_candidate
    filename = str(row.get("filename", "")).strip()
    if not filename:
        return None
    candidate = reference.songs_dir(data_dir=data_dir) / song_id / "reports" / filename
    if candidate.is_file():
        return candidate
    # Graceful fallback for renamed timestamp files: choose latest report in same segment.
    segment_id = str(row.get("segment_id", "")).strip()
    if segment_id:
        history_rows = _sorted_history_candidates(
            build_history(
                song_id=song_id,
                segment_id=segment_id,
                attempts=50,
                data_dir=data_dir,
            )
        )
        for candidate_row in reversed(history_rows):
            candidate_name = _row_text(candidate_row, "filename", default="")
            if exclude_filename and candidate_name == exclude_filename:
                continue
            latest_path = str(candidate_row.get("path", "")).strip()
            if not latest_path:
                continue
            latest_candidate = Path(latest_path)
            if latest_candidate.is_file():
                return latest_candidate
    return None


def _sorted_history_candidates(rows: list[dict]) -> list[dict]:
    return sorted(
        rows,
        key=lambda row: (_row_text(row, "filename"), _row_text(row, "path")),
    )


def _safe_note_name(note_number: int) -> str:
    try:
        return pretty_midi.note_number_to_name(int(note_number))
    except (TypeError, ValueError):
        return f"note_{note_number}"


@app.command("devices")
def devices() -> None:
    try:
        entries = midi_io.list_devices()
    except (OSError, RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
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
    bpm: float | None = typer.Option(None, "--bpm"),
    time_sig: str | None = typer.Option(None, "--time-sig"),
    measures: str | None = typer.Option(None, "--measures"),
    count_in: int | None = typer.Option(None, "--count-in"),
    split_pitch: int | None = typer.Option(None, "--split-pitch"),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
) -> None:
    song = _require_song(song)
    segment = _require_segment(segment)
    if bpm is not None and bpm <= 0:
        raise typer.BadParameter("bpm must be > 0")
    if bpm is not None and (bpm < 20 or bpm > 240):
        raise typer.BadParameter("bpm must be in range 20..240")
    if split_pitch is not None and (split_pitch < 0 or split_pitch > 127):
        raise typer.BadParameter("split-pitch must be in range 0..127")
    config.ensure_config(data_dir=data_dir)
    parsed_time_sig = _parse_time_signature(time_sig) if time_sig is not None else None

    try:
        meta = reference.load_meta(song_id=song, data_dir=data_dir)
    except FileNotFoundError:
        default_beats, default_unit = parsed_time_sig or (4, 4)
        meta = {
            "song_id": song,
            "time_signature": {"beats_per_measure": default_beats, "beat_unit": default_unit},
            "bpm": float(bpm) if bpm is not None else 120.0,
            "segments": [],
            "hand_split": {"split_pitch": 60},
            "tolerance": config.load_config(data_dir=data_dir)["tolerance"],
        }
    existing_segment = next(
        (s for s in meta.get("segments", []) if s.get("segment_id") == segment),
        None,
    )
    if measures is None:
        if existing_segment is not None:
            start_measure = int(existing_segment.get("start_measure", 1))
            end_measure = int(existing_segment.get("end_measure", start_measure))
        else:
            start_measure, end_measure = _default_segment_bounds(meta)
    else:
        start_measure, end_measure = _parse_measures(measures)
    if count_in is None:
        if existing_segment is not None:
            count_in_measures = int(existing_segment.get("count_in_measures", 1))
        else:
            count_in_measures = _default_count_in(meta)
    else:
        if count_in <= 0:
            raise typer.BadParameter("count-in must be > 0")
        count_in_measures = count_in
    existing_split_pitch = int(meta.get("hand_split", {}).get("split_pitch", 60))
    resolved_split_pitch = existing_split_pitch if split_pitch is None else split_pitch
    if parsed_time_sig is None:
        beats_per_measure = int(meta.get("time_signature", {}).get("beats_per_measure", 4))
        beat_unit = int(meta.get("time_signature", {}).get("beat_unit", 4))
    else:
        beats_per_measure, beat_unit = parsed_time_sig
    resolved_bpm = float(meta.get("bpm", 120.0)) if bpm is None else float(bpm)
    meta["song_id"] = song
    meta["time_signature"] = {
        "beats_per_measure": beats_per_measure, "beat_unit": beat_unit}
    meta["bpm"] = resolved_bpm
    meta["hand_split"] = {"split_pitch": resolved_split_pitch}
    segments = [s for s in meta.get(
        "segments", []) if s.get("segment_id") != segment]
    segments.append(
        {
            "segment_id": segment,
            "label": segment,
            "start_measure": start_measure,
            "end_measure": end_measure,
            "count_in_measures": count_in_measures,
        }
    )
    meta["segments"] = sorted(segments, key=lambda seg: seg["segment_id"])
    try:
        path = reference.save_meta(song_id=song, meta=meta, data_dir=data_dir)
    except (ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    console.print(f"Saved setup: {path}")


@app.command("import")
def import_song(
    file: Path = typer.Option(..., "--file", exists=True, dir_okay=False),
    song: str = typer.Option(..., "--song"),
    segment: str | None = typer.Option(None, "--segment"),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
) -> None:
    song = _require_song(song)
    segment = _require_optional_segment(segment)
    config.ensure_config(data_dir=data_dir)
    try:
        path = reference.import_reference(
            midi_path=file, song_id=song, data_dir=data_dir, segment_id=segment)
    except (FileNotFoundError, ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    console.print(f"Imported reference MIDI: {path}")


@app.command("list")
def list_song(data_dir: Path | None = typer.Option(None, "--data-dir")) -> None:
    config.ensure_config(data_dir=data_dir)
    try:
        songs = reference.list_songs(data_dir=data_dir)
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
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
        try:
            history_rows = build_history(
                song_id=song.song_id,
                attempts=1,
                data_dir=data_dir,
            )
        except (ValueError, OSError):
            history_rows = []
        last_match = "-"
        last_problem = "-"
        if history_rows:
            latest = history_rows[-1]
            last_match = f"{_coerce_float(latest.get('match_rate')):.2f}"
            last_problem = (
                f"{_coerce_int(latest.get('missing'))}/"
                f"{_coerce_int(latest.get('extra'))}"
            )
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
    song = _require_song(song)
    segment = _require_segment(segment)
    cfg = config.ensure_config(data_dir=data_dir)
    try:
        meta = reference.load_meta(song_id=song, data_dir=data_dir)
        ref_path = reference.reference_midi_path(song_id=song, data_dir=data_dir)
    except (FileNotFoundError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    segment_cfg = _segment_meta(meta, segment_id=segment)

    beats_per_measure = int(meta["time_signature"]["beats_per_measure"])
    beat_unit = int(meta["time_signature"].get("beat_unit", 4))
    bpm = float(meta["bpm"])
    if beats_per_measure <= 0:
        raise typer.BadParameter(
            "invalid time signature: beats_per_measure must be > 0"
        )
    if beats_per_measure > 12:
        raise typer.BadParameter(
            "invalid time signature: beats_per_measure must be <= 12"
        )
    if beat_unit <= 0:
        raise typer.BadParameter(
            "invalid time signature: beat_unit must be > 0"
        )
    if beat_unit not in {1, 2, 4, 8, 16}:
        raise typer.BadParameter(
            "invalid time signature: beat_unit must be one of 1,2,4,8,16"
        )
    if bpm < 20 or bpm > 240:
        raise typer.BadParameter("invalid bpm: must be in range 20..240")
    measures = int(segment_cfg["end_measure"]) - \
        int(segment_cfg["start_measure"]) + 1
    if measures <= 0:
        raise typer.BadParameter(
            f"invalid segment range for {segment}: "
            f"{segment_cfg['start_measure']}-{segment_cfg['end_measure']}"
        )
    count_in_measures = int(segment_cfg.get("count_in_measures", 1))
    if count_in_measures <= 0:
        raise typer.BadParameter("segment count_in_measures must be > 0")
    duration_sec = measures * beats_per_measure * (60.0 / bpm)
    count_in_beats = count_in_measures * beats_per_measure

    try:
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
        result = analyze(
            str(ref_path),
            str(attempt_path),
            meta,
            segment_id=segment,
            attempt_is_segment_relative=True,
        )
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
    except (FileNotFoundError, ValueError, OSError, RuntimeError) as exc:
        raise typer.BadParameter(str(exc)) from exc

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
        provider = None
        try:
            provider = create_provider(cfg)
        except (ValueError, OSError, RuntimeError) as exc:
            console.print(f"Provider unavailable, using fallback coaching: {exc}")

        if provider is None:
            coaching = fallback_output(report_data)
        else:
            console.print("Streaming coaching:")
            try:
                streamed_text = _stream_coaching_text(
                    report_payload=report_data,
                    provider=provider,
                    song_id=song,
                    segment_id=segment,
                    data_dir=data_dir,
                    output_port=output_port,
                )
            except (ValueError, OSError, RuntimeError) as exc:
                raise typer.BadParameter(str(exc)) from exc
            coaching, stream_errors = parse_coaching_text(streamed_text)
            if coaching is None:
                console.print(
                    "Streaming output invalid, using fallback coaching: "
                    + "; ".join(stream_errors)
                )
                try:
                    coaching = get_coaching(
                        report=report_data,
                        provider=provider,
                        max_retries=_resolve_max_retries(cfg),
                    )
                except Exception as exc:
                    # Provider stacks can raise heterogeneous exception types.
                    console.print(
                        "Batch coaching recovery failed, using fallback coaching: "
                        + str(exc)
                    )
                    coaching = fallback_output(report_data)
        try:
            coaching_path = save_coaching(
                coaching=coaching, song_id=song, data_dir=data_dir)
        except (ValueError, OSError, RuntimeError) as exc:
            raise typer.BadParameter(str(exc)) from exc
        console.print(f"Saved coaching: {coaching_path}")
        console.print(render_report(report_data, coaching=coaching))
        console.print(f"quality_tier={result.quality_tier}")
    if result.quality_tier != "too_low":
        diff_max_measures = 1 if result.quality_tier == "simplified" else 3
        console.print(render_piano_roll_diff(report_data, max_measures=diff_max_measures))


@app.command("record-ref")
def record_ref(
    song: str = typer.Option(..., "--song"),
    segment: str = typer.Option("default", "--segment"),
    input_port: str | None = typer.Option(None, "--input-port"),
    output_port: str | None = typer.Option(None, "--output-port"),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
) -> None:
    song = _require_song(song)
    segment = _require_segment(segment)
    config.ensure_config(data_dir=data_dir)
    try:
        path = reference.record_reference(
            song_id=song,
            segment_id=segment,
            port=input_port,
            output_port=output_port,
            data_dir=data_dir,
        )
    except (FileNotFoundError, ValueError, OSError, RuntimeError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    console.print(f"Saved reference MIDI: {path}")


@app.command("report")
def report(
    song: str = typer.Option(..., "--song"),
    segment: str | None = typer.Option(None, "--segment"),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
) -> None:
    song = _require_song(song)
    segment = _require_optional_segment(segment)
    config.ensure_config(data_dir=data_dir)
    if segment is None:
        try:
            report_path = latest_valid_report_path(song_id=song, data_dir=data_dir)
        except FileNotFoundError:
            console.print("No report history.")
            return
        except OSError as exc:
            raise typer.BadParameter(str(exc)) from exc
    else:
        try:
            report_path = latest_valid_report_path(
                song_id=song,
                segment_id=segment,
                data_dir=data_dir,
            )
        except FileNotFoundError:
            console.print("No report found for segment.")
            return
        except OSError as exc:
            raise typer.BadParameter(str(exc)) from exc
    try:
        payload = load_report(report_path)
    except FileNotFoundError:
        if segment is None:
            console.print("No report history.")
        else:
            console.print("No report found for segment.")
        return
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    except OSError as exc:
        raise typer.BadParameter(str(exc)) from exc
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
    song = _require_song(song)
    segment = _require_optional_segment(segment)
    cfg = config.ensure_config(data_dir=data_dir)
    if segment is None:
        try:
            report_path = latest_valid_report_path(song_id=song, data_dir=data_dir)
        except FileNotFoundError:
            console.print("No report history.")
            return
        except OSError as exc:
            raise typer.BadParameter(str(exc)) from exc
    else:
        try:
            report_path = latest_valid_report_path(
                song_id=song,
                segment_id=segment,
                data_dir=data_dir,
            )
        except FileNotFoundError:
            console.print("No report found for segment.")
            return
        except OSError as exc:
            raise typer.BadParameter(str(exc)) from exc
    try:
        report_payload = load_report(report_path)
    except FileNotFoundError:
        if segment is None:
            console.print("No report history.")
        else:
            console.print("No report found for segment.")
        return
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    except OSError as exc:
        raise typer.BadParameter(str(exc)) from exc

    provider = None
    try:
        provider = create_provider(cfg)
    except (ValueError, OSError, RuntimeError) as exc:
        console.print(f"Provider unavailable, using fallback coaching: {exc}")

    if stream:
        if provider is None:
            coaching = fallback_output(report_payload)
            try:
                output_path = save_coaching(
                    coaching=coaching, song_id=song, data_dir=data_dir)
            except (ValueError, OSError, RuntimeError) as exc:
                raise typer.BadParameter(str(exc)) from exc
            console.print(f"Saved coaching: {output_path}")
            console.print(f"Goal: {coaching.get('goal', '-')}")
            return

        segment_id = str(report_payload.get("segment_id", "default"))
        try:
            _ = _stream_coaching_text(
                report_payload=report_payload,
                provider=provider,
                song_id=song,
                segment_id=segment_id,
                data_dir=data_dir,
            )
        except (ValueError, OSError, RuntimeError) as exc:
            raise typer.BadParameter(str(exc)) from exc
        console.print("Streaming coaching finished.")
        return

    if provider is None:
        coaching = fallback_output(report_payload)
    else:
        try:
            coaching = get_coaching(
                report=report_payload,
                provider=provider,
                max_retries=_resolve_max_retries(cfg),
            )
        except Exception as exc:
            # Provider stacks can raise heterogeneous exception types.
            console.print(
                "Coaching request failed, using fallback coaching: "
                + str(exc)
            )
            coaching = fallback_output(report_payload)
    try:
        output_path = save_coaching(
            coaching=coaching, song_id=song, data_dir=data_dir)
    except (ValueError, OSError, RuntimeError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    console.print(f"Saved coaching: {output_path}")
    console.print(f"Goal: {coaching.get('goal', '-')}")
    for issue in coaching.get("top_issues", [])[:3]:
        console.print(f"- {issue.get('title', '-')}")


@app.command("playback")
def playback(
    song: str = typer.Option(..., "--song"),
    segment: str = typer.Option("default", "--segment"),
    mode: Literal["reference", "attempt", "comparison"] = typer.Option("reference", "--mode"),
    measures: str | None = typer.Option(None, "--measures"),
    bpm: float | None = typer.Option(None, "--bpm"),
    highlight: list[str] | None = typer.Option(None, "--highlight"),
    output_port: str | None = typer.Option(None, "--output-port"),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
) -> None:
    song = _require_song(song)
    segment = _require_segment(segment)
    if bpm is not None and (bpm < 20 or bpm > 240):
        raise typer.BadParameter("bpm must be in range 20..240")
    try:
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
    except (FileNotFoundError, ValueError, OSError, RuntimeError) as exc:
        raise typer.BadParameter(str(exc)) from exc
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
    song = _require_song(song)
    segment = _require_segment(segment)
    if bpm is not None and (bpm < 20 or bpm > 240):
        raise typer.BadParameter("bpm must be in range 20..240")

    def _on_step(step) -> None:
        console.print(render_wait_step(step.measure, step.beat, step.pitch_names))

    def _on_match(step) -> None:
        _ = step
        console.print("  ok matched")

    def _on_wrong(step, played_pitches: set[int]) -> None:
        expected = ", ".join(step.pitch_names) if step.pitch_names else "(none)"
        played_names = sorted(
            _safe_note_name(pitch) for pitch in played_pitches
        )
        played = ", ".join(played_names) if played_names else "(none)"
        console.print(f"  x expected {expected}, got {played}")

    def _on_timeout(step) -> None:
        expected = ", ".join(step.pitch_names) if step.pitch_names else "(none)"
        console.print(f"  timeout waiting for {expected}")

    try:
        result = run_wait_mode(
            song_id=song,
            segment_id=segment,
            bpm=bpm,
            port=input_port,
            data_dir=data_dir,
            on_step=_on_step,
            on_match=_on_match,
            on_wrong=_on_wrong,
            on_timeout=_on_timeout,
        )
    except (FileNotFoundError, ValueError, OSError, RuntimeError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    console.print(
        f"Wait mode: completed={result.completed}/{result.total_steps} errors={result.errors}"
    )


@app.command("history")
def history(
    song: str = typer.Option(..., "--song"),
    segment: str | None = typer.Option(None, "--segment"),
    attempts: str = typer.Option("5", "--attempts"),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
) -> None:
    song = _require_song(song)
    segment = _require_optional_segment(segment)
    attempt_count = _parse_attempts(attempts)
    try:
        rows = build_history(
            song_id=song,
            segment_id=segment,
            attempts=attempt_count,
            data_dir=data_dir,
        )
    except (ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from exc
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
            _row_text(row, "filename"),
            _row_text(row, "segment_id"),
            f"{_coerce_float(row.get('match_rate')):.2f}",
            str(_coerce_int(row.get("missing"))),
            str(_coerce_int(row.get("extra"))),
        )
    console.print(table)


@app.command("compare")
def compare(
    song: str = typer.Option(..., "--song"),
    segment: str | None = typer.Option(None, "--segment"),
    attempts: str = typer.Option("2", "--attempts"),
    playback: bool = typer.Option(False, "--playback"),
    bpm: float | None = typer.Option(None, "--bpm"),
    output_port: str | None = typer.Option(None, "--output-port"),
    delay_between: float = typer.Option(1.0, "--delay-between"),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
) -> None:
    song = _require_song(song)
    segment = _require_optional_segment(segment)
    if bpm is not None and (bpm < 20 or bpm > 240):
        raise typer.BadParameter("bpm must be in range 20..240")
    if delay_between < 0:
        raise typer.BadParameter("delay-between must be >= 0")
    attempt_count = _parse_attempts(attempts)
    try:
        rows = build_history(
            song_id=song,
            segment_id=segment,
            attempts=max(2, attempt_count),
            data_dir=data_dir,
        )
    except (ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    if len(rows) < 2:
        console.print("Need at least 2 reports to compare.")
        return
    if segment is None:
        curr = rows[-1]
        curr_segment = str(curr.get("segment_id", "")).strip()
        if not curr_segment:
            console.print(
                "Need at least 2 reports in the same segment to compare. "
                "Use --segment or increase --attempts."
            )
            return
        prev = next(
            (
                row
                for row in reversed(rows[:-1])
                if str(row.get("segment_id", "")).strip() == curr_segment
            ),
            None,
        )
        if prev is None:
            console.print(
                "Need at least 2 reports in the same segment to compare. "
                "Use --segment or increase --attempts."
            )
            return
    else:
        prev = rows[-2]
        curr = rows[-1]
    prev_filename = _row_text(prev, "filename")
    curr_filename = _row_text(curr, "filename")
    prev_match = _coerce_float(prev.get("match_rate"))
    curr_match = _coerce_float(curr.get("match_rate"))
    prev_missing = _coerce_int(prev.get("missing"))
    curr_missing = _coerce_int(curr.get("missing"))
    prev_extra = _coerce_int(prev.get("extra"))
    curr_extra = _coerce_int(curr.get("extra"))
    console.print(f"Compare: {prev_filename} -> {curr_filename}")
    delta_match = curr_match - prev_match
    delta_missing = curr_missing - prev_missing
    delta_extra = curr_extra - prev_extra
    console.print(
        f"match_rate: {prev_match:.2f} -> {curr_match:.2f} ({delta_match:+.2f})")
    console.print(
        f"missing: {prev_missing} -> {curr_missing} ({delta_missing:+d})")
    console.print(
        f"extra: {prev_extra} -> {curr_extra} ({delta_extra:+d})")
    if delta_match > 0 and delta_missing <= 0 and delta_extra <= 0:
        verdict = "improved"
    elif delta_match == 0 and delta_missing == 0 and delta_extra == 0:
        verdict = "stable"
    else:
        verdict = "regressed"
    console.print(f"trend: {verdict}")

    if not playback:
        return

    prev_report_path = _resolve_report_path_from_row(
        row=prev,
        song_id=song,
        data_dir=data_dir,
        exclude_filename=_row_text(curr, "filename", default=""),
    )
    curr_report_path = _resolve_report_path_from_row(
        row=curr,
        song_id=song,
        data_dir=data_dir,
        exclude_filename=_row_text(prev, "filename", default=""),
    )
    if not prev_report_path or not curr_report_path:
        console.print("Playback skipped: report history does not include file paths.")
        return
    prev_report_file = Path(str(prev_report_path))
    curr_report_file = Path(str(curr_report_path))
    if prev_report_file.resolve() == curr_report_file.resolve():
        console.print(
            "Playback skipped: resolved previous and current report to the same file."
        )
        return
    try:
        prev_report = load_report(prev_report_file)
        curr_report = load_report(curr_report_file)
    except FileNotFoundError:
        console.print("Playback skipped: resolved report file not found.")
        return
    except ValueError:
        console.print("Playback skipped: resolved report file is invalid.")
        return
    except OSError as exc:
        raise typer.BadParameter(str(exc)) from exc

    prev_attempt_path = str(prev_report.get("inputs", {}).get("attempt_mid", "")).strip()
    curr_attempt_path = str(curr_report.get("inputs", {}).get("attempt_mid", "")).strip()
    if not prev_attempt_path or not curr_attempt_path:
        console.print("Playback skipped: missing attempt path in report inputs.")
        return

    prev_attempt = _resolve_attempt_path(
        attempt_path=prev_attempt_path,
        report_path=prev_report_file,
        data_dir=data_dir,
    )
    curr_attempt = _resolve_attempt_path(
        attempt_path=curr_attempt_path,
        report_path=curr_report_file,
        data_dir=data_dir,
    )
    if not prev_attempt.is_file() or not curr_attempt.is_file():
        console.print("Playback skipped: attempt MIDI file not found.")
        return
    if prev_attempt.resolve() == curr_attempt.resolve():
        console.print(
            "Playback skipped: resolved previous and current attempt to the same file."
        )
        return

    try:
        console.print("▶ playback before attempt")
        before_status, before_duration = _play_attempt_file(
            attempt_path=str(prev_attempt),
            output_port=output_port,
            bpm=bpm,
        )
        if before_status == "no_device":
            console.print("Playback skipped: no MIDI output device.")
            return
        if delay_between > 0:
            time.sleep(delay_between)
        console.print("▶ playback latest attempt")
        latest_status, latest_duration = _play_attempt_file(
            attempt_path=str(curr_attempt),
            output_port=output_port,
            bpm=bpm,
        )
        if latest_status == "no_device":
            console.print("Playback skipped: no MIDI output device.")
            return
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    console.print(
        "Playback compare: "
        f"before={before_status} ({before_duration:.2f}s), "
        f"latest={latest_status} ({latest_duration:.2f}s)"
    )


if __name__ == "__main__":
    app()
