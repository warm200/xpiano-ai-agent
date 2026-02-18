from __future__ import annotations

from xpiano.models import MeasureBeat


def time_to_measure_beat(
    time_sec: float,
    bpm: float,
    beats_per_measure: int,
    start_measure: int = 1,
) -> MeasureBeat:
    if bpm <= 0:
        raise ValueError("bpm must be > 0")
    if beats_per_measure <= 0:
        raise ValueError("beats_per_measure must be > 0")
    if beats_per_measure > 12:
        raise ValueError("beats_per_measure must be <= 12")
    if start_measure <= 0:
        raise ValueError("start_measure must be > 0")
    if time_sec < 0:
        time_sec = 0

    beat_duration = 60.0 / bpm
    total_beats = time_sec / beat_duration
    measure = start_measure + int(total_beats // beats_per_measure)
    beat = 1.0 + (total_beats % beats_per_measure)
    return MeasureBeat(measure=measure, beat=beat)
