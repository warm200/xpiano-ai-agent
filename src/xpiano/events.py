from __future__ import annotations

from collections import defaultdict
from itertools import count
from typing import Literal

from xpiano.measure_beat import time_to_measure_beat
from xpiano.models import AlignmentResult, AnalysisEvent, NoteEvent


def _timing_event_type(delta_ms: float) -> Literal["timing_early", "timing_late"]:
    return "timing_early" if delta_ms < 0 else "timing_late"


def _timing_severity(
    delta_ms_abs: float,
    timing_grades: dict[str, int],
) -> Literal["low", "med", "high"] | None:
    if delta_ms_abs <= timing_grades["great_ms"]:
        return None
    if delta_ms_abs <= timing_grades["good_ms"]:
        return "low"
    if delta_ms_abs <= timing_grades["rushed_dragged_ms"]:
        return "med"
    return "high"


def _duration_event(
    ratio: float,
    short_ratio: float,
    long_ratio: float,
) -> tuple[Literal["duration_short", "duration_long"], Literal["med", "high"]] | None:
    if ratio <= 0:
        return None
    if ratio < 0.4:
        return ("duration_short", "high")
    if ratio > 2.0:
        return ("duration_long", "high")
    if ratio < short_ratio:
        return ("duration_short", "med")
    if ratio > long_ratio:
        return ("duration_long", "med")
    return None


def _segment_start_measure(meta: dict, segment_id: str | None) -> int:
    segments = meta.get("segments", [])
    if not segments:
        return 1
    if segment_id is None:
        first = segments[0]
        start_measure = int(first.get("start_measure", 1))
        if start_measure <= 0:
            raise ValueError(f"invalid segment start_measure: {start_measure}")
        return start_measure
    for segment in segments:
        if segment.get("segment_id") == segment_id:
            start_measure = int(segment.get("start_measure", 1))
            if start_measure <= 0:
                raise ValueError(f"invalid segment start_measure: {start_measure}")
            return start_measure
    raise ValueError(f"segment not found: {segment_id}")


def _group_indices_by_time(indices: list[int], notes: list[NoteEvent], window_sec: float) -> list[list[int]]:
    if not indices:
        return []
    sorted_indices = sorted(indices, key=lambda idx: notes[idx].start_sec)
    groups: list[list[int]] = [[sorted_indices[0]]]
    for idx in sorted_indices[1:]:
        last_group = groups[-1]
        anchor = notes[last_group[0]].start_sec
        if abs(notes[idx].start_sec - anchor) <= window_sec:
            last_group.append(idx)
        else:
            groups.append([idx])
    return groups


def _pitches_to_names(notes: list[NoteEvent], pitches: set[int]) -> list[str]:
    names: set[str] = set()
    for note in notes:
        if note.pitch in pitches:
            names.add(note.pitch_name)
    return sorted(names)


def _validate_timing_meta(meta: dict) -> tuple[int, float]:
    beats_per_measure = int(meta["time_signature"]["beats_per_measure"])
    bpm = float(meta["bpm"])
    if beats_per_measure <= 0:
        raise ValueError("invalid time signature: beats_per_measure must be > 0")
    if beats_per_measure > 12:
        raise ValueError("invalid time signature: beats_per_measure must be <= 12")
    if bpm < 20 or bpm > 240:
        raise ValueError("invalid bpm: must be in range 20..240")
    return beats_per_measure, bpm


def _validate_chord_window_ms(chord_window_ms: float) -> None:
    if chord_window_ms < 0:
        raise ValueError("invalid chord_window_ms: must be >= 0")


