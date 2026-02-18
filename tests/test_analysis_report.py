from __future__ import annotations

from pathlib import Path

import mido

from xpiano.analysis import analyze
from xpiano.analysis import AnalysisResult
from xpiano.models import AlignmentResult, AnalysisEvent
from xpiano.reference import save_meta
from xpiano.report import build_report, save_report
from xpiano.schemas import validate


def _write_midi(path: Path, notes: list[tuple[float, float, int]], bpm: float = 100.0) -> None:
    ticks_per_beat = 480
    tempo = mido.bpm2tempo(bpm)
    mid = mido.MidiFile(ticks_per_beat=ticks_per_beat)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=tempo, time=0))
    track.append(mido.MetaMessage("time_signature",
                 numerator=4, denominator=4, time=0))

    abs_events: list[tuple[int, mido.Message]] = []
    for start_beat, dur_beat, pitch in notes:
        start_tick = int(start_beat * ticks_per_beat)
        end_tick = int((start_beat + dur_beat) * ticks_per_beat)
        abs_events.append((start_tick, mido.Message(
            "note_on", note=pitch, velocity=80, time=0)))
        abs_events.append((end_tick, mido.Message(
            "note_off", note=pitch, velocity=0, time=0)))

    abs_events.sort(key=lambda item: (
        item[0], 0 if item[1].type == "note_off" else 1))
    last_tick = 0
    for abs_tick, msg in abs_events:
        delta = abs_tick - last_tick
        track.append(msg.copy(time=delta))
        last_tick = abs_tick
    track.append(mido.MetaMessage("end_of_track", time=1))
    mid.save(str(path))


def _meta() -> dict:
    return {
        "song_id": "demo",
        "time_signature": {"beats_per_measure": 4, "beat_unit": 4},
        "bpm": 100,
        "segments": [{"segment_id": "verse1", "start_measure": 1, "end_measure": 1}],
        "tolerance": {
            "match_tol_ms": 80,
            "timing_grades": {"great_ms": 25, "good_ms": 50, "rushed_dragged_ms": 100},
            "chord_window_ms": 50,
            "duration_short_ratio": 0.6,
            "duration_long_ratio": 1.5,
        },
        "hand_split": {"split_pitch": 60},
    }


def _meta_two_segments() -> dict:
    meta = _meta()
    meta["segments"] = [
        {"segment_id": "verse1", "start_measure": 1, "end_measure": 1},
        {"segment_id": "verse2", "start_measure": 2, "end_measure": 2},
    ]
    return meta


def test_analysis_quality_tiers(tmp_path: Path) -> None:
    ref_mid = tmp_path / "ref.mid"
    good_mid = tmp_path / "good.mid"
    bad_mid = tmp_path / "bad.mid"
    notes = [(0.0, 1.0, 60), (1.0, 1.0, 62), (2.0, 1.0, 64), (3.0, 1.0, 65)]
    _write_midi(ref_mid, notes)
    _write_midi(good_mid, notes)
    _write_midi(bad_mid, [(0.0, 1.0, 70), (1.0, 1.0, 71),
                (2.0, 1.0, 72), (3.0, 1.0, 73)])

    meta = _meta()
    good = analyze(str(ref_mid), str(good_mid), meta)
    bad = analyze(str(ref_mid), str(bad_mid), meta)

    assert good.quality_tier == "full"
    assert good.match_rate >= 0.99
    assert bad.quality_tier == "too_low"
    assert bad.match_rate == 0.0


def test_report_build_and_save(tmp_path: Path, xpiano_home: Path) -> None:
    ref_mid = tmp_path / "ref.mid"
    attempt_mid = tmp_path / "attempt.mid"
    notes = [(0.0, 1.0, 60), (1.0, 1.0, 62), (2.0, 1.0, 64), (3.0, 1.0, 65)]
    _write_midi(ref_mid, notes)
    _write_midi(attempt_mid, notes)

    meta = _meta()
    save_meta(song_id="demo", meta=meta)
    result = analyze(str(ref_mid), str(attempt_mid), meta)
    report = build_report(
        result=result,
        meta=meta,
        ref_path=ref_mid,
        attempt_path=attempt_mid,
        song_id="demo",
        segment_id="verse1",
    )
    assert validate("report", report) == []
    report_path = save_report(report=report, song_id="demo")
    assert report_path.exists()


def test_report_marks_simplified_as_low_quality(tmp_path: Path) -> None:
    ref_mid = tmp_path / "ref.mid"
    attempt_mid = tmp_path / "attempt.mid"
    _write_midi(ref_mid, [(0.0, 1.0, 60), (1.0, 1.0, 62), (2.0, 1.0, 64), (3.0, 1.0, 65)])
    _write_midi(attempt_mid, [(0.0, 1.0, 60), (1.0, 1.0, 70), (2.0, 1.0, 71), (3.0, 1.0, 72)])

    meta = _meta()
    result = analyze(str(ref_mid), str(attempt_mid), meta)
    assert result.quality_tier == "simplified"
    report = build_report(
        result=result,
        meta=meta,
        ref_path=ref_mid,
        attempt_path=attempt_mid,
        song_id="demo",
        segment_id="verse1",
    )
    assert report["status"] == "low_quality"


