from __future__ import annotations

from dataclasses import dataclass, replace
from statistics import median

from xpiano.alignment import Aligner, DTWAligner
from xpiano.events import generate_events
from xpiano.models import AlignmentResult, AnalysisEvent, NoteEvent
from xpiano.parser import midi_to_notes


@dataclass
class AnalysisResult:
    ref_notes: list[NoteEvent]
    attempt_notes: list[NoteEvent]
    events: list[AnalysisEvent]
    metrics: dict
    match_rate: float
    quality_tier: str
    alignment: AlignmentResult
    matched: int


def _dedup_ref_count(notes: list[NoteEvent], chord_window_ms: float) -> int:
    if not notes:
        return 0
    sorted_notes = sorted(notes, key=lambda n: (n.start_sec, n.pitch))
    kept = 0
    last_seen: dict[int, float] = {}
    win_sec = chord_window_ms / 1000.0
    for note in sorted_notes:
        last_time = last_seen.get(note.pitch)
        if last_time is None or (note.start_sec - last_time) > win_sec:
            kept += 1
            last_seen[note.pitch] = note.start_sec
    return kept


def _segment_config(meta: dict, segment_id: str | None) -> dict | None:
    segments = meta.get("segments", [])
    if not segments:
        return None
    if segment_id is None:
        return segments[0]
    for segment in segments:
        if segment.get("segment_id") == segment_id:
            return segment
    raise ValueError(f"segment not found: {segment_id}")


def _segment_time_bounds(meta: dict, segment_id: str | None) -> tuple[float, float] | None:
    segment = _segment_config(meta, segment_id=segment_id)
    if segment is None:
        return None
    bpm = float(meta.get("bpm", 120))
    beats_per_measure = int(meta.get("time_signature", {}).get("beats_per_measure", 4))
    start_measure = int(segment.get("start_measure", 1))
    end_measure = int(segment.get("end_measure", start_measure))
    if start_measure <= 0:
        raise ValueError(f"invalid segment range: {start_measure}-{end_measure}")
    if end_measure < start_measure:
        raise ValueError(f"invalid segment range: {start_measure}-{end_measure}")
    beat_sec = 60.0 / bpm
    start_sec = (start_measure - 1) * beats_per_measure * beat_sec
    end_sec = end_measure * beats_per_measure * beat_sec
    return (start_sec, end_sec)


def _validate_timing_meta(meta: dict) -> None:
    beats_per_measure = int(meta.get("time_signature", {}).get("beats_per_measure", 4))
    bpm = float(meta.get("bpm", 120))
    if beats_per_measure <= 0:
        raise ValueError("invalid time signature: beats_per_measure must be > 0")
    if bpm <= 0:
        raise ValueError("invalid bpm: must be > 0")


def _slice_to_segment(notes: list[NoteEvent], segment_bounds: tuple[float, float] | None) -> list[NoteEvent]:
    if segment_bounds is None:
        return notes
    start_sec, end_sec = segment_bounds
    return [note for note in notes if start_sec <= note.start_sec < end_sec]


def _shift_notes(notes: list[NoteEvent], offset_sec: float) -> list[NoteEvent]:
    if offset_sec == 0:
        return notes
    return [
        replace(
            note,
            start_sec=note.start_sec - offset_sec,
            end_sec=note.end_sec - offset_sec,
        )
        for note in notes
    ]


def _select_valid_matches(
    ref_notes: list[NoteEvent],
    attempt_notes: list[NoteEvent],
    path: list[tuple[int, int]],
    match_tol_ms: float,
) -> list[tuple[int, int]]:
    valid: list[tuple[int, int]] = []
    seen_ref: set[int] = set()
    seen_attempt: set[int] = set()
    for ref_idx, attempt_idx in path:
        if ref_idx in seen_ref or attempt_idx in seen_attempt:
            continue
        if ref_idx >= len(ref_notes) or attempt_idx >= len(attempt_notes):
            continue
        ref_note = ref_notes[ref_idx]
        attempt_note = attempt_notes[attempt_idx]
        if ref_note.pitch != attempt_note.pitch:
            continue
        if abs((attempt_note.start_sec - ref_note.start_sec) * 1000.0) > match_tol_ms:
            continue
        seen_ref.add(ref_idx)
        seen_attempt.add(attempt_idx)
        valid.append((ref_idx, attempt_idx))
    return valid


def _quality_tier(match_rate: float) -> str:
    if match_rate >= 0.50:
        return "full"
    if match_rate >= 0.20:
        return "simplified"
    return "too_low"


def _safe_median(values: list[float]) -> float:
    return float(median(values)) if values else 0.0


def _safe_p90(values: list[float]) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = min(len(sorted_vals) - 1, int(round(0.9 * (len(sorted_vals) - 1))))
    return float(sorted_vals[idx])


