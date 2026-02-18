from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

import mido

from xpiano.models import NoteEvent
from xpiano.reference import load_meta, load_reference_notes


@dataclass
class PitchSetStep:
    measure: int
    beat: float
    pitches: set[int]
    pitch_names: list[str]


@dataclass
class WaitModeResult:
    total_steps: int
    completed: int
    errors: int


def _segment_start_measure(meta: dict, segment_id: str) -> int:
    for segment in meta.get("segments", []):
        if segment.get("segment_id") == segment_id:
            return int(segment.get("start_measure", 1))
    raise ValueError(f"segment not found: {segment_id}")


def build_pitch_sequence(notes: list[NoteEvent], meta: dict) -> list[PitchSetStep]:
    tolerance = meta.get("tolerance", {})
    chord_window_ms = float(tolerance.get("chord_window_ms", 50))
    beats_per_measure = int(meta["time_signature"]["beats_per_measure"])
    bpm = float(meta["bpm"])
    beat_sec = 60.0 / bpm
    window_sec = chord_window_ms / 1000.0

    if not notes:
        return []
    sorted_notes = sorted(notes, key=lambda note: (note.start_sec, note.pitch))
    start_measure = int(meta.get("segments", [{}])[0].get("start_measure", 1))

    grouped: list[list[NoteEvent]] = []
    for note in sorted_notes:
        if not grouped:
            grouped.append([note])
            continue
        last_group = grouped[-1]
        if abs(note.start_sec - last_group[0].start_sec) <= window_sec:
            last_group.append(note)
        else:
            grouped.append([note])

    steps: list[PitchSetStep] = []
    for group in grouped:
        start_sec = group[0].start_sec
        total_beats = start_sec / beat_sec
        measure = start_measure + int(total_beats // beats_per_measure)
        beat = 1.0 + (total_beats % beats_per_measure)
        pitches = {note.pitch for note in group}
        names = sorted({note.pitch_name for note in group})
        steps.append(PitchSetStep(measure=measure, beat=beat,
                     pitches=pitches, pitch_names=names))
    return steps


def _dict_to_note(note: dict) -> NoteEvent:
    return NoteEvent(
        pitch=int(note["pitch"]),
        pitch_name=str(note["pitch_name"]),
        start_sec=float(note["start_sec"]),
        end_sec=float(note["end_sec"]),
        dur_sec=float(note["dur_sec"]),
        velocity=int(note["velocity"]),
        hand=cast(Literal["L", "R", "U"], note.get("hand", "U")),
    )


def run_wait_mode(
    song_id: str,
    segment_id: str,
    port: str | None = None,
    bpm: float | None = None,
    data_dir: str | Path | None = None,
    event_stream: Iterable[set[int]] | None = None,
) -> WaitModeResult:
    meta = load_meta(song_id=song_id, data_dir=data_dir)
    if bpm is not None:
        meta = dict(meta)
        meta["bpm"] = bpm
    _ = _segment_start_measure(meta, segment_id=segment_id)

    notes = [_dict_to_note(note) for note in load_reference_notes(
        song_id=song_id, data_dir=data_dir)]
    steps = build_pitch_sequence(notes=notes, meta=meta)
    if not steps:
        return WaitModeResult(total_steps=0, completed=0, errors=0)

    if event_stream is not None:
        completed = 0
        errors = 0
        incoming = list(event_stream)
        for idx, step in enumerate(steps):
            if idx >= len(incoming):
                break
            if incoming[idx] == step.pitches:
                completed += 1
            else:
                errors += 1
        return WaitModeResult(total_steps=len(steps), completed=completed, errors=errors)

    beat_timeout_sec = 2.0 * (60.0 / float(meta["bpm"]))
    completed = 0
    errors = 0
    with mido.open_input(port) as in_port:
        for step in steps:
            started_at = time.monotonic()
            collected: set[int] = set()
            while True:
                for msg in in_port.iter_pending():
                    if msg.type == "note_on" and msg.velocity > 0:
                        collected.add(int(msg.note))
                if collected == step.pitches:
                    completed += 1
                    break
                if collected and not step.pitches.issubset(collected):
                    errors += 1
                    collected.clear()
                if (time.monotonic() - started_at) > beat_timeout_sec:
                    errors += 1
                    break
                time.sleep(0.005)

    return WaitModeResult(total_steps=len(steps), completed=completed, errors=errors)
