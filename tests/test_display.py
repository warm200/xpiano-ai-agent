from __future__ import annotations

from xpiano.display import (render_low_match, render_piano_roll_diff,
                            render_playback_indicator, render_report,
                            render_streaming_text, render_wait_step)


def _report() -> dict:
    return {
        "summary": {
            "counts": {"ref_notes": 10, "attempt_notes": 9, "matched": 7, "missing": 3, "extra": 2},
            "match_rate": 0.7,
            "top_problems": ["M2 wrong_pitch x2"],
        },
        "events": [
            {"type": "wrong_pitch", "measure": 2, "beat": 3.0,
                "pitch_name": "E4", "actual_pitch_name": "F4"},
            {"type": "missing_note", "measure": 2,
                "beat": 4.0, "pitch_name": "G4"},
        ],
    }


def test_render_report_contains_summary() -> None:
    text = render_report(_report())
    assert "match_rate=0.70" in text
    assert "M2 wrong_pitch x2" in text


def test_render_low_match_contains_commands() -> None:
    text = render_low_match(match_rate=0.12, song="twinkle", segment="verse1")
    assert "xpiano playback" in text
    assert "xpiano wait" in text


def test_render_piano_roll_diff_contains_wrong_pitch() -> None:
    text = render_piano_roll_diff(_report())
    assert "wrong F4 -> expected E4" in text


def test_render_wait_step() -> None:
    text = render_wait_step(2, 3.0, ["C4", "E4"])
    assert "M2" in text
    assert "C4 E4" in text


def test_render_streaming_text_passthrough() -> None:
    assert render_streaming_text("hello") == "hello"


def test_render_playback_indicator() -> None:
    text = render_playback_indicator("reference", "2-3")
    assert "reference" in text
    assert "2-3" in text
