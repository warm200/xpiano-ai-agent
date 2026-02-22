# XPiano E2E HIL Plan

## Goal

Automatically verify full system integrity with a real MIDI I/O loop:
`practice playback -> MIDI transport -> record -> analyze -> report`.

## Scope

- Keep existing unit/integration tests as deterministic CI lane.
- Add hardware-in-loop (HIL) lane for real transport + timing behavior.
- Use one reference MIDI and one or more "human-like" practice MID files.

## Why this lane

- Existing tests heavily mock I/O (good for logic correctness).
- Real regressions usually happen in port wiring, timing, note_on/off handling, and device fallback.
- HIL catches those issues before manual QA.

## Test Topology

- Input port: loopback input (IAC/loopMIDI/virtual port).
- Output port: loopback output.
- `xpiano record` listens on input.
- `xpiano practice --file <attempt.mid>` writes to output.
- Loopback routes output back into input to simulate a human performance.

## Command Additions

- New command: `xpiano practice --file <mid> [--output-port ...] [--bpm ...] [--start-sec ...] [--end-sec ...]`
- Purpose: deterministic "performer" driver for HIL tests.

## Gate Script Design

Script target: `scripts/e2e_hil_gate.sh`

1. Import reference:
`XPIANO_HOME=<tmp> xpiano import --file <reference.mid> --song <song> --segment <segment>`
2. Start record in background:
`XPIANO_HOME=<tmp> xpiano record --song <song> --segment <segment> --input-port <in> --output-port <out>`
3. Trigger practice playback:
`XPIANO_HOME=<tmp> xpiano practice --file <attempt.mid> --output-port <out>`
4. Wait for record completion.
5. Load latest report JSON and assert thresholds.
6. Emit concise pass/fail and error category.

## Initial Thresholds

- `quality_tier` must be `full`.
- `summary.match_rate >= 0.90` for good attempt fixture.
- `metrics.timing.onset_error_ms_p90_abs <= 120`.
- `summary.counts.extra <= 2`.
- `summary.counts.missing <= 2`.

## Enhancement Trigger Rules

- Low match + high extra: inspect duplicate/phantom events and input filtering.
- Good pitch but bad timing p90: inspect tempo scaling and delta tick conversion.
- High missing with stable timing: inspect note_off / sustain / chord-window behavior.
- `no_device`: improve device probing and CLI diagnostics.

## Rollout

1. Land `xpiano practice` command + tests.
2. Land HIL gate script with report threshold checks.
3. Add 2 fixture attempts:
`good.mid` (expected pass), `bad.mid` (expected fail mode).
4. Document local runbook for virtual loopback setup.
5. Optionally wire nightly CI on runner with MIDI loopback available.

## Current Status

- In progress.
- `xpiano practice` implementation started.
