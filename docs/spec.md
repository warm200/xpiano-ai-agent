# XPiano Engineering Spec (MVP: M0–M3)

> Derived from [`prd.md`](prd.md) + [`post-mvp.md`](post-mvp.md).
> Post-MVP (M5–M8) noted as extension points only.

---

## 1. Project Setup

### Runtime & Tooling

| Item | Value |
|------|-------|
| Python | >= 3.10 |
| Package manager | `uv` (lockfile: `uv.lock`) |
| Build system | `pyproject.toml` (hatchling or setuptools) |
| CLI framework | `typer` (preferred) or `click` |
| Entry point | `xpiano` (console_scripts) |
| User data dir | `~/.xpiano/` |
| Config | `~/.xpiano/config.yaml` |
| Linting/format | flake8, isort, autopep8, pyupgrade, mypy |
| Tests | pytest |

### Dependencies (MVP)

| Package | Purpose |
|---------|---------|
| `mido` | MIDI file read/write, real-time I/O |
| `python-rtmidi` | MIDI device detection & real-time record/playback |
| `pretty_midi` | MIDI → NoteEvent parsing, pitch_name conversion |
| `numpy` | DTW alignment math, metrics |
| `fastdtw` | Dynamic time warping |
| `typer` | CLI framework |
| `rich` | Terminal formatting, piano roll diff, Live display |
| `anthropic` | Claude API (default LLM provider) |
| `jsonschema` | Schema validation for meta/report/llm_output |
| `pyyaml` | config.yaml parsing |

### pyproject.toml skeleton

```toml
[project]
name = "xpiano"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "mido>=1.3",
    "python-rtmidi>=1.5",
    "pretty_midi>=0.2",
    "numpy>=1.24",
    "fastdtw>=0.3",
    "typer>=0.12",
    "rich>=13.0",
    "anthropic>=0.39",
    "jsonschema>=4.20",
    "pyyaml>=6.0",
]

[project.scripts]
xpiano = "xpiano.cli:app"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

---

## 2. File / Module Map

```
src/xpiano/
├── __init__.py
├── cli.py               # Typer app, all commands
├── midi_io.py           # Device detect, record, playback (raw MIDI I/O)
├── reference.py         # Import, store, meta.json CRUD
├── parser.py            # MIDI → NoteEvent[] via pretty_midi
├── alignment.py         # Aligner ABC + DTWAligner impl
├── analysis.py          # Orchestrator: parse → align → match → events → report
├── events.py            # Event generation + wrong_pitch post-processing
├── measure_beat.py      # time_sec ↔ (measure, beat) mapping
├── report.py            # report.json assembly + schema validation
├── llm_provider.py      # LLMProvider ABC + ClaudeProvider
├── llm_coach.py         # report → prompt → llm_output.json
├── playback.py          # 3-mode playback engine (ref/attempt/comparison)
├── wait_mode.py         # Wait Mode: pitch-set matching, no alignment needed
├── schemas.py           # Embedded JSON schemas + validate() helpers
├── config.py            # ~/.xpiano/config.yaml load/defaults
├── models.py            # Dataclasses: NoteEvent, AnalysisEvent, etc.
└── display.py           # Rich formatting: report, piano roll diff, streaming

tests/
├── conftest.py          # Fixtures: sample MIDI bytes, NoteEvent lists
├── test_parser.py
├── test_measure_beat.py
├── test_alignment.py
├── test_events.py
├── test_report.py
├── test_llm_coach.py
├── test_playback.py
├── test_wait_mode.py
├── test_cli.py
└── test_schemas.py
```

### User data layout (`~/.xpiano/`)

```
~/.xpiano/
├── config.yaml
└── songs/
    └── <song_id>/
        ├── meta.json
        ├── reference.mid
        ├── reference_notes.json
        ├── attempts/
        │   └── <YYYYMMDD_HHMM>.mid
        └── reports/
            └── <YYYYMMDD_HHMM>.json
```

---

## 3. Data Model

### `models.py` — core types

```python
from dataclasses import dataclass
from typing import Literal

@dataclass
class NoteEvent:
    pitch: int                        # MIDI 0-127
    pitch_name: str                   # e.g. "C4"
    start_sec: float
    end_sec: float
    dur_sec: float
    velocity: int
    hand: Literal["L", "R", "U"]     # U = unknown

@dataclass
class MeasureBeat:
    measure: int                      # 1-based
    beat: float                       # 1-based, fractional for subdivisions

