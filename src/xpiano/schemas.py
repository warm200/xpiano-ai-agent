from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator

META_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "xpiano.meta.schema.json",
    "title": "XPiano Song Meta (song-level, contains segments[])",
    "type": "object",
    "required": ["song_id", "time_signature", "bpm", "segments", "tolerance"],
    "properties": {
        "song_id": {"type": "string", "minLength": 1},
        "title": {"type": "string"},
        "composer": {"type": "string"},
        "time_signature": {
            "type": "object",
            "required": ["beats_per_measure", "beat_unit"],
            "properties": {
                "beats_per_measure": {"type": "integer", "minimum": 1, "maximum": 12},
                "beat_unit": {"type": "integer", "enum": [1, 2, 4, 8, 16]},
            },
            "additionalProperties": False,
        },
        "bpm": {"type": "number", "minimum": 20, "maximum": 240},
        "key_signature": {"type": "string"},
        "segments": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["segment_id", "start_measure", "end_measure"],
                "properties": {
                    "segment_id": {"type": "string", "minLength": 1},
                    "label": {"type": "string"},
                    "start_measure": {"type": "integer", "minimum": 1},
                    "end_measure": {"type": "integer", "minimum": 1},
                    "count_in_measures": {"type": "integer", "minimum": 1, "maximum": 4, "default": 1},
                },
                "additionalProperties": False,
            },
        },
        "hand_split": {
            "type": "object",
            "properties": {
                "split_pitch": {"type": "integer", "minimum": 0, "maximum": 127, "default": 60},
            },
            "additionalProperties": False,
        },
        "tolerance": {
            "type": "object",
            "required": ["match_tol_ms", "timing_grades"],
            "properties": {
                "match_tol_ms": {"type": "integer", "minimum": 20, "maximum": 300, "default": 80},
                "timing_grades": {
                    "type": "object",
                    "required": ["great_ms", "good_ms", "rushed_dragged_ms"],
                    "properties": {
                        "great_ms": {"type": "integer", "minimum": 5, "maximum": 100, "default": 25},
                        "good_ms": {"type": "integer", "minimum": 10, "maximum": 150, "default": 50},
                        "rushed_dragged_ms": {"type": "integer", "minimum": 20, "maximum": 300, "default": 100},
                    },
                    "additionalProperties": False,
                },
                "chord_window_ms": {"type": "integer", "minimum": 10, "maximum": 200, "default": 50},
                "duration_short_ratio": {"type": "number", "minimum": 0.1, "maximum": 1.0, "default": 0.6},
                "duration_long_ratio": {"type": "number", "minimum": 1.0, "maximum": 5.0, "default": 1.5},
            },
            "additionalProperties": False,
        },
    },
    "additionalProperties": False,
}

REPORT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "xpiano.report.schema.json",
    "title": "XPiano Analysis Report",
    "type": "object",
    "required": ["version", "song_id", "segment_id", "status", "inputs", "summary", "events", "metrics"],
    "properties": {
        "version": {"type": "string", "default": "0.1"},
        "song_id": {"type": "string"},
        "segment_id": {"type": "string"},
        "inputs": {
            "type": "object",
            "required": ["reference_mid", "attempt_mid", "meta"],
            "properties": {
                "reference_mid": {"type": "string"},
                "attempt_mid": {"type": "string"},
                "meta": {"type": "object"},
            },
            "additionalProperties": False,
        },
        "status": {"type": "string", "enum": ["ok", "low_quality", "error"]},
        "summary": {
            "type": "object",
            "required": ["counts", "match_rate"],
            "properties": {
                "counts": {
                    "type": "object",
                    "required": ["ref_notes", "attempt_notes", "matched", "missing", "extra"],
                    "properties": {
                        "ref_notes": {"type": "integer", "minimum": 0},
                        "attempt_notes": {"type": "integer", "minimum": 0},
                        "matched": {"type": "integer", "minimum": 0},
                        "missing": {"type": "integer", "minimum": 0},
                        "extra": {"type": "integer", "minimum": 0},
                    },
                    "additionalProperties": False,
                },
                "match_rate": {"type": "number", "minimum": 0, "maximum": 1},
                "top_problems": {"type": "array", "minItems": 0, "maxItems": 5, "items": {"type": "string"}},
            },
            "additionalProperties": False,
        },
        "metrics": {
            "type": "object",
            "required": ["timing", "duration", "dynamics"],
            "properties": {
                "timing": {
                    "type": "object",
                    "properties": {
                        "onset_error_ms_median": {"type": "number"},
                        "onset_error_ms_p90_abs": {"type": "number"},
                        "onset_error_ms_mean_abs": {"type": "number"},
                    },
                    "additionalProperties": False,
                },
                "duration": {
                    "type": "object",
                    "properties": {
                        "duration_ratio_median": {"type": "number"},
                        "duration_too_short_ratio": {"type": "number", "minimum": 0, "maximum": 1},
                        "duration_too_long_ratio": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                    "additionalProperties": False,
                },
                "dynamics": {
                    "type": "object",
                    "properties": {
                        "left_mean_velocity": {"type": ["number", "null"]},
                        "right_mean_velocity": {"type": ["number", "null"]},
                        "velocity_imbalance": {"type": ["number", "null"]},
                    },
                    "additionalProperties": False,
                },
            },
            "additionalProperties": False,
        },
        "events": {
            "type": "array",
            "minItems": 0,
            "items": {
                "type": "object",
                "required": ["type", "measure", "beat", "severity"],
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": [
                            "missing_note",
                            "extra_note",
                            "wrong_pitch",
                            "timing_early",
                            "timing_late",
                            "duration_short",
                            "duration_long",
                        ],
                    },
                    "measure": {"type": "integer", "minimum": 1},
                    "beat": {"type": "number", "minimum": 1},
                    "pitch": {"type": ["integer", "null"], "minimum": 0, "maximum": 127},
                    "pitch_name": {"type": "string", "minLength": 1},
                    "actual_pitch": {"type": ["integer", "null"], "minimum": 0, "maximum": 127},
                    "actual_pitch_name": {"type": ["string", "null"]},
                    "hand": {"type": "string", "enum": ["L", "R", "U"]},
                    "severity": {"type": "string", "enum": ["low", "med", "high"]},
                    "evidence": {"type": ["string", "null"]},
                    "time_ref_sec": {"type": ["number", "null"]},
                    "time_attempt_sec": {"type": ["number", "null"]},
                    "delta_ms": {"type": ["number", "null"]},
                    "expected_duration_sec": {"type": ["number", "null"]},
                    "actual_duration_sec": {"type": ["number", "null"]},
                    "group_id": {"type": ["string", "null"]},
                },
                "additionalProperties": False,
            },
        },
        "examples": {
            "type": "object",
            "properties": {
                "missing_first_10": {"type": "array", "items": {"type": "object"}},
                "extra_first_10": {"type": "array", "items": {"type": "object"}},
            },
            "additionalProperties": False,
        },
    },
    "additionalProperties": False,
}

