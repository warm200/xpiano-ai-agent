#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def main() -> int:
    parser = argparse.ArgumentParser(description="Check XPiano report thresholds.")
    parser.add_argument("--report", required=True, help="Path to report JSON.")
    parser.add_argument("--quality", default="full", help="Required quality_tier value.")
    parser.add_argument("--match-rate-min", type=float, default=0.90)
    parser.add_argument("--timing-p90-max", type=float, default=120.0)
    parser.add_argument("--missing-max", type=int, default=2)
    parser.add_argument("--extra-max", type=int, default=2)
    args = parser.parse_args()

    report_path = Path(args.report)
    payload = json.loads(report_path.read_text(encoding="utf-8"))

    summary = payload.get("summary", {})
    counts = summary.get("counts", {})
    metrics = payload.get("metrics", {})
    timing = metrics.get("timing", {})

    match_rate = _to_float(summary.get("match_rate"))
    quality_tier = str(payload.get("quality_tier", "")).strip()
    status = str(payload.get("status", "")).strip()
    if not quality_tier:
        if status == "ok":
            quality_tier = "full"
        elif status == "low_quality":
            quality_tier = "simplified" if match_rate >= 0.20 else "too_low"
    timing_p90 = _to_float(timing.get("onset_error_ms_p90_abs"))
    missing = _to_int(counts.get("missing"))
    extra = _to_int(counts.get("extra"))

    print(
        "report metrics:",
        f"quality_tier={quality_tier or '(missing)'}",
        f"match_rate={match_rate:.4f}",
        f"timing_p90={timing_p90:.2f}",
        f"missing={missing}",
        f"extra={extra}",
    )

    failures: list[str] = []
    if quality_tier != args.quality:
        failures.append(
            f"quality_tier expected {args.quality}, got {quality_tier or '(missing)'}"
        )
    if match_rate < args.match_rate_min:
        failures.append(
            f"match_rate expected >= {args.match_rate_min:.4f}, got {match_rate:.4f}"
        )
    if timing_p90 > args.timing_p90_max:
        failures.append(
            f"timing_p90 expected <= {args.timing_p90_max:.2f}, got {timing_p90:.2f}"
        )
    if missing > args.missing_max:
        failures.append(
            f"missing expected <= {args.missing_max}, got {missing}"
        )
    if extra > args.extra_max:
        failures.append(
            f"extra expected <= {args.extra_max}, got {extra}"
        )

    if failures:
        print("threshold check failed:")
        for item in failures:
            print(f"- {item}")
        return 1

    print("threshold check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