@dataclass
class AnalysisEvent:
    type: Literal[
        "missing_note", "extra_note", "wrong_pitch",
        "timing_early", "timing_late",
        "duration_short", "duration_long",
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
    actual_pitch: int | None = None          # wrong_pitch only
    actual_pitch_name: str | None = None     # wrong_pitch only
    group_id: str | None = None

@dataclass
class AlignmentResult:
    path: list[tuple[int, int]]   # DTW index pairs (ref_idx, attempt_idx)
    cost: float
    method: str                    # "per_pitch_dtw" | "hmm_matchmaker" etc.

@dataclass
class ScorePosition:
    """Online aligner output (Post-MVP stub)."""
    note_index: int
    measure: int
    beat: float
    confidence: float

@dataclass
class PlayResult:
    status: Literal["played", "no_device", "cancelled"]
    duration_sec: float
```

### Measure/Beat mapping

```python
def time_to_measure_beat(
    time_sec: float,
    bpm: float,
    beats_per_measure: int,
    start_measure: int = 1,
) -> MeasureBeat:
    """Convert absolute time (sec) to (measure, beat).

    beat_dur = 60 / bpm
    total_beats = time_sec / beat_dur
    measure = start_measure + int(total_beats // beats_per_measure)
    beat = 1 + (total_beats % beats_per_measure)
    """
```

---

## 4. Module Specs

### 4.1 MIDI I/O (`midi_io.py`)

**Responsibilities:** device enumeration, real-time MIDI record, MIDI output playback.

| Function | Signature | Notes |
|----------|-----------|-------|
| `list_devices` | `() -> list[MidiDevice]` | Uses `mido.get_input_names()` / `get_output_names()` |
| `record` | `(port, duration_sec, count_in_beats, bpm, stop_on_enter=False) -> mido.MidiFile` | Fixed-length by default; with `stop_on_enter` records until Enter; count-in clicks; returns MidiFile |
| `play_midi` | `(port, midi, bpm, start_sec, end_sec, highlight_pitches, velocity_boost) -> PlayResult` | Tempo-scaled playback; boost velocity on highlighted pitches |

**Count-in:** send `count_in_beats` click notes (MIDI note 37, channel 9) at target BPM before recording.

**Fixed-length recording:** `duration_sec = num_measures * beats_per_measure * (60/bpm)`.

### 4.2 Reference Manager (`reference.py`)

| Function | Signature | Notes |
|----------|-----------|-------|
| `import_reference` | `(midi_path, song_id) -> Path` | Copy MIDI → `~/.xpiano/songs/<id>/reference.mid`; parse → `reference_notes.json` |
| `record_reference` | `(song_id, segment_id, port, until_enter=False) -> Path` | Record via `midi_io.record`, save as reference |
| `save_meta` | `(song_id, meta) -> Path` | Write + validate against meta schema |
| `load_meta` | `(song_id) -> dict` | Read + validate |
| `list_songs` | `() -> list[SongInfo]` | Scan `~/.xpiano/songs/`, return summaries |
| `save_attempt` | `(song_id, midi) -> Path` | Save to `attempts/<timestamp>.mid` |

### 4.3 Parser (`parser.py`)

| Function | Signature | Notes |
|----------|-----------|-------|
| `midi_to_notes` | `(midi_path, hand_split=60) -> list[NoteEvent]` | Uses `pretty_midi`; assigns hand by pitch split |

**Pitch naming:** `pretty_midi.note_number_to_name(pitch)`.

**Hand assignment (MVP):** `pitch < hand_split → "L"`, else `"R"`. Configurable via `meta.json.hand_split.split_pitch`.

### 4.4 Alignment (`alignment.py`)

**Pluggable design** — same pattern as `LLMProvider`:

```python
class Aligner(ABC):
    @abstractmethod
    def align_offline(self, ref: list[NoteEvent], attempt: list[NoteEvent]) -> AlignmentResult:
        """Offline alignment: post-recording analysis. MVP default."""
        ...

    def align_online(self, ref: list[NoteEvent]) -> OnlineAligner:
        """Online tracking: real-time note following. Post-MVP."""
        raise NotImplementedError("Online alignment not available in MVP")

class OnlineAligner(ABC):
    """Post-MVP: real-time score follower (Wait Mode / live feedback)."""
    @abstractmethod
    def feed(self, event: NoteEvent) -> ScorePosition:
        ...
```

**Current default implementation — `HMMAligner` (pair-HMM/Viterbi):**

| Function | Notes |
|----------|-------|
| `align_offline` | Global sequence alignment with HMM-style transitions (`match` / `skip_ref` / `skip_attempt`) |

- **Emission model:** match requires same pitch; onset cost computed on warped attempt timeline.
- **Tempo robustness:** estimates affine warp `t_ref ~= t_attempt * scale + offset` before scoring.
- **Output:** `AlignmentResult.path` + warp params (`warp_scale`, `warp_offset_sec`) reused by analysis/events.

**Fallback implementation — `DTWAligner`:**

| Function | Notes |
|----------|-------|
| `align_offline` | Per-pitch DTW (group by pitch, DTW each onset sequence, merge) |

- **DTW features:** each note → `(pitch, onset_sec)`. Cost: pitch same → `|onset_diff|`; pitch different → `∞`.
- **Flow:** group by pitch → DTW per group → merge warp → unmatched ref = `missing_note`, unmatched attempt = `extra_note`.
- **Match tolerance:** `tol_ms` (default 80, configurable). Onset diff > tol_ms → not matched.

**Post-MVP:** `MatchmakerHMMAligner` wrapping [Matchmaker](https://github.com/CPJKU/matchmaker) (HMM score follower, ~1.5ms latency, handles skips/errors natively).

#### Chord Pitch-set Grouping

Reference notes within the same beat window (`chord_window_ms`, default 50) are grouped into a **pitch-set**.

- Attempt notes matched against the set (not individual onsets).
- Full hit → matched; partial → matched pitches + `missing_note` for absent + `extra_note` for surplus.
- Evidence: `"chord partial: hit 2/3 [C4,E4] missing [G4]"`.

### 4.5 Events (`events.py`)

**Responsibilities:** compare matched notes → generate `AnalysisEvent` list; `wrong_pitch` post-processing.

| Function | Signature | Notes |
|----------|-----------|-------|
| `generate_events` | `(ref, attempt, alignment, meta) -> list[AnalysisEvent]` | Core matching + event generation |
| `merge_wrong_pitch` | `(events) -> list[AnalysisEvent]` | Post-processing: merge missing+extra at same beat into wrong_pitch |

**Matching algorithm:**

1. For each ref note, find closest aligned attempt note within `match_tol_ms`.
2. Unmatched ref → `missing_note` (severity=high).
3. Unmatched attempt → `extra_note` (severity=med).
4. Matched pairs: check timing + duration thresholds.
5. Attach `measure`, `beat` via `measure_beat.time_to_measure_beat()`.

**Timing severity (tiered thresholds from `meta.tolerance.timing_grades`):**

| Onset delta | Grade | Event generated? | Severity |
|-------------|-------|------------------|----------|
| ≤ great_ms (25) | Great | No | — |
| great_ms – good_ms (25–50) | Good | Yes | low |
| good_ms – rushed_dragged_ms (50–100) | Rushed/Dragged | Yes | med |
| > rushed_dragged_ms (100) | Bad | Yes | high |

**Duration severity:**

| Condition | Severity |
|-----------|----------|
| ratio < 0.4 or > 2.0 | high |
| ratio outside [short_ratio, long_ratio] | med |

**`wrong_pitch` post-processing:**

After initial event generation, scan for `(measure, beat)` pairs that have both a `missing_note` and an `extra_note`. Merge into a single `wrong_pitch` event:
- `pitch_name` = expected (from reference)
- `actual_pitch_name` = what user played
- `evidence` = `"played F4, expected E4"`
- `severity` = high

### 4.6 Analysis Engine (`analysis.py`)

**Orchestrates:** parse → align → events → metrics → quality gate → report.

| Function | Signature | Notes |
|----------|-----------|-------|
| `analyze` | `(ref_midi, attempt_midi, meta) -> AnalysisResult` | End-to-end pipeline |

```python
@dataclass
class AnalysisResult:
    ref_notes: list[NoteEvent]
    attempt_notes: list[NoteEvent]
    events: list[AnalysisEvent]
    metrics: dict
    match_rate: float       # matched / ref_notes
    quality_tier: str       # "full" | "simplified" | "too_low"
```

**Quality gate:**

| match_rate | quality_tier | Behavior |
|------------|-------------|----------|
| >= 0.50 | `"full"` | Full diagnosis + LLM drill prescription |
| 0.20 – 0.50 | `"simplified"` | Top 3 problems only, suggest slow practice |
| < 0.20 | `"too_low"` | No diagnosis; prompt slow-playback / wait mode |

**Metrics:**

```python
metrics = {
    "timing": {
        "onset_error_ms_median": ...,
        "onset_error_ms_p90_abs": ...,
        "onset_error_ms_mean_abs": ...,
    },
    "duration": {
        "duration_ratio_median": ...,
        "duration_too_short_ratio": ...,
        "duration_too_long_ratio": ...,
    },
    "dynamics": {
        "left_mean_velocity": ...,
        "right_mean_velocity": ...,
        "velocity_imbalance": ...,   # abs(L - R) / max(L, R)
    },
}
```

### 4.7 Report (`report.py`)

| Function | Signature | Notes |
|----------|-----------|-------|
| `build_report` | `(result, meta, ref_path, attempt_path) -> dict` | Assemble full report dict |
| `save_report` | `(report, song_id) -> Path` | Validate schema + write to `reports/<timestamp>.json` |

**Top problems:** group events by measure, pick top 3–5 by severity + count.

### 4.8 LLM Provider (`llm_provider.py`)

```python
class LLMProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str, output_schema: dict | None = None) -> str:
        ...

    @abstractmethod
    async def stream(self, prompt: str, tools: list[dict] | None = None):
        ...

