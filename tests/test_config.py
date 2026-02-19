from __future__ import annotations

from pathlib import Path

import yaml  # type: ignore[import-untyped]

from xpiano import config


def test_load_config_recovers_from_invalid_yaml(tmp_path: Path) -> None:
    cfg_path = config.config_path(data_dir=tmp_path)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text("llm: [bad", encoding="utf-8")

    loaded = config.load_config(data_dir=tmp_path)

    assert loaded["llm"]["provider"] == "claude"
    reparsed = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    assert isinstance(reparsed, dict)
    assert reparsed.get("llm", {}).get("provider") == "claude"


def test_load_config_recovers_from_non_mapping_yaml(tmp_path: Path) -> None:
    cfg_path = config.config_path(data_dir=tmp_path)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text("- invalid\n- shape\n", encoding="utf-8")

    loaded = config.load_config(data_dir=tmp_path)

    assert loaded["llm"]["provider"] == "claude"
    reparsed = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    assert isinstance(reparsed, dict)
    assert reparsed.get("llm", {}).get("provider") == "claude"


def test_load_config_recovers_from_invalid_utf8(tmp_path: Path) -> None:
    cfg_path = config.config_path(data_dir=tmp_path)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_bytes(b"\xff\xfe\x00\x00")

    loaded = config.load_config(data_dir=tmp_path)

    assert loaded["llm"]["provider"] == "claude"
    reparsed = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    assert isinstance(reparsed, dict)
    assert reparsed.get("llm", {}).get("provider") == "claude"


def test_load_config_ignores_non_mapping_override_for_default_mapping_key(
    tmp_path: Path,
) -> None:
    cfg_path = config.config_path(data_dir=tmp_path)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text("llm: []\ntolerance: bad\n", encoding="utf-8")

    loaded = config.load_config(data_dir=tmp_path)

    assert isinstance(loaded["llm"], dict)
    assert loaded["llm"]["provider"] == "claude"
    assert isinstance(loaded["tolerance"], dict)
    assert loaded["tolerance"]["match_tol_ms"] == 80
    reparsed = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    assert isinstance(reparsed, dict)
    assert isinstance(reparsed.get("llm"), dict)
    assert isinstance(reparsed.get("tolerance"), dict)


def test_load_config_ignores_non_mapping_nested_override_for_mapping_key(
    tmp_path: Path,
) -> None:
    cfg_path = config.config_path(data_dir=tmp_path)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        "tolerance:\n  timing_grades: []\n  match_tol_ms: 64\n",
        encoding="utf-8",
    )

    loaded = config.load_config(data_dir=tmp_path)

    assert loaded["tolerance"]["match_tol_ms"] == 64
    assert isinstance(loaded["tolerance"]["timing_grades"], dict)
    assert loaded["tolerance"]["timing_grades"]["great_ms"] == 25
    reparsed = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    assert isinstance(reparsed, dict)
    assert isinstance(reparsed.get("tolerance", {}).get("timing_grades"), dict)
