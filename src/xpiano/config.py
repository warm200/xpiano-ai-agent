from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

DEFAULT_CONFIG: dict[str, Any] = {
    "llm": {
        "provider": "claude",
        "model": "claude-sonnet-4-5-20250929",
        "api_key_env": "ANTHROPIC_API_KEY",
        "max_retries": 3,
    },
    "midi": {
        "default_input": None,
        "default_output": None,
    },
    "tolerance": {
        "match_tol_ms": 80,
        "timing_grades": {
            "great_ms": 25,
            "good_ms": 50,
            "rushed_dragged_ms": 100,
        },
        "chord_window_ms": 50,
        "duration_short_ratio": 0.6,
        "duration_long_ratio": 1.5,
    },
}


def xpiano_home(data_dir: str | Path | None = None) -> Path:
    if data_dir is not None:
        return Path(data_dir).expanduser()
    env_home = os.getenv("XPIANO_HOME")
    if env_home:
        return Path(env_home).expanduser()
    return Path.home() / ".xpiano"


def config_path(data_dir: str | Path | None = None) -> Path:
    return xpiano_home(data_dir) / "config.yaml"


def songs_path(data_dir: str | Path | None = None) -> Path:
    return xpiano_home(data_dir) / "songs"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def save_config(config: dict[str, Any], data_dir: str | Path | None = None) -> Path:
    home = xpiano_home(data_dir)
    home.mkdir(parents=True, exist_ok=True)
    path = config_path(home)
    with path.open("w", encoding="utf-8") as fp:
        yaml.safe_dump(config, fp, sort_keys=False, allow_unicode=False)
    songs_path(home).mkdir(parents=True, exist_ok=True)
    return path


def load_config(data_dir: str | Path | None = None) -> dict[str, Any]:
    path = config_path(data_dir)
    if not path.exists():
        save_config(copy.deepcopy(DEFAULT_CONFIG), data_dir=data_dir)
        return copy.deepcopy(DEFAULT_CONFIG)

    with path.open("r", encoding="utf-8") as fp:
        loaded = yaml.safe_load(fp) or {}
    if not isinstance(loaded, dict):
        loaded = {}
    merged = _deep_merge(DEFAULT_CONFIG, loaded)
    if merged != loaded:
        save_config(merged, data_dir=data_dir)
    songs_path(data_dir).mkdir(parents=True, exist_ok=True)
    return merged


def ensure_config(data_dir: str | Path | None = None) -> dict[str, Any]:
    return load_config(data_dir=data_dir)
