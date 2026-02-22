from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass
class NoteEvent:
    pitch: int
    pitch_name: str
    start_sec: float
    end_sec: float
    dur_sec: float
    velocity: int
    hand: Literal["L", "R", "U"]


@dataclass
class MeasureBeat:
    measure: int
    beat: float


@dataclass
class AnalysisEvent:
    type: Literal[
        "missing_note",
        "extra_note",
        "wrong_pitch",
        "timing_early",
        "timing_late",
        "duration_short",
        "duration_long",
    ]
    measure: int
    beat: float
    pitch: int | None
    pitch_name: str
    hand: Literal["L", "R", "U"]
    severity: Literal["low", "med", "high"]
    evidence: str | None = None
    delta_ms: float | None = None
    time_ref_sec: float | None = None
    time_attempt_sec: float | None = None
    expected_duration_sec: float | None = None
    actual_duration_sec: float | None = None
    actual_pitch: int | None = None
    actual_pitch_name: str | None = None
    group_id: str | None = None


@dataclass
class AlignmentResult:
    path: list[tuple[int, int]]
    cost: float
    method: str
    warp_scale: float | None = None
    warp_offset_sec: float | None = None


@dataclass
class ScorePosition:
    note_index: int
    measure: int
    beat: float
    confidence: float


@dataclass
class PlayResult:
    status: Literal["played", "no_device", "cancelled"]
    duration_sec: float
