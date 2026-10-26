import re
import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from orteki import __version__
from orteki.cli import app

# The console script installed by `[project.scripts]`, next to the interpreter.
ORTEKI = Path(sys.executable).parent / "orteki"

# Typer forces coloured output on CI (e.g. GITHUB_ACTIONS); compare plain text.
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def plain(text: str) -> str:
    return ANSI_ESCAPE.sub("", text)


def run_orteki(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([ORTEKI, *args], capture_output=True, text=True, check=False)


def test_version_flag_prints_version() -> None:
    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output.strip() == f"orteki {__version__}"


def test_installed_command_prints_version() -> None:
    result = run_orteki("--version")

    assert result.returncode == 0
    assert result.stdout.strip() == f"orteki {__version__}"


def test_help_shows_usage() -> None:
    result = run_orteki("--help")

    assert result.returncode == 0
    assert "Usage: orteki" in plain(result.stdout)


def test_no_arguments_shows_usage_as_a_usage_error() -> None:
    result = run_orteki()

    assert result.returncode == 2
    assert "Usage: orteki" in plain(result.stdout + result.stderr)


def test_python_dash_m_runs_the_cli() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "orteki", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == f"orteki {__version__}"
