# XPiano

CLI-first piano practice coach for MIDI keyboard workflows.

## Prerequisites

- Python 3.10+
- `uv`
- A MIDI input device (and optional MIDI output device)

## Install

```bash
source .venv/bin/activate
uv pip install -e .
```

## Quickstart

1. List MIDI ports:

```bash
xpiano devices
```

2. Import a reference MIDI (creates song metadata):

```bash
xpiano import --file /path/to/reference.mid --song twinkle --segment verse1
```

3. (Optional) tune setup:

```bash
xpiano setup --song twinkle --segment verse1 --bpm 100 --time-sig 4/4 --measures 1-8 --count-in 1
```

4. Record + analyze:

```bash
xpiano record --song twinkle --segment verse1 --input-port "Your MIDI In" --output-port "Your MIDI Out"
```

5. Show latest report:

```bash
xpiano report --song twinkle --segment verse1
```

6. Run coaching (LLM):

```bash
export ANTHROPIC_API_KEY=your_key
xpiano coach --song twinkle --segment verse1 --stream
```

## Practice Commands

Playback modes:

```bash
xpiano playback --song twinkle --segment verse1 --mode reference
xpiano playback --song twinkle --segment verse1 --mode attempt
xpiano playback --song twinkle --segment verse1 --mode comparison --measures 2-4
```

Wait mode:

```bash
xpiano wait --song twinkle --segment verse1
```

History + compare attempts:

```bash
xpiano history --song twinkle --segment verse1 --attempts latest-5
xpiano compare --song twinkle --segment verse1 --attempts 2 --playback
```

## Help

Top-level help:

```bash
xpiano --help
```

Command help:

```bash
xpiano record --help
xpiano playback --help
```
