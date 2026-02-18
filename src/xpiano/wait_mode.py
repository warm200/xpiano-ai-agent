from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

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


def _segment_bounds(meta: dict, segment_id: str) -> tuple[int, int]:
    for segment in meta.get("segments", []):
        if segment.get("segment_id") == segment_id:
            start = int(segment.get("start_measure", 1))
            end = int(segment.get("end_measure", start))
            if start <= 0:
                raise ValueError(f"invalid segment range: {start}-{end}")
            if end < start:
                raise ValueError(f"invalid segment range: {start}-{end}")
            return start, end
    raise ValueError(f"segment not found: {segment_id}")


def build_pitch_sequence(notes: list[NoteEvent], meta: dict) -> list[PitchSetStep]:
    tolerance = meta.get("tolerance", {})
    chord_window_ms = float(tolerance.get("chord_window_ms", 50))
    if chord_window_ms < 0:
        raise ValueError("invalid chord_window_ms: must be >= 0")
    beats_per_measure = int(meta["time_signature"]["beats_per_measure"])
    beat_unit = int(meta["time_signature"].get("beat_unit", 4))
    bpm = float(meta["bpm"])
    if beats_per_measure <= 0:
        raise ValueError("invalid time signature: beats_per_measure must be > 0")
    if beats_per_measure > 12:
        raise ValueError("invalid time signature: beats_per_measure must be <= 12")
    if beat_unit not in {1, 2, 4, 8, 16}:
        raise ValueError("invalid time signature: beat_unit must be one of 1,2,4,8,16")
    if bpm < 20 or bpm > 240:
        raise ValueError("invalid bpm: must be in range 20..240")
    beat_sec = 60.0 / bpm
    window_sec = chord_window_ms / 1000.0

    if not notes:
        return []
    sorted_notes = sorted(notes, key=lambda note: (note.start_sec, note.pitch))

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
        measure = 1 + int(total_beats // beats_per_measure)
        beat = 1.0 + (total_beats % beats_per_measure)
        pitches = {note.pitch for note in group}
        names = sorted({note.pitch_name for note in group})
        steps.append(PitchSetStep(measure=measure, beat=beat,
                     pitches=pitches, pitch_names=names))
    return steps


def _dict_to_note(note: dict) -> NoteEvent:
    required = {"pitch", "pitch_name", "start_sec", "end_sec", "dur_sec", "velocity"}
    missing = [key for key in sorted(required) if key not in note]
    if missing:
        raise ValueError(f"invalid reference note entry: missing keys {', '.join(missing)}")
    pitch = int(note["pitch"])
    if pitch < 0 or pitch > 127:
        raise ValueError("invalid reference note entry: pitch must be in range 0..127")
    pitch_name = str(note["pitch_name"])
    if not pitch_name:
        raise ValueError("invalid reference note entry: pitch_name must be non-empty")
    start_sec = float(note["start_sec"])
    end_sec = float(note["end_sec"])
    dur_sec = float(note["dur_sec"])
    if end_sec < start_sec:
        raise ValueError("invalid reference note entry: end_sec must be >= start_sec")
    if dur_sec < 0:
        raise ValueError("invalid reference note entry: dur_sec must be >= 0")
    velocity = int(note["velocity"])
    if velocity < 0 or velocity > 127:
        raise ValueError("invalid reference note entry: velocity must be in range 0..127")
    hand_raw = str(note.get("hand", "U"))
    if hand_raw not in {"L", "R", "U"}:
        raise ValueError(f"invalid reference note entry: hand must be one of L,R,U (got {hand_raw})")
    hand = cast(Literal["L", "R", "U"], hand_raw)
    return NoteEvent(
        pitch=pitch,
        pitch_name=pitch_name,
        start_sec=start_sec,
        end_sec=end_sec,
        dur_sec=dur_sec,
        velocity=velocity,
        hand=hand,
    )


def _normalize_pitch_set(value: Any) -> set[int]:
    iterable: Iterable[Any]
    if isinstance(value, set):
        iterable = value
    elif isinstance(value, (list, tuple)):
        iterable = value
    else:
        raise ValueError("invalid event_stream item: expected set/list/tuple of pitches")
    out: set[int] = set()
    for pitch in iterable:
        if isinstance(pitch, bool):
            raise ValueError("invalid event_stream pitch: expected integer")
        out.add(int(pitch))
    return out


def run_wait_mode(
    song_id: str,
    segment_id: str,
    port: str | None = None,
    bpm: float | None = None,
    data_dir: str | Path | None = None,
    event_stream: Iterable[set[int]] | None = None,
    on_step: Callable[[PitchSetStep], None] | None = None,
    on_match: Callable[[PitchSetStep], None] | None = None,
    on_wrong: Callable[[PitchSetStep, set[int]], None] | None = None,
    on_timeout: Callable[[PitchSetStep], None] | None = None,
) -> WaitModeResult:
    if bpm is not None and (bpm < 20 or bpm > 240):
        raise ValueError("invalid bpm: must be in range 20..240")
    meta = load_meta(song_id=song_id, data_dir=data_dir)
    if bpm is not None:
        meta = dict(meta)
        meta["bpm"] = bpm
    segment_start, segment_end = _segment_bounds(meta, segment_id=segment_id)

    notes = [_dict_to_note(note) for note in load_reference_notes(
        song_id=song_id, data_dir=data_dir)]
    all_steps = build_pitch_sequence(notes=notes, meta=meta)
    steps = [step for step in all_steps if segment_start <=
             step.measure <= segment_end]
    if not steps:
        return WaitModeResult(total_steps=0, completed=0, errors=0)

    if event_stream is not None:
        completed = 0
        errors = 0
        incoming_iter = iter(event_stream)
        for step in steps:
            if on_step is not None:
                on_step(step)
            try:
                incoming_step = next(incoming_iter)
            except StopIteration:
                errors += 1
                if on_timeout is not None:
                    on_timeout(step)
                continue
            try:
                incoming_pitches = _normalize_pitch_set(incoming_step)
            except (TypeError, ValueError):
                errors += 1
                if on_wrong is not None:
                    on_wrong(step, set())
                continue
            if incoming_pitches == step.pitches:
                completed += 1
                if on_match is not None:
                    on_match(step)
            else:
                errors += 1
                if on_wrong is not None:
                    on_wrong(step, incoming_pitches)
        return WaitModeResult(total_steps=len(steps), completed=completed, errors=errors)

    beat_timeout_sec = 2.0 * (60.0 / float(meta["bpm"]))
    completed = 0
    errors = 0
    with mido.open_input(port) as in_port:
        for step in steps:
            if on_step is not None:
                on_step(step)
            started_at = time.monotonic()
            collected: set[int] = set()
            while True:
                for msg in in_port.iter_pending():
                    if msg.type == "note_on" and msg.velocity > 0:
                        collected.add(int(msg.note))
                if collected == step.pitches:
                    completed += 1
                    if on_match is not None:
                        on_match(step)
                    break
                if collected and not collected.issubset(step.pitches):
                    errors += 1
                    if on_wrong is not None:
                        on_wrong(step, set(collected))
                    collected.clear()
                if (time.monotonic() - started_at) > beat_timeout_sec:
                    errors += 1
                    if on_timeout is not None:
                        on_timeout(step)
                    break
                time.sleep(0.005)

    return WaitModeResult(total_steps=len(steps), completed=completed, errors=errors)
