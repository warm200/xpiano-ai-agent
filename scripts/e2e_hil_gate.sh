#!/usr/bin/env bash
set -euo pipefail

if [ "${1:-}" = "" ] || [ "${2:-}" = "" ] || [ "${3:-}" = "" ] || [ "${4:-}" = "" ]; then
  cat <<'USAGE'
usage: scripts/e2e_hil_gate.sh <reference.mid> <practice.mid> <input_port> <output_port> [song] [segment]

example:
  scripts/e2e_hil_gate.sh \
    ./xpiano_capture_reference.mid \
    ./xpiano_capture_reference.mid \
    "IAC Driver Bus 1" \
    "IAC Driver Bus 1" \
    twinkle \
    verse1
USAGE
  exit 1
fi

REF_MID="$1"
PRACTICE_MID="$2"
INPUT_PORT="$3"
OUTPUT_PORT="$4"
SONG_ID="${5:-hil_song}"
SEGMENT_ID="${6:-default}"

MATCH_RATE_MIN="${MATCH_RATE_MIN:-0.90}"
TIMING_P90_MAX="${TIMING_P90_MAX:-120}"
MISSING_MAX="${MISSING_MAX:-2}"
EXTRA_MAX="${EXTRA_MAX:-2}"
QUALITY_TIER="${QUALITY_TIER:-full}"

if [ -z "${XPIANO_HOME:-}" ]; then
  export XPIANO_HOME
  XPIANO_HOME="$(mktemp -d /tmp/xpiano_hil_XXXXXX)"
fi

RUN_DIR="$XPIANO_HOME/runs"
mkdir -p "$RUN_DIR"
RECORD_LOG="$RUN_DIR/record.log"

echo "XPIANO_HOME=$XPIANO_HOME"
echo "import reference..."
xpiano import --file "$REF_MID" --song "$SONG_ID" --segment "$SEGMENT_ID"

echo "start record..."
xpiano record \
  --song "$SONG_ID" \
  --segment "$SEGMENT_ID" \
  --input-port "$INPUT_PORT" \
  --output-port "$OUTPUT_PORT" \
  >"$RECORD_LOG" 2>&1 &
RECORD_PID=$!

# Give record loop a short head start.
sleep 0.30

echo "trigger practice playback..."
xpiano practice --file "$PRACTICE_MID" --output-port "$OUTPUT_PORT"

echo "wait record completion..."
if ! wait "$RECORD_PID"; then
  echo "record command failed; log follows:"
  cat "$RECORD_LOG"
  exit 1
fi

REPORT_DIR="$XPIANO_HOME/songs/$SONG_ID/reports"
if [ ! -d "$REPORT_DIR" ]; then
  echo "no report directory generated: $REPORT_DIR"
  exit 1
fi
LATEST_REPORT="$(find "$REPORT_DIR" -maxdepth 1 -name '*.json' -type f | sort | tail -n 1)"
if [ -z "$LATEST_REPORT" ]; then
  echo "no report generated"
  exit 1
fi

echo "latest report: $LATEST_REPORT"
python3 scripts/check_report_thresholds.py \
  --report "$LATEST_REPORT" \
  --quality "$QUALITY_TIER" \
  --match-rate-min "$MATCH_RATE_MIN" \
  --timing-p90-max "$TIMING_P90_MAX" \
  --missing-max "$MISSING_MAX" \
  --extra-max "$EXTRA_MAX"

echo "e2e_hil_gate passed"
