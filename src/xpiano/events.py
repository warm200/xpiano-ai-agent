from __future__ import annotations

from collections import defaultdict
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


def _segment_start_measure(meta: dict) -> int:
    segments = meta.get("segments", [])
    if not segments:
        return 1
    first = segments[0]
    return int(first.get("start_measure", 1))


def generate_events(
    ref: list[NoteEvent],
    attempt: list[NoteEvent],
    alignment: AlignmentResult,
    meta: dict,
) -> list[AnalysisEvent]:
    tolerance = meta.get("tolerance", {})
    match_tol_ms = float(tolerance.get("match_tol_ms", 80))
    timing_grades = tolerance.get(
        "timing_grades",
        {"great_ms": 25, "good_ms": 50, "rushed_dragged_ms": 100},
    )
    short_ratio = float(tolerance.get("duration_short_ratio", 0.6))
    long_ratio = float(tolerance.get("duration_long_ratio", 1.5))

    beats_per_measure = int(meta["time_signature"]["beats_per_measure"])
    bpm = float(meta["bpm"])
    start_measure = _segment_start_measure(meta)

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

    for ref_idx, ref_note in enumerate(ref):
        if ref_idx in matched_ref_indices:
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
        if attempt_idx in matched_attempt_indices:
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
        if event.type == "missing_note":
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
