"""The orteki Qt app (tray, main window, indicator). Requires the `gui` extra."""

import sys

MISSING_GUI_EXTRA = """\
The orteki app needs the 'gui' extra. Install it with:
  uv tool install "orteki[gui] @ git+https://github.com/mathieulaforce/orteki"
or, in a development checkout:
  uv sync --extra gui"""


def main() -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ModuleNotFoundError as exc:
        # Only a missing PySide6 means the extra is absent; anything else (a broken
        # install, a missing system library) must surface as the real error.
        if exc.name != "PySide6":
            raise
        print(MISSING_GUI_EXTRA, file=sys.stderr)
        return 1
    _ = QApplication(sys.argv)
    print("The orteki app has no UI yet.", file=sys.stderr)
    return 0
