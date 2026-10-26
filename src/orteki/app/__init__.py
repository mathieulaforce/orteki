"""The orteki Qt app (tray, main window, indicator). Requires the `gui` extra."""

import sys


def main() -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("The orteki app needs the 'gui' extra: uv sync --extra gui", file=sys.stderr)
        return 1
    _ = QApplication(sys.argv)
    print("The orteki app has no UI yet.", file=sys.stderr)
    return 0
