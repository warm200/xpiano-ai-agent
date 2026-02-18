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


def _resolve_measures(segment: dict, measures: str | None) -> MeasureRange:
    default_start = int(segment["start_measure"])
    default_end = int(segment["end_measure"])
    if not measures:
        return MeasureRange(start=default_start, end=default_end)
    if "-" not in measures:
        value = int(measures)
        return MeasureRange(start=value, end=value)
    start_s, end_s = measures.split("-", maxsplit=1)
    return MeasureRange(start=int(start_s), end=int(end_s))


def _measure_to_sec(measure: int, bpm: float, beats_per_measure: int, segment_start_measure: int) -> float:
    beats_from_start = (measure - segment_start_measure) * beats_per_measure
    return beats_from_start * (60.0 / bpm)


def _pitch_names_to_numbers(values: list[str] | None) -> set[int]:
    if not values:
        return set()
    out: set[int] = set()
    for value in values:
        try:
            out.add(int(pretty_midi.note_name_to_number(value)))
        except Exception:
            continue
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
    meta = reference.load_meta(song_id=song_id, data_dir=data_dir)
    segment = _segment_config(meta, segment_id=segment_id)
    selected = _resolve_measures(segment=segment, measures=measures)
    beats_per_measure = int(meta["time_signature"]["beats_per_measure"])
    ref_bpm = float(meta["bpm"])
    seg_start = int(segment["start_measure"])

    start_sec = _measure_to_sec(
        measure=selected.start,
        bpm=ref_bpm,
        beats_per_measure=beats_per_measure,
        segment_start_measure=seg_start,
    )
    end_sec = _measure_to_sec(
        measure=selected.end + 1,
        bpm=ref_bpm,
        beats_per_measure=beats_per_measure,
        segment_start_measure=seg_start,
    )
    highlight = _pitch_names_to_numbers(highlight_pitches)

    if source == "reference":
        return _play_single(
            midi_path=reference.reference_midi_path(song_id=song_id, data_dir=data_dir),
            port=output_port,
            bpm=bpm,
            start_sec=start_sec,
            end_sec=end_sec,
            highlight=highlight,
        )

    if source == "attempt":
        return _play_single(
            midi_path=reference.latest_attempt_path(song_id=song_id, data_dir=data_dir),
            port=output_port,
            bpm=bpm,
            start_sec=start_sec,
            end_sec=end_sec,
            highlight=highlight,
        )

    if source == "comparison":
        first = _play_single(
            midi_path=reference.latest_attempt_path(song_id=song_id, data_dir=data_dir),
            port=output_port,
            bpm=bpm,
            start_sec=start_sec,
            end_sec=end_sec,
            highlight=set(),
        )
        if first.status == "no_device":
            return first
        time.sleep(max(0.0, delay_between))
        second = _play_single(
            midi_path=reference.reference_midi_path(song_id=song_id, data_dir=data_dir),
            port=output_port,
            bpm=bpm,
            start_sec=start_sec,
            end_sec=end_sec,
            highlight=highlight,
        )
        return PlayResult(status=second.status, duration_sec=first.duration_sec + delay_between + second.duration_sec)

    raise ValueError(f"unsupported playback source: {source}")
