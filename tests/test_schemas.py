from __future__ import annotations

from xpiano.schemas import validate


def test_meta_schema_validates() -> None:
    meta = {
        "song_id": "twinkle",
        "time_signature": {"beats_per_measure": 4, "beat_unit": 4},
        "bpm": 80,
        "segments": [{"segment_id": "verse1", "start_measure": 1, "end_measure": 4}],
        "tolerance": {"match_tol_ms": 80, "timing_grades": {"great_ms": 25, "good_ms": 50, "rushed_dragged_ms": 100}},
    }
    assert validate("meta", meta) == []


def test_report_schema_validates() -> None:
    report = {
        "version": "0.1",
        "song_id": "twinkle",
        "segment_id": "verse1",
        "status": "ok",
        "inputs": {"reference_mid": "a.mid", "attempt_mid": "b.mid", "meta": {}},
        "summary": {
            "counts": {"ref_notes": 10, "attempt_notes": 10, "matched": 8, "missing": 2, "extra": 2},
            "match_rate": 0.8,
            "top_problems": [],
        },
        "metrics": {"timing": {}, "duration": {}, "dynamics": {}},
        "events": [],
    }
    assert validate("report", report) == []


def test_llm_output_schema_validates() -> None:
    output = {
        "goal": "Stabilize timing in bar 2",
        "top_issues": [{"title": "Late notes", "why": "beat drift", "evidence": ["M2 beat3 late"]}],
        "drills": [
            {
                "name": "Slow hands-together",
                "minutes": 6,
                "bpm": 50,
                "how": ["Play bar 2 only", "Count out loud"],
                "reps": "5x clean",
                "focus_measures": "2",
            },
            {
                "name": "Metronome lock",
                "minutes": 5,
                "bpm": 55,
                "how": ["Accent beat 1", "Stay relaxed"],
                "reps": "4x",
                "focus_measures": "1-2",
            },
        ],
        "pass_conditions": {
            "before_speed_up": ["No missed notes in M2", "Onset p90 < 80ms"],
            "speed_up_rule": "+5 BPM after 2 clean reps",
        },
        "next_recording": {"what_to_record": "M1-M2", "tips": ["Keep wrist loose", "Watch beat 3"]},
    }
    assert validate("llm_output", output) == []
