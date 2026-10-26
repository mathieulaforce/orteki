"""The `orteki` command-line interface: a thin layer over the core."""

from typing import Annotated

import typer

from orteki import __version__

app = typer.Typer(name="orteki", no_args_is_help=True, add_completion=False)


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"orteki {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    _version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_print_version,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    """Offline dictation and rewrite with recipes."""