class ClaudeProvider(LLMProvider):
    def __init__(self, model: str = "claude-sonnet-4-5-20250929", api_key: str | None = None):
        ...
```

**Config** (`~/.xpiano/config.yaml`):

```yaml
llm:
  provider: claude
  model: claude-sonnet-4-5-20250929
  api_key_env: ANTHROPIC_API_KEY
  max_retries: 3
midi:
  default_input: null
  default_output: null
tolerance:
  match_tol_ms: 80
  timing_grades:
    great_ms: 25
    good_ms: 50
    rushed_dragged_ms: 100
  chord_window_ms: 50
```

API key: `os.environ[config.llm.api_key_env]`. Never hardcoded.

### 4.9 LLM Coach (`llm_coach.py`)

| Function | Signature | Notes |
|----------|-----------|-------|
| `build_coaching_prompt` | `(report) -> str` | System + user prompt with report data |
| `get_coaching` | `(report, provider) -> dict` | Call LLM, validate, retry up to 3x |
| `stream_coaching` | `(report, provider, playback_engine) -> None` | Streaming + interleaved tool_calls |

**Retry logic:**

```
attempt = 0
while attempt < max_retries:
    raw = provider.generate(prompt)
    parsed = json.loads(raw)
    errors = schemas.validate("llm_output", parsed)
    if not errors: return parsed
    prompt = build_correction_prompt(raw, errors)
    attempt += 1