LLM_OUTPUT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "xpiano.llm_output.schema.json",
    "title": "XPiano LLM Coaching Output",
    "type": "object",
    "required": ["goal", "top_issues", "drills", "pass_conditions", "next_recording"],
    "properties": {
        "goal": {"type": "string", "minLength": 1},
        "top_issues": {
            "type": "array",
            "minItems": 1,
            "maxItems": 3,
            "items": {
                "type": "object",
                "required": ["title", "why", "evidence"],
                "properties": {
                    "title": {"type": "string"},
                    "why": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                },
                "additionalProperties": False,
            },
        },
        "drills": {
            "type": "array",
            "minItems": 2,
            "maxItems": 4,
            "items": {
                "type": "object",
                "required": ["name", "minutes", "bpm", "how", "reps", "focus_measures"],
                "properties": {
                    "name": {"type": "string"},
                    "minutes": {"type": "number", "minimum": 1, "maximum": 20},
                    "bpm": {"type": "number", "minimum": 20, "maximum": 240},
                    "how": {"type": "array", "items": {"type": "string"}, "minItems": 2},
                    "reps": {"type": "string"},
                    "focus_measures": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        "pass_conditions": {
            "type": "object",
            "required": ["before_speed_up", "speed_up_rule"],
            "properties": {
                "before_speed_up": {"type": "array", "items": {"type": "string"}, "minItems": 2},
                "speed_up_rule": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "next_recording": {
            "type": "object",
            "required": ["what_to_record", "tips"],
            "properties": {
                "what_to_record": {"type": "string"},
                "tips": {"type": "array", "items": {"type": "string"}, "minItems": 2},
            },
            "additionalProperties": False,
        },
        "tool_calls": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["position", "action"],
                "properties": {
                    "position": {
                        "type": "string",
                        "enum": [
                            "after_issue_1",
                            "after_issue_2",
                            "after_issue_3",
                            "before_drill_1",
                            "after_drill_1",
                            "before_drill_2",
                            "after_drill_2",
                            "summary_end",
                        ],
                    },
                    "action": {
                        "type": "object",
                        "required": ["type", "source"],
                        "properties": {
                            "type": {"const": "playback"},
                            "source": {"type": "string", "enum": ["reference", "attempt", "comparison"]},
                            "measures": {
                                "type": "object",
                                "properties": {
                                    "start": {"type": "integer"},
                                    "end": {"type": "integer"},
                                },
                                "additionalProperties": False,
                            },
                            "bpm": {"type": "number", "minimum": 20, "maximum": 240},
                            "highlight_pitches": {"type": "array", "items": {"type": "string"}},
                            "delay_between_sec": {"type": "number"},
                        },
                        "additionalProperties": False,
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    "additionalProperties": False,
}

SCHEMAS = {
    "meta": META_SCHEMA,
    "report": REPORT_SCHEMA,
    "llm_output": LLM_OUTPUT_SCHEMA,
}


def validate(schema_name: str, data: dict[str, Any]) -> list[str]:
    schema = SCHEMAS.get(schema_name)
    if schema is None:
        return [f"unknown schema: {schema_name}"]
    validator = Draft202012Validator(schema)
    errors: list[str] = []
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
        path = "/".join(str(item) for item in err.path)
        errors.append(f"{path or '$'}: {err.message}")
    return errors
