import subprocess
import sys

from typer.testing import CliRunner

from orteki import __version__
from orteki.cli import app


def test_version_flag_prints_version() -> None:
    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output.strip() == f"orteki {__version__}"


def test_installed_command_runs() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "orteki", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.startswith("orteki ")