def _build_metrics(ref_notes: list[NoteEvent], attempt_notes: list[NoteEvent], matches: list[tuple[int, int]]) -> dict:
    deltas_ms: list[float] = []
    duration_ratios: list[float] = []

    for ref_idx, attempt_idx in matches:
        ref_note = ref_notes[ref_idx]
        attempt_note = attempt_notes[attempt_idx]
        deltas_ms.append(
            (attempt_note.start_sec - ref_note.start_sec) * 1000.0)
        if ref_note.dur_sec > 0:
            duration_ratios.append(attempt_note.dur_sec / ref_note.dur_sec)

    left_vel = [n.velocity for n in attempt_notes if n.hand == "L"]
    right_vel = [n.velocity for n in attempt_notes if n.hand == "R"]
    left_mean = float(sum(left_vel) / len(left_vel)) if left_vel else None
    right_mean = float(sum(right_vel) / len(right_vel)) if right_vel else None
    imbalance = None
    if left_mean is not None and right_mean is not None:
        top = max(left_mean, right_mean)
        imbalance = 0.0 if top == 0 else abs(left_mean - right_mean) / top

    short_ratio = 0.0
    long_ratio = 0.0
    if duration_ratios:
        short_ratio = len([r for r in duration_ratios if r <
                          0.6]) / len(duration_ratios)
        long_ratio = len([r for r in duration_ratios if r >
                         1.5]) / len(duration_ratios)

    abs_deltas = [abs(v) for v in deltas_ms]
    return {
        "timing": {
            "onset_error_ms_median": _safe_median(deltas_ms),
            "onset_error_ms_p90_abs": _safe_p90(abs_deltas),
            "onset_error_ms_mean_abs": float(sum(abs_deltas) / len(abs_deltas)) if abs_deltas else 0.0,
        },
        "duration": {
            "duration_ratio_median": _safe_median(duration_ratios),
            "duration_too_short_ratio": short_ratio,
            "duration_too_long_ratio": long_ratio,
        },
        "dynamics": {
            "left_mean_velocity": left_mean,
            "right_mean_velocity": right_mean,
            "velocity_imbalance": imbalance,
        },
    }


def analyze(
    ref_midi: str,
    attempt_midi: str,
    meta: dict,
    aligner: Aligner | None = None,
    segment_id: str | None = None,
    attempt_is_segment_relative: bool = False,
) -> AnalysisResult:
    _validate_timing_meta(meta)
    hand_split = int(meta.get("hand_split", {}).get("split_pitch", 60))
    segment_bounds = _segment_time_bounds(meta, segment_id=segment_id)
    raw_ref_notes = midi_to_notes(ref_midi, hand_split=hand_split)
    raw_attempt_notes = midi_to_notes(attempt_midi, hand_split=hand_split)
    ref_notes = _slice_to_segment(raw_ref_notes, segment_bounds)
    attempt_notes = _slice_to_segment(raw_attempt_notes, segment_bounds)
    if segment_bounds is not None:
        start_sec, end_sec = segment_bounds
        ref_notes = _shift_notes(ref_notes, start_sec)
        if attempt_is_segment_relative:
            segment_duration = end_sec - start_sec
            attempt_notes = [note for note in raw_attempt_notes if 0 <= note.start_sec < segment_duration]
        else:
            attempt_notes = _shift_notes(attempt_notes, start_sec)

    engine = aligner or DTWAligner()
    alignment = engine.align_offline(ref_notes, attempt_notes)

    match_tol_ms = float(meta.get("tolerance", {}).get("match_tol_ms", 80))
    chord_window_ms = float(
        meta.get("tolerance", {}).get("chord_window_ms", 50))
    short_ratio = float(meta.get("tolerance", {}).get("duration_short_ratio", 0.6))
    long_ratio = float(meta.get("tolerance", {}).get("duration_long_ratio", 1.5))
    if match_tol_ms < 0:
        raise ValueError("invalid match_tol_ms: must be >= 0")
    if chord_window_ms < 0:
        raise ValueError("invalid chord_window_ms: must be >= 0")
    if short_ratio <= 0:
        raise ValueError("invalid duration_short_ratio: must be > 0")
    if long_ratio <= 0:
        raise ValueError("invalid duration_long_ratio: must be > 0")
    if short_ratio >= long_ratio:
        raise ValueError("invalid duration ratios: duration_short_ratio must be < duration_long_ratio")
    valid_matches = _select_valid_matches(
        ref_notes=ref_notes,
        attempt_notes=attempt_notes,
        path=alignment.path,
        match_tol_ms=match_tol_ms,
    )

    ref_count = _dedup_ref_count(ref_notes, chord_window_ms=chord_window_ms)
    matched = len(valid_matches)
    match_rate = 0.0 if ref_count == 0 else matched / ref_count
    events = generate_events(
        ref=ref_notes,
        attempt=attempt_notes,
        alignment=alignment,
        meta=meta,
        segment_id=segment_id,
    )
    metrics = _build_metrics(
        ref_notes=ref_notes, attempt_notes=attempt_notes, matches=valid_matches)

    return AnalysisResult(
        ref_notes=ref_notes,
        attempt_notes=attempt_notes,
        events=events,
        metrics=metrics,
        match_rate=match_rate,
        quality_tier=_quality_tier(match_rate),
        alignment=alignment,
        matched=matched,
    )