def _validate_tolerance(
    match_tol_ms: float,
    short_ratio: float,
    long_ratio: float,
    timing_grades: dict[str, int],
) -> None:
    if match_tol_ms < 0:
        raise ValueError("invalid match_tol_ms: must be >= 0")
    if short_ratio <= 0:
        raise ValueError("invalid duration_short_ratio: must be > 0")
    if long_ratio <= 0:
        raise ValueError("invalid duration_long_ratio: must be > 0")
    if short_ratio >= long_ratio:
        raise ValueError("invalid duration ratios: duration_short_ratio must be < duration_long_ratio")
    great_ms = int(timing_grades["great_ms"])
    good_ms = int(timing_grades["good_ms"])
    rushed_dragged_ms = int(timing_grades["rushed_dragged_ms"])
    if great_ms <= 0 or good_ms <= 0 or rushed_dragged_ms <= 0:
        raise ValueError("invalid timing_grades: values must be > 0")
    if not (great_ms <= good_ms <= rushed_dragged_ms):
        raise ValueError(
            "invalid timing_grades: expected great_ms <= good_ms <= rushed_dragged_ms"
        )


def generate_events(
    ref: list[NoteEvent],
    attempt: list[NoteEvent],
    alignment: AlignmentResult,
    meta: dict,
    segment_id: str | None = None,
) -> list[AnalysisEvent]:
    tolerance = meta.get("tolerance", {})
    match_tol_ms = float(tolerance.get("match_tol_ms", 80))
    timing_grades = tolerance.get(
        "timing_grades",
        {"great_ms": 25, "good_ms": 50, "rushed_dragged_ms": 100},
    )
    short_ratio = float(tolerance.get("duration_short_ratio", 0.6))
    long_ratio = float(tolerance.get("duration_long_ratio", 1.5))
    chord_window_ms = float(tolerance.get("chord_window_ms", 50))
    _validate_chord_window_ms(chord_window_ms)
    _validate_tolerance(
        match_tol_ms=match_tol_ms,
        short_ratio=short_ratio,
        long_ratio=long_ratio,
        timing_grades=timing_grades,
    )

    beats_per_measure, bpm = _validate_timing_meta(meta)
    start_measure = _segment_start_measure(meta, segment_id=segment_id)

    matched_ref_indices: set[int] = set()
    matched_attempt_indices: set[int] = set()
    events: list[AnalysisEvent] = []

    for ref_idx, attempt_idx in alignment.path:
        if ref_idx >= len(ref) or attempt_idx >= len(attempt):
            continue
        ref_note = ref[ref_idx]
        attempt_note = attempt[attempt_idx]
        if ref_note.pitch != attempt_note.pitch:
            continue

        onset_delta_ms = (attempt_note.start_sec - ref_note.start_sec) * 1000.0
        if abs(onset_delta_ms) > match_tol_ms:
            continue

        matched_ref_indices.add(ref_idx)
        matched_attempt_indices.add(attempt_idx)

        pos = time_to_measure_beat(
            time_sec=ref_note.start_sec,
            bpm=bpm,
            beats_per_measure=beats_per_measure,
            start_measure=start_measure,
        )
        timing_severity = _timing_severity(abs(onset_delta_ms), timing_grades)
        if timing_severity:
            events.append(
                AnalysisEvent(
                    type=_timing_event_type(onset_delta_ms),
                    measure=pos.measure,
                    beat=pos.beat,
                    pitch=ref_note.pitch,
                    pitch_name=ref_note.pitch_name,
                    hand=ref_note.hand,
                    severity=timing_severity,
                    delta_ms=onset_delta_ms,
                    time_ref_sec=ref_note.start_sec,
                    time_attempt_sec=attempt_note.start_sec,
                )
            )

        ratio = attempt_note.dur_sec / ref_note.dur_sec if ref_note.dur_sec > 0 else 1.0
        duration_result = _duration_event(
            ratio, short_ratio=short_ratio, long_ratio=long_ratio)
        if duration_result:
            event_type, severity = duration_result
            events.append(
                AnalysisEvent(
                    type=event_type,
                    measure=pos.measure,
                    beat=pos.beat,
                    pitch=ref_note.pitch,
                    pitch_name=ref_note.pitch_name,
                    hand=ref_note.hand,
                    severity=severity,
                    expected_duration_sec=ref_note.dur_sec,
                    actual_duration_sec=attempt_note.dur_sec,
                )
            )

    unmatched_ref_indices = [idx for idx in range(len(ref)) if idx not in matched_ref_indices]
    unmatched_attempt_indices = [idx for idx in range(len(attempt)) if idx not in matched_attempt_indices]
    consumed_ref_indices: set[int] = set()
    consumed_attempt_indices: set[int] = set()
    group_counter = count(1)
    chord_window_sec = chord_window_ms / 1000.0

    ref_chord_groups = _group_indices_by_time(unmatched_ref_indices, ref, chord_window_sec)
    for ref_group in ref_chord_groups:
        anchor_time = ref[ref_group[0]].start_sec
        ref_context = [
            idx for idx, note in enumerate(ref)
            if abs(note.start_sec - anchor_time) <= chord_window_sec
        ]
        attempt_context = [
            idx for idx, note in enumerate(attempt)
            if abs(note.start_sec - anchor_time) <= chord_window_sec
        ]
        ref_context_pitches = {ref[idx].pitch for idx in ref_context}
        attempt_context_pitches = {attempt[idx].pitch for idx in attempt_context}

        if len(ref_context_pitches) <= 1 and len(attempt_context_pitches) <= 1:
            continue

        candidate_attempt = [
            idx for idx in unmatched_attempt_indices
            if idx not in consumed_attempt_indices and abs(attempt[idx].start_sec - anchor_time) <= chord_window_sec
        ]
        if not candidate_attempt:
            continue

        ref_pitch_map: dict[int, list[int]] = defaultdict(list)
        attempt_pitch_map: dict[int, list[int]] = defaultdict(list)
        for idx in ref_group:
            ref_pitch_map[ref[idx].pitch].append(idx)
        for idx in candidate_attempt:
            attempt_pitch_map[attempt[idx].pitch].append(idx)

        ref_pitches = set(ref_pitch_map.keys())
        attempt_pitches = set(attempt_pitch_map.keys())
        hit_pitches = ref_context_pitches & attempt_context_pitches
        missing_pitches = ref_pitches - (ref_pitches & attempt_pitches)
        extra_pitches = attempt_pitches - (ref_pitches & attempt_pitches)

        pos = time_to_measure_beat(
            time_sec=anchor_time,
            bpm=bpm,
            beats_per_measure=beats_per_measure,
            start_measure=start_measure,
        )
        group_id = f"chord-{next(group_counter)}"
        hit_names = _pitches_to_names(ref, hit_pitches)
        missing_names = _pitches_to_names(ref, missing_pitches)
        extra_names = _pitches_to_names(attempt, extra_pitches)
        evidence = (
            f"chord partial: hit {len(hit_pitches)}/{len(ref_context_pitches)} "
            f"{hit_names} missing {missing_names} extra {extra_names}"
        )

        for pitch in hit_pitches:
            for ref_idx in ref_pitch_map[pitch]:
                consumed_ref_indices.add(ref_idx)
            for attempt_idx in attempt_pitch_map[pitch]:
                consumed_attempt_indices.add(attempt_idx)

        for pitch in missing_pitches:
            for ref_idx in ref_pitch_map[pitch]:
                ref_note = ref[ref_idx]
                consumed_ref_indices.add(ref_idx)
                events.append(
                    AnalysisEvent(
                        type="missing_note",
                        measure=pos.measure,
                        beat=pos.beat,
                        pitch=ref_note.pitch,
                        pitch_name=ref_note.pitch_name,
                        hand=ref_note.hand,
                        severity="high",
                        evidence=evidence,
                        time_ref_sec=ref_note.start_sec,
                        group_id=group_id,
                    )
                )

        for pitch in extra_pitches:
            for attempt_idx in attempt_pitch_map[pitch]:
                attempt_note = attempt[attempt_idx]
                consumed_attempt_indices.add(attempt_idx)
                events.append(
                    AnalysisEvent(
                        type="extra_note",
                        measure=pos.measure,
                        beat=pos.beat,
                        pitch=attempt_note.pitch,
                        pitch_name=attempt_note.pitch_name,
                        hand=attempt_note.hand,
                        severity="med",
                        evidence=evidence,
                        time_attempt_sec=attempt_note.start_sec,
                        group_id=group_id,
                    )
                )

    for ref_idx, ref_note in enumerate(ref):
        if ref_idx in matched_ref_indices or ref_idx in consumed_ref_indices:
            continue
        pos = time_to_measure_beat(
            time_sec=ref_note.start_sec,
            bpm=bpm,
            beats_per_measure=beats_per_measure,
            start_measure=start_measure,
        )
        events.append(
            AnalysisEvent(
                type="missing_note",
                measure=pos.measure,
                beat=pos.beat,
                pitch=ref_note.pitch,
                pitch_name=ref_note.pitch_name,
                hand=ref_note.hand,
                severity="high",
                time_ref_sec=ref_note.start_sec,
            )
        )

    for attempt_idx, attempt_note in enumerate(attempt):
        if attempt_idx in matched_attempt_indices or attempt_idx in consumed_attempt_indices:
            continue
        pos = time_to_measure_beat(
            time_sec=attempt_note.start_sec,
            bpm=bpm,
            beats_per_measure=beats_per_measure,
            start_measure=start_measure,
        )
        events.append(
            AnalysisEvent(
                type="extra_note",
                measure=pos.measure,
                beat=pos.beat,
                pitch=attempt_note.pitch,
                pitch_name=attempt_note.pitch_name,
                hand=attempt_note.hand,
                severity="med",
                time_attempt_sec=attempt_note.start_sec,
            )
        )

    return merge_wrong_pitch(events)


