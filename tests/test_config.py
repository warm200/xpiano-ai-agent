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