return fallback_output(report)
```

**Fallback:** rule-based template from report.events — top 2 issues, generic BPM/drill suggestions.

**Streaming** (`stream_coaching`): build prompt with `playback_control` tool def → `provider.stream()` → for each event: `text_delta` → Rich render; `tool_use` → `playback_engine.play()` → return result to stream. MVP: blocking (wait for playback before continuing).

### 4.10 Playback Engine (`playback.py`)

| Function | Signature | Notes |
|----------|-----------|-------|
| `play` | `(source, song_id, segment_id, measures, bpm, highlight_pitches, delay_between) -> PlayResult` | Main entry |

**Modes:**

| Mode | Behavior |
|------|----------|
| `reference` | Play `reference.mid` (or slice) at given BPM |
| `attempt` | Play latest `attempts/*.mid` |
| `comparison` | attempt slice → pause `delay_between` sec → reference slice |

**Measure slicing:** `meta.json` BPM + time_signature → compute `start_sec` / `end_sec`.

**Highlight:** matching pitches get velocity +40 (cap 127).

**No-device:** return `status="no_device"` — never crash.

### 4.11 Wait Mode (`wait_mode.py`)

**Responsibilities:** real-time pitch-set matching per beat; no alignment engine needed.

| Function | Signature | Notes |
|----------|-----------|-------|
| `build_pitch_sequence` | `(notes: list[NoteEvent], meta) -> list[PitchSetStep]` | Group ref notes into ordered pitch-sets per beat |
| `run_wait_mode` | `(song_id, segment_id, port, bpm) -> WaitModeResult` | Main loop: display → listen → match → advance |

```python
@dataclass
class PitchSetStep:
    measure: int
    beat: float
    pitches: set[int]           # expected pitch set (e.g. {60, 64, 67} for C-E-G chord)
    pitch_names: list[str]      # display names

@dataclass
class WaitModeResult:
    total_steps: int
    completed: int
    errors: int                 # wrong pitches before correct input
```

**Algorithm:**
1. Load `reference_notes.json` → group into pitch-set steps by `(measure, beat)` using `chord_window_ms`.
2. Display current step: `"▶ M1 Beat1: C4"` (or `"▶ M2 Beat3: C4 E4 G4"` for chords).
3. Listen for MIDI note-on events on input port.
4. Collect incoming pitches within arpeggiation window.
5. If collected set matches expected set → display `✓`, advance to next step.
6. If wrong pitch → display `"✗ expected C4, got D4"`, wait for correct input.
7. Optional timeout: `2 * beat_duration` → auto-skip, count as miss.
8. Ctrl+C → stop, display summary.

### 4.12 CLI Layer (`cli.py`)

**Commands:**

| Command | Args | Behavior |
|---------|------|----------|
| `xpiano devices` | — | List MIDI I/O devices |
| `xpiano list` | — | Show songs, segments, latest attempt stats |
| `xpiano setup` | `--song --segment --bpm --time-sig --measures --count-in` | Create/update meta.json |
| `xpiano import` | `--file --song` | Import MIDI as reference |
| `xpiano record-ref` | `--song --segment [--until-enter]` | Record reference via MIDI |
| `xpiano record` | `--song --segment [--until-enter]` | Record → auto-analyze → display report (or slow-playback if too_low) |
| `xpiano report` | `--song --segment` | Show latest report |
| `xpiano playback` | `--song --segment --mode --bpm --measures --highlight` | Play MIDI (3 modes) |
| `xpiano practice` | `--file --output-port [--bpm --start-sec --end-sec]` | Play a MIDI file as deterministic "human-like" practice input |
| `xpiano wait` | `--song --segment [--bpm]` | Wait Mode: pitch-set matching practice |
| `xpiano compare` | `--song --segment --attempts` | Compare recent attempts (M4) |
| `xpiano history` | `--song --segment` | Show history trend (M4) |

**`record` flow:**

1. Load meta → compute duration.
2. `midi_io.record(...)` with count-in.
3. `reference.save_attempt(...)`.
4. `analysis.analyze(ref_midi, attempt_midi, meta)`.
5. `report.build_report(...)` + `report.save_report(...)`.
6. **Quality gate:**
   - `too_low` → display slow-playback + wait mode suggestion.
   - `simplified` → display top 3 problems, suggest slow practice.
   - `full` → `llm_coach.stream_coaching(...)`.
7. Display formatted report via `display.py`.

`--until-enter`: skip fixed duration; stop capture when user presses Enter.

### 4.13 Display (`display.py`)

| Function | Purpose |
|----------|---------|
| `render_report` | Format report + llm_output into styled terminal output |
| `render_low_match` | Quality-gate "too low" message with playback + wait command suggestions |
| `render_piano_roll_diff` | Per-measure grid: ref vs attempt; mark missing/extra/wrong_pitch |
| `render_streaming_text` | Rich Live display for LLM streaming tokens |
| `render_playback_indicator` | `"▶ [播放中...]"` during MIDI playback |
| `render_wait_step` | Current pitch-set step display for wait mode |

**Piano roll diff:**

```
═══ Measure 2 ═══
Beat:   1       2       3       4
Ref:  ── G4 ── ── A4 ── ── E4 ── ── F4 ──
You:  ── G4 ── ── A4 ── ── F4 ── ── F4 ──
                          ↑ wrong: played F4, expected E4
```

---

## 5. Schemas

### 5.1 meta.json

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "xpiano.meta.schema.json",
  "title": "XPiano Song Meta (song-level, contains segments[])",
  "type": "object",
  "required": ["song_id", "time_signature", "bpm", "segments", "tolerance"],
  "properties": {
    "song_id": { "type": "string", "minLength": 1 },
    "title": { "type": "string" },
    "composer": { "type": "string" },
    "time_signature": {
      "type": "object",
      "required": ["beats_per_measure", "beat_unit"],
      "properties": {
        "beats_per_measure": { "type": "integer", "minimum": 1, "maximum": 12 },
        "beat_unit": { "type": "integer", "enum": [1, 2, 4, 8, 16] }
      },
      "additionalProperties": false
    },
    "bpm": {
      "type": "number", "minimum": 20, "maximum": 240,
      "description": "Must match reference MIDI tempo."
    },
    "key_signature": { "type": "string" },
    "segments": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "required": ["segment_id", "start_measure", "end_measure"],
        "properties": {
          "segment_id": { "type": "string", "minLength": 1 },
          "label": { "type": "string" },
          "start_measure": { "type": "integer", "minimum": 1 },
          "end_measure": { "type": "integer", "minimum": 1 },
          "count_in_measures": { "type": "integer", "minimum": 0, "maximum": 4, "default": 1 }
        },
        "additionalProperties": false
      }
    },
    "hand_split": {
      "type": "object",
      "properties": {
        "split_pitch": { "type": "integer", "minimum": 0, "maximum": 127, "default": 60 }
      },
      "additionalProperties": false
    },
    "tolerance": {
      "type": "object",
      "required": ["match_tol_ms", "timing_grades"],
      "properties": {
        "match_tol_ms": { "type": "integer", "minimum": 20, "maximum": 300, "default": 80 },
        "timing_grades": {
          "type": "object",
          "required": ["great_ms", "good_ms", "rushed_dragged_ms"],
          "properties": {
            "great_ms": { "type": "integer", "minimum": 5, "maximum": 100, "default": 25 },
            "good_ms": { "type": "integer", "minimum": 10, "maximum": 150, "default": 50 },
            "rushed_dragged_ms": { "type": "integer", "minimum": 20, "maximum": 300, "default": 100 }
          },
          "additionalProperties": false
        },
        "chord_window_ms": { "type": "integer", "minimum": 10, "maximum": 200, "default": 50 },
        "duration_short_ratio": { "type": "number", "minimum": 0.1, "maximum": 1.0, "default": 0.6 },
        "duration_long_ratio": { "type": "number", "minimum": 1.0, "maximum": 5.0, "default": 1.5 }
      },
      "additionalProperties": false
    }
  },
  "additionalProperties": false
}
```

### 5.2 report.json

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "xpiano.report.schema.json",
  "title": "XPiano Analysis Report",
  "type": "object",
  "required": ["version", "song_id", "segment_id", "status", "inputs", "summary", "events", "metrics"],
  "properties": {
    "version": { "type": "string", "default": "0.1" },
    "song_id": { "type": "string" },
    "segment_id": { "type": "string" },
    "inputs": {
      "type": "object",
      "required": ["reference_mid", "attempt_mid", "meta"],
      "properties": {
        "reference_mid": { "type": "string" },
        "attempt_mid": { "type": "string" },
        "meta": { "type": "object" }
      },
      "additionalProperties": false
    },
    "status": {
      "type": "string",
      "enum": ["ok", "low_quality", "error"]
    },
    "summary": {
      "type": "object",
      "required": ["counts", "match_rate"],
      "properties": {
        "counts": {
          "type": "object",
          "required": ["ref_notes", "attempt_notes", "matched", "missing", "extra"],
          "properties": {
            "ref_notes": { "type": "integer", "minimum": 0 },
            "attempt_notes": { "type": "integer", "minimum": 0 },
            "matched": { "type": "integer", "minimum": 0 },
            "missing": { "type": "integer", "minimum": 0 },
            "extra": { "type": "integer", "minimum": 0 }
          },
          "additionalProperties": false
        },
        "match_rate": { "type": "number", "minimum": 0, "maximum": 1 },
        "top_problems": {
          "type": "array", "minItems": 0, "maxItems": 5,
          "items": { "type": "string" }
        }
      },
      "additionalProperties": false
    },
    "metrics": {
      "type": "object",
      "required": ["timing", "duration", "dynamics"],
      "properties": {
        "timing": {
          "type": "object",
          "properties": {
            "onset_error_ms_median": { "type": "number" },
            "onset_error_ms_p90_abs": { "type": "number" },
            "onset_error_ms_mean_abs": { "type": "number" }
          },
          "additionalProperties": false
        },
        "duration": {
          "type": "object",
          "properties": {
            "duration_ratio_median": { "type": "number" },
            "duration_too_short_ratio": { "type": "number", "minimum": 0, "maximum": 1 },
            "duration_too_long_ratio": { "type": "number", "minimum": 0, "maximum": 1 }
          },
          "additionalProperties": false
        },
        "dynamics": {
          "type": "object",
          "properties": {
            "left_mean_velocity": { "type": ["number", "null"] },
            "right_mean_velocity": { "type": ["number", "null"] },
            "velocity_imbalance": { "type": ["number", "null"] }
          },
          "additionalProperties": false
        }
      },
      "additionalProperties": false
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
            "enum": ["missing_note", "extra_note", "wrong_pitch", "timing_early", "timing_late", "duration_short", "duration_long"]
          },
          "measure": { "type": "integer", "minimum": 1 },
          "beat": { "type": "number", "minimum": 1 },
          "pitch": { "type": ["integer", "null"], "minimum": 0, "maximum": 127 },
          "pitch_name": { "type": "string", "minLength": 1 },
          "actual_pitch": { "type": ["integer", "null"], "minimum": 0, "maximum": 127 },
          "actual_pitch_name": { "type": ["string", "null"] },
          "hand": { "type": "string", "enum": ["L", "R", "U"] },
          "severity": { "type": "string", "enum": ["low", "med", "high"] },
          "evidence": { "type": ["string", "null"] },
          "time_ref_sec": { "type": ["number", "null"] },
          "time_attempt_sec": { "type": ["number", "null"] },
          "delta_ms": { "type": ["number", "null"] },
          "expected_duration_sec": { "type": ["number", "null"] },
          "actual_duration_sec": { "type": ["number", "null"] },
          "group_id": { "type": ["string", "null"] }
        },
        "additionalProperties": false
      }
    },
    "examples": {
      "type": "object",
      "properties": {
        "missing_first_10": { "type": "array", "items": { "type": "object" } },
        "extra_first_10": { "type": "array", "items": { "type": "object" } }
      },
      "additionalProperties": false
    }
  },
  "additionalProperties": false
}
```

### 5.3 llm_output.json

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "xpiano.llm_output.schema.json",
  "title": "XPiano LLM Coaching Output",
  "type": "object",
  "required": ["goal", "top_issues", "drills", "pass_conditions", "next_recording"],
  "properties": {
    "goal": { "type": "string", "minLength": 1 },
    "top_issues": {
      "type": "array", "minItems": 1, "maxItems": 3,
      "items": {
        "type": "object",
        "required": ["title", "why", "evidence"],
        "properties": {
          "title": { "type": "string" },
          "why": { "type": "string" },
          "evidence": { "type": "array", "items": { "type": "string" }, "minItems": 1 }
        },
        "additionalProperties": false
      }
    },
    "drills": {
      "type": "array", "minItems": 2, "maxItems": 4,
      "items": {
        "type": "object",
        "required": ["name", "minutes", "bpm", "how", "reps", "focus_measures"],
        "properties": {
          "name": { "type": "string" },
          "minutes": { "type": "number", "minimum": 1, "maximum": 20 },
          "bpm": { "type": "number", "minimum": 20, "maximum": 240 },
          "how": { "type": "array", "items": { "type": "string" }, "minItems": 2 },
          "reps": { "type": "string" },
          "focus_measures": { "type": "string" }
        },
        "additionalProperties": false
      }
    },
    "pass_conditions": {
      "type": "object",
      "required": ["before_speed_up", "speed_up_rule"],
      "properties": {
        "before_speed_up": { "type": "array", "items": { "type": "string" }, "minItems": 2 },
        "speed_up_rule": { "type": "string" }
      },
      "additionalProperties": false
    },
    "next_recording": {
      "type": "object",
      "required": ["what_to_record", "tips"],
      "properties": {
        "what_to_record": { "type": "string" },
        "tips": { "type": "array", "items": { "type": "string" }, "minItems": 2 }
      },
      "additionalProperties": false
    },
    "tool_calls": {
      "description": "Batch-mode fallback only. Streaming mode uses real-time tool_use blocks instead.",
      "type": "array",
      "items": {
        "type": "object",
        "required": ["position", "action"],
        "properties": {
          "position": {
            "type": "string",
            "enum": ["after_issue_1", "after_issue_2", "after_issue_3", "before_drill_1", "after_drill_1", "before_drill_2", "after_drill_2", "summary_end"]
          },
          "action": {
            "type": "object",
            "required": ["type", "source"],
            "properties": {
              "type": { "const": "playback" },
              "source": { "type": "string", "enum": ["reference", "attempt", "comparison"] },
              "measures": { "type": "object", "properties": { "start": { "type": "integer" }, "end": { "type": "integer" } } },
              "bpm": { "type": "number", "minimum": 20, "maximum": 240 },
              "highlight_pitches": { "type": "array", "items": { "type": "string" } },
              "delay_between_sec": { "type": "number", "default": 1.5 }
            },
            "additionalProperties": false
          }
        },
        "additionalProperties": false
      }
    }
  },
  "additionalProperties": false
}
```

---

## 6. Data Flow

### End-to-end pipeline (record → feedback)

```
User: xpiano record --song X --segment Y
          │
          ▼
   ┌─────────────┐     ┌──────────────┐
   │  midi_io     │────→│  reference    │  save attempt .mid
   │  .record()   │     │  .save_attempt│
   └──────┬──────┘     └──────────────┘
          │ MidiFile
          ▼
   ┌─────────────┐
   │  parser      │  MIDI → NoteEvent[]  (both ref + attempt)
   │  .midi_to_   │
   │   notes()    │
   └──────┬──────┘
          │ ref_notes, attempt_notes
          ▼
   ┌─────────────┐
   │  alignment   │  Aligner.align_offline() → AlignmentResult
   │  (DTWAligner)│  + chord pitch-set grouping
   └──────┬──────┘
          │ AlignmentResult
          ▼
   ┌─────────────┐
   │  events      │  generate_events() → AnalysisEvent[]
   │  + merge_    │  merge_wrong_pitch() post-processing
   │  wrong_pitch │
   └──────┬──────┘
          │ events + metrics
          ▼
   ┌─────────────┐
   │  report      │  build_report() + schema validate
   └──────┬──────┘
          │ report dict
          ▼
   ┌─── quality gate ───┐
   │  match_rate check   │
   └──┬───────┬────────┬┘
      │       │        │
   <0.20   0.20-0.50  >=0.50
      │       │        │
      ▼       ▼        ▼
  display   display   llm_coach
  .render_  .render_  .stream_coaching()
  _low_     _report   │
  _match()  (brief)   ▼
                    ┌─────────────┐
                    │ LLM Provider│  streaming + tool_use
                    │ .stream()   │
                    └──────┬──────┘
                           │ text_delta / tool_use events
                           ▼
                    ┌─────────────┐
                    │ display +   │  render text + trigger MIDI playback
                    │ playback    │
                    └─────────────┘
```

### Wait Mode pipeline (no alignment)

```
User: xpiano wait --song X --segment Y
          │
          ▼
   ┌──────────────────┐
   │  wait_mode        │
   │  .build_pitch_    │  reference_notes.json → PitchSetStep[]
   │   sequence()      │  (group by measure/beat using chord_window_ms)
   └──────┬───────────┘
          │
          ▼
   ┌──────────────────┐
   │  wait_mode        │  display step → listen MIDI → match pitch-set → advance
   │  .run_wait_mode() │  loop until segment end or Ctrl+C
   └──────────────────┘
```

### playback_control tool schema (for LLM function calling)

```json
{
  "name": "playback_control",
  "description": "Play a MIDI snippet to demonstrate a problem or comparison.",
  "parameters": {
    "type": "object",
    "required": ["source"],
    "properties": {
      "source": { "type": "string", "enum": ["reference", "attempt", "comparison"] },
      "measures": { "type": "object", "properties": { "start": { "type": "integer", "minimum": 1 }, "end": { "type": "integer", "minimum": 1 } } },
      "bpm": { "type": "number", "minimum": 20, "maximum": 240 },
      "highlight_pitches": { "type": "array", "items": { "type": "string" } },
      "delay_between_sec": { "type": "number", "default": 1.5 }
    }
  }
}
```

---

## 7. Implementation Order

### M0: Infrastructure (1–2 days)

**Deliverables:**
- `pyproject.toml` + `src/xpiano/` package structure
- `config.py` — load/create `~/.xpiano/config.yaml` with defaults
- `models.py` — `NoteEvent`, `MeasureBeat`, `AnalysisEvent`, `AlignmentResult`, `PlayResult` dataclasses
- `schemas.py` — embed 3 JSON schemas, `validate(schema_name, data) -> list[str]`
- `midi_io.py` — `list_devices()`, `record()` (fixed-length + count-in)
- `reference.py` — `import_reference()`, `save_meta()`, `load_meta()`, `list_songs()`
- `parser.py` — `midi_to_notes()` with hand split
- `measure_beat.py` — `time_to_measure_beat()`
- CLI stubs: `devices`, `setup`, `import`, `list`

**Gate:** `xpiano devices` lists ports; `xpiano import` stores MIDI + generates meta; `xpiano list` shows songs.

### M1: Analysis Engine (2–4 days)

**Deliverables:**
- `alignment.py` — `Aligner` ABC + `DTWAligner` with chord pitch-set grouping
- `events.py` — event generation + `merge_wrong_pitch()` post-processing
- `analysis.py` — orchestrator pipeline
- `report.py` — `build_report()`, `save_report()`, schema validation
- Tests with 2–3 real MIDI recordings

**Gate:** `report.json` passes schema; events have correct measure/beat/pitch_name; `wrong_pitch` events correctly merged; tiered timing severity works; match_rate reasonable.

### M2: LLM Coach + Provider (2–3 days)

**Deliverables:**
- `llm_provider.py` — `LLMProvider` ABC + `ClaudeProvider`
- `config.py` — LLM provider config section
- `llm_coach.py` — `build_coaching_prompt()`, `get_coaching()`, retry/fallback
- Schema validation on llm_output.json
- Tests with mocked LLM responses

**Gate:** given report.json → valid llm_output.json; retry works on malformed; fallback produces valid output.

### M3: CLI + Playback + Wait Mode + Display (3–4 days)

**Deliverables:**
- `playback.py` — 3 modes, measure slicing, highlight, no-device fallback
- `wait_mode.py` — pitch-set sequence builder + real-time matching loop
- `display.py` — Rich report, piano roll diff, streaming renderer, wait mode display
- `cli.py` — all commands: `record`, `record-ref`, `report`, `playback`, `wait`, `compare`
- `llm_coach.stream_coaching()` — streaming with interleaved tool_calls
- Quality gate logic in `record` command flow
- End-to-end test: record → analyze → LLM feedback with playback

**Gate (maps to AC1–AC8):**

| AC | Check |
|----|-------|
| AC1 | `xpiano record` captures MIDI (note on/off + velocity) |
| AC2 | report.json events have measure/beat + pitch_name |
| AC3 | CLI outputs "measure X beat Y missing E4" and "played F4, expected E4" (wrong_pitch) |
| AC4 | llm_output.json follows template; provider switchable via config |
| AC5 | match_rate <20% triggers slow-playback + wait mode suggestion |
| AC6 | `xpiano playback --mode reference/attempt/comparison --measures 2-3` works |
| AC7 | LLM streaming interleaves playback tool_calls |
| AC8 | CLI renders piano roll diff (with wrong_pitch markers) |
| — | `xpiano wait` correctly advances on pitch-set match |

---

## 8. Test Strategy

### Mock boundaries

| Boundary | Mock in tests |
|----------|---------------|
| MIDI hardware | Pre-recorded `.mid` files as fixtures |
| LLM API | Mock `LLMProvider.generate()` / `.stream()` with canned responses |
| MIDI output (playback) | Mock `midi_io.play_midi()`; verify args only |
| File system | `tmp_path` fixture; or mock `~/.xpiano` path |

### What to test

| Module | Key test cases |
|--------|---------------|
| `parser` | Known MIDI → expected NoteEvent list; hand split boundary (59 vs 60) |
| `measure_beat` | Beat 1 of measure 1; last beat; fractional; different time sigs |
| `alignment` | Identical → perfect; shifted → correct warp; chord grouping (3 notes same beat → pitch-set); `Aligner` ABC contract |
| `events` | Missing/extra detection; `wrong_pitch` merge (same beat missing+extra → wrong_pitch); tiered timing: 20ms=no event, 40ms=low, 70ms=med, 120ms=high; duration thresholds |
| `report` | Schema validation pass/fail; top_problems derivation |
| `llm_coach` | Valid response → valid output; invalid → retry; 3 failures → fallback |
| `schemas` | All 3 schemas validate good data; reject bad data |
| `playback` | Mode dispatch; measure slicing math; highlight velocity; no-device graceful |
| `wait_mode` | Pitch-set sequence from notes; single note match; chord match (order-independent); wrong pitch rejection; timeout skip |
| `cli` | Integration: record flow with mocked MIDI + LLM; quality gate routing; wait mode invocation |

### Fixture data

- `tests/fixtures/twinkle_ref.mid` — 4-bar reference (includes chords for pitch-set test)
- `tests/fixtures/twinkle_good.mid` — good attempt (~80% match)
- `tests/fixtures/twinkle_bad.mid` — poor attempt (~15% match)
- `tests/fixtures/twinkle_wrong_pitch.mid` — attempt with deliberate wrong pitches (for wrong_pitch merge test)
- `tests/fixtures/sample_report.json` — valid report
- `tests/fixtures/sample_llm_output.json` — valid coaching output

---

## Post-MVP Extension Points

| Extension | Hook point | Milestone |
|-----------|-----------|-----------|
| HMM alignment (Matchmaker) | New `MatchmakerHMMAligner` class implementing `Aligner` ABC | M5+ |
| Online score following | `Aligner.align_online()` + `OnlineAligner.feed()` stubs already defined | M5+ |
| ABC score parser (music21) | New `abc_parser.py`; feeds into same `NoteEvent[]` pipeline | M6 |
| LLM score generation | New CLI `xpiano generate`; uses `LLMProvider` | M6 |
| Interactive practice loop | Extends `llm_coach.py` with session state + history | M7 |
| Accompaniment generation | New CLI command; LLM outputs multi-variant ABC | M8 |
| Trend comparison (M4) | `report.py` loads previous reports; `display.py` renders delta | M4 |
| OpenAI / Ollama providers | New classes in `llm_provider.py` implementing `LLMProvider` ABC | Any |
| `hands_not_together` event | New event type in `events.py`; requires reliable hand tracking | Post-MVP |