def test_analysis_slices_notes_to_segment(tmp_path: Path) -> None:
    ref_mid = tmp_path / "ref.mid"
    attempt_mid = tmp_path / "attempt.mid"
    notes = [
        (0.0, 1.0, 60),  # measure 1
        (1.0, 1.0, 62),
        (2.0, 1.0, 64),
        (3.0, 1.0, 65),
        (4.0, 1.0, 67),  # measure 2
        (5.0, 1.0, 69),
        (6.0, 1.0, 71),
        (7.0, 1.0, 72),
    ]
    _write_midi(ref_mid, notes)
    _write_midi(attempt_mid, notes)

    meta = _meta()
    meta["segments"] = [{"segment_id": "verse2", "start_measure": 2, "end_measure": 2}]
    result = analyze(str(ref_mid), str(attempt_mid), meta)
    assert len(result.ref_notes) == 4
    assert len(result.attempt_notes) == 4


def test_analysis_selects_target_segment_in_multi_segment_meta(tmp_path: Path) -> None:
    ref_mid = tmp_path / "ref.mid"
    attempt_mid = tmp_path / "attempt.mid"
    notes = [
        (0.0, 1.0, 60),  # measure 1
        (1.0, 1.0, 62),
        (2.0, 1.0, 64),
        (3.0, 1.0, 65),
        (4.0, 1.0, 67),  # measure 2
        (5.0, 1.0, 69),
        (6.0, 1.0, 71),
        (7.0, 1.0, 72),
    ]
    _write_midi(ref_mid, notes)
    _write_midi(attempt_mid, notes)

    result = analyze(str(ref_mid), str(attempt_mid), _meta_two_segments(), segment_id="verse2")
    assert len(result.ref_notes) == 4
    assert len(result.attempt_notes) == 4
    assert result.match_rate >= 0.99
    assert all(event.measure == 2 for event in result.events)


def test_analysis_handles_segment_relative_attempt_recording(tmp_path: Path) -> None:
    ref_mid = tmp_path / "ref.mid"
    attempt_mid = tmp_path / "attempt.mid"
    ref_notes = [
        (0.0, 1.0, 60),  # measure 1
        (1.0, 1.0, 62),
        (2.0, 1.0, 64),
        (3.0, 1.0, 65),
        (4.0, 1.0, 67),  # measure 2
        (5.0, 1.0, 69),
        (6.0, 1.0, 71),
        (7.0, 1.0, 72),
    ]
    segment_local_attempt = [
        (0.0, 1.0, 67),
        (1.0, 1.0, 69),
        (2.0, 1.0, 71),
        (3.0, 1.0, 72),
    ]
    _write_midi(ref_mid, ref_notes)
    _write_midi(attempt_mid, segment_local_attempt)

    result = analyze(
        str(ref_mid),
        str(attempt_mid),
        _meta_two_segments(),
        segment_id="verse2",
        attempt_is_segment_relative=True,
    )
    assert result.match_rate >= 0.99
    assert all(event.measure == 2 for event in result.events)


def test_report_limits_top_problems_for_simplified_quality(tmp_path: Path) -> None:
    result = AnalysisResult(
        ref_notes=[],
        attempt_notes=[],
        events=[
            AnalysisEvent(type="missing_note", measure=1, beat=1.0, pitch=60, pitch_name="C4", hand="R", severity="high"),
            AnalysisEvent(type="extra_note", measure=2, beat=1.0, pitch=61, pitch_name="C#4", hand="R", severity="med"),
            AnalysisEvent(type="wrong_pitch", measure=3, beat=1.0, pitch=62, pitch_name="D4", hand="R", severity="high"),
            AnalysisEvent(type="timing_late", measure=4, beat=1.0, pitch=63, pitch_name="D#4", hand="R", severity="low"),
            AnalysisEvent(type="duration_short", measure=5, beat=1.0, pitch=64, pitch_name="E4", hand="R", severity="med"),
        ],
        metrics={"timing": {}, "duration": {}, "dynamics": {}},
        match_rate=0.3,
        quality_tier="simplified",
        alignment=AlignmentResult(path=[], cost=0.0, method="test"),
        matched=0,
    )
    report = build_report(
        result=result,
        meta=_meta(),
        ref_path=tmp_path / "ref.mid",
        attempt_path=tmp_path / "attempt.mid",
        song_id="demo",
        segment_id="verse1",
    )
    assert len(report["summary"]["top_problems"]) == 3


def test_report_hides_top_problems_for_too_low_quality(tmp_path: Path) -> None:
    result = AnalysisResult(
        ref_notes=[],
        attempt_notes=[],
        events=[
            AnalysisEvent(type="missing_note", measure=1, beat=1.0, pitch=60, pitch_name="C4", hand="R", severity="high"),
            AnalysisEvent(type="extra_note", measure=2, beat=1.0, pitch=61, pitch_name="C#4", hand="R", severity="med"),
            AnalysisEvent(type="wrong_pitch", measure=3, beat=1.0, pitch=62, pitch_name="D4", hand="R", severity="high"),
        ],
        metrics={"timing": {}, "duration": {}, "dynamics": {}},
        match_rate=0.05,
        quality_tier="too_low",
        alignment=AlignmentResult(path=[], cost=0.0, method="test"),
        matched=0,
    )
    report = build_report(
        result=result,
        meta=_meta(),
        ref_path=tmp_path / "ref.mid",
        attempt_path=tmp_path / "attempt.mid",
        song_id="demo",
        segment_id="verse1",
    )
    assert report["summary"]["top_problems"] == []