def merge_wrong_pitch(events: list[AnalysisEvent], beat_tolerance: float = 0.20) -> list[AnalysisEvent]:
    missing_by_measure: dict[int, list[AnalysisEvent]] = defaultdict(list)
    extra_by_measure: dict[int, list[AnalysisEvent]] = defaultdict(list)
    passthrough: list[AnalysisEvent] = []

    for event in events:
        if event.group_id is not None:
            passthrough.append(event)
        elif event.type == "missing_note":
            missing_by_measure[event.measure].append(event)
        elif event.type == "extra_note":
            extra_by_measure[event.measure].append(event)
        else:
            passthrough.append(event)

    consumed_missing: set[tuple[int, int]] = set()
    consumed_extra: set[tuple[int, int]] = set()
    merged: list[AnalysisEvent] = []

    for measure, miss_list in missing_by_measure.items():
        extra_list = extra_by_measure.get(measure, [])
        for miss_idx, miss in enumerate(miss_list):
            best_idx: int | None = None
            best_delta = float("inf")
            for extra_idx, extra in enumerate(extra_list):
                if (measure, extra_idx) in consumed_extra:
                    continue
                beat_delta = abs(miss.beat - extra.beat)
                if beat_delta <= beat_tolerance and beat_delta < best_delta:
                    best_delta = beat_delta
                    best_idx = extra_idx
            if best_idx is None:
                continue
            consumed_missing.add((measure, miss_idx))
            consumed_extra.add((measure, best_idx))
            extra = extra_list[best_idx]
            merged.append(
                AnalysisEvent(
                    type="wrong_pitch",
                    measure=miss.measure,
                    beat=miss.beat,
                    pitch=miss.pitch,
                    pitch_name=miss.pitch_name,
                    actual_pitch=extra.pitch,
                    actual_pitch_name=extra.pitch_name,
                    hand=miss.hand,
                    severity="high",
                    evidence=f"played {extra.pitch_name}, expected {miss.pitch_name}",
                    time_ref_sec=miss.time_ref_sec,
                    time_attempt_sec=extra.time_attempt_sec,
                )
            )

    remaining: list[AnalysisEvent] = passthrough[:]
    for measure, miss_list in missing_by_measure.items():
        for miss_idx, miss in enumerate(miss_list):
            if (measure, miss_idx) not in consumed_missing:
                remaining.append(miss)

    for measure, extra_list in extra_by_measure.items():
        _ = measure
        for extra_idx, extra in enumerate(extra_list):
            if (measure, extra_idx) not in consumed_extra:
                remaining.append(extra)

    remaining.extend(merged)
    remaining.sort(key=lambda evt: (evt.measure, evt.beat, evt.type))
    return remaining
