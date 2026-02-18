from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from xpiano.cli import app

runner = CliRunner()


def test_setup_and_list_command(xpiano_home: Path) -> None:
    result = runner.invoke(
        app,
        [
            "setup",
            "--song",
            "twinkle",
            "--segment",
            "verse1",
            "--bpm",
            "80",
            "--time-sig",
            "4/4",
            "--measures",
            "4",
        ],
    )
    assert result.exit_code == 0

    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "twinkle" in result.stdout
