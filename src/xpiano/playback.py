from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import mido
import pretty_midi

from xpiano import midi_io, reference
from xpiano.models import PlayResult


@dataclass
class MeasureRange:
    start: int
    end: int


def _segment_config(meta: dict, segment_id: str) -> dict:
    for segment in meta.get("segments", []):
        if segment.get("segment_id") == segment_id:
            return segment
    raise ValueError(f"segment not found: {segment_id}")


def _parse_measure(value: str) -> int:
    try:
        return int(value.strip())
    except ValueError as exc:
        raise ValueError(f"invalid measure value: {value}") from exc


def _resolve_measures(segment: dict, measures: str | None) -> MeasureRange:
    default_start = int(segment["start_measure"])
    default_end = int(segment["end_measure"])
    if default_start <= 0:
        raise ValueError(
            f"invalid segment range: {default_start}-{default_end}"
        )
    if default_end < default_start:
        raise ValueError(
            f"invalid segment range: {default_start}-{default_end}"
        )
    if not measures:
        return MeasureRange(start=default_start, end=default_end)
    if "-" not in measures:
        value = _parse_measure(measures)
        start = value
        end = value
    else:
        start_s, end_s = measures.split("-", maxsplit=1)
        start = _parse_measure(start_s)
        end = _parse_measure(end_s)

    if start <= 0 or end <= 0 or end < start:
        raise ValueError(f"invalid measure range: {measures}")
    if start < default_start or end > default_end:
        raise ValueError(
            f"measure range {start}-{end} is outside segment "
            f"{default_start}-{default_end}"
        )
    return MeasureRange(start=start, end=end)


def _measure_to_sec(measure: int, bpm: float, beats_per_measure: int, segment_start_measure: int) -> float:
    beats_from_start = (measure - segment_start_measure) * beats_per_measure
    return beats_from_start * (60.0 / bpm)


def _measure_range_to_secs(
    selected: MeasureRange,
    bpm: float,
    beats_per_measure: int,
    base_measure: int,
) -> tuple[float, float]:
    start_sec = _measure_to_sec(
        measure=selected.start,
        bpm=bpm,
        beats_per_measure=beats_per_measure,
        segment_start_measure=base_measure,
    )
    end_sec = _measure_to_sec(
        measure=selected.end + 1,
        bpm=bpm,
        beats_per_measure=beats_per_measure,
        segment_start_measure=base_measure,
    )
    return start_sec, end_sec


def _pitch_names_to_numbers(values: list[str] | None) -> set[int]:
    if not values:
        return set()
    out: set[int] = set()
    invalid: list[str] = []
    for value in values:
        for token in value.split(","):
            normalized = token.strip()
            if not normalized:
                continue
            try:
                out.add(int(pretty_midi.note_name_to_number(normalized)))
            except Exception:
                invalid.append(normalized)
    if invalid:
        raise ValueError(
            "invalid highlight pitches: " + ", ".join(invalid)
        )
    return out


def _play_single(
    midi_path: Path,
    port: str | None,
    bpm: float | None,
    start_sec: float,
    end_sec: float | None,
    highlight: set[int],
) -> PlayResult:
    midi_file = mido.MidiFile(str(midi_path))
    return midi_io.play_midi(
        port=port,
        midi=midi_file,
        bpm=bpm,
        start_sec=start_sec,
        end_sec=end_sec,
        highlight_pitches=highlight,
    )


def play(
    source: str,
    song_id: str,
    segment_id: str,
    measures: str | None = None,
    bpm: float | None = None,
    highlight_pitches: list[str] | None = None,
    delay_between: float = 1.5,
    data_dir: str | Path | None = None,
    output_port: str | None = None,
) -> PlayResult:
    if bpm is not None and (bpm < 20 or bpm > 240):
        raise ValueError("invalid bpm: must be in range 20..240")
    if source == "comparison" and delay_between < 0:
        raise ValueError("delay_between must be >= 0")
    meta = reference.load_meta(song_id=song_id, data_dir=data_dir)
    segment = _segment_config(meta, segment_id=segment_id)
    selected = _resolve_measures(segment=segment, measures=measures)
    beats_per_measure = int(meta["time_signature"]["beats_per_measure"])
    ref_bpm = float(meta["bpm"])
    if beats_per_measure <= 0:
        raise ValueError("invalid time signature: beats_per_measure must be > 0")
    if beats_per_measure > 12:
        raise ValueError("invalid time signature: beats_per_measure must be <= 12")
    if ref_bpm < 20 or ref_bpm > 240:
        raise ValueError("invalid bpm: must be in range 20..240")
    seg_start = int(segment["start_measure"])
    highlight = _pitch_names_to_numbers(highlight_pitches)

    if source == "reference":
        start_sec, end_sec = _measure_range_to_secs(
            selected=selected,
            bpm=ref_bpm,
            beats_per_measure=beats_per_measure,
            base_measure=1,
        )
        return _play_single(
            midi_path=reference.reference_midi_path(
                song_id=song_id, data_dir=data_dir),
            port=output_port,
            bpm=bpm,
            start_sec=start_sec,
            end_sec=end_sec,
            highlight=highlight,
        )

    if source == "attempt":
        start_sec, end_sec = _measure_range_to_secs(
            selected=selected,
            bpm=ref_bpm,
            beats_per_measure=beats_per_measure,
            base_measure=seg_start,
        )
        return _play_single(
            midi_path=reference.latest_attempt_path(
                song_id=song_id, data_dir=data_dir),
            port=output_port,
            bpm=bpm,
            start_sec=start_sec,
            end_sec=end_sec,
            highlight=highlight,
        )

    if source == "comparison":
        attempt_start_sec, attempt_end_sec = _measure_range_to_secs(
            selected=selected,
            bpm=ref_bpm,
            beats_per_measure=beats_per_measure,
            base_measure=seg_start,
        )
        ref_start_sec, ref_end_sec = _measure_range_to_secs(
            selected=selected,
            bpm=ref_bpm,
            beats_per_measure=beats_per_measure,
            base_measure=1,
        )
        first = _play_single(
            midi_path=reference.latest_attempt_path(
                song_id=song_id, data_dir=data_dir),
            port=output_port,
            bpm=bpm,
            start_sec=attempt_start_sec,
            end_sec=attempt_end_sec,
            highlight=set(),
        )
        if first.status == "no_device":
            return first
        time.sleep(max(0.0, delay_between))
        second = _play_single(
            midi_path=reference.reference_midi_path(
                song_id=song_id, data_dir=data_dir),
            port=output_port,
            bpm=bpm,
            start_sec=ref_start_sec,
            end_sec=ref_end_sec,
            highlight=highlight,
        )
        return PlayResult(status=second.status, duration_sec=first.duration_sec + delay_between + second.duration_sec)

    raise ValueError(f"unsupported playback source: {source}")
