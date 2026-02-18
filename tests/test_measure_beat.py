from __future__ import annotations

from xpiano.measure_beat import time_to_measure_beat


def test_time_to_measure_beat_basic() -> None:
    pos = time_to_measure_beat(time_sec=0.0, bpm=120.0, beats_per_measure=4)
    assert pos.measure == 1
    assert pos.beat == 1.0


def test_time_to_measure_beat_fractional() -> None:
    pos = time_to_measure_beat(time_sec=1.5, bpm=60.0, beats_per_measure=4)
    assert pos.measure == 1
    assert pos.beat == 2.5
