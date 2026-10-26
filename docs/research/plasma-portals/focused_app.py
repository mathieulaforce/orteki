# /// script
# requires-python = ">=3.12"
# dependencies = ["jeepney>=0.9"]
# ///
"""Get the focused application from KWin by loading a tiny KWin script over D-Bus.

    uv run docs/research/plasma-portals/focused_app.py            # print the focused window once
    uv run docs/research/plasma-portals/focused_app.py --watch 20 # stream focus changes for 20 s

The script reads `workspace.activeWindow` and calls back into this process with `callDBus`
(the same trick kdotool uses). No portal and no permission dialog are involved.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import tempfile
import time
from collections import deque
from pathlib import Path

from jeepney import DBusAddress, MatchRule, new_method_call, new_method_return
from jeepney.io.blocking import open_dbus_connection
from jeepney.wrappers import unwrap_msg

KWIN = "org.kde.KWin"
PATH = "/orteki_research"
IFACE = "io.github.mathieulaforce.OrtekiResearch"

JS = """
function info(w) {
    if (!w) return {};
    return {resourceClass: w.resourceClass, resourceName: w.resourceName,
            desktopFileName: w.desktopFileName, caption: w.caption, pid: w.pid,
            internalId: w.internalId.toString()};
}
function report(w) {
    callDBus(%(service)s, %(path)s, %(iface)s, "focused", JSON.stringify(info(w)));
}
report(workspace.activeWindow);
if (%(watch)s) workspace.windowActivated.connect(report);
"""


def kwin_call(conn, path: str, iface: str, method: str, sig=None, body=()):
    addr = DBusAddress(path, bus_name=KWIN, interface=iface)
    return unwrap_msg(conn.send_and_get_reply(new_method_call(addr, method, sig, body), timeout=5))


def focus_events(watch: float | None = None):
    """Yield the focused window (as a dict) now, and on every focus change for `watch` seconds."""
    conn = open_dbus_connection(bus="SESSION")
    plugin = f"orteki_research_focus_{conn.unique_name.replace(':', '').replace('.', '_')}"
    js = JS % {
        "service": json.dumps(conn.unique_name),
        "path": json.dumps(PATH),
        "iface": json.dumps(IFACE),
        "watch": "true" if watch else "false",
    }
    calls: deque = deque()
    rule = MatchRule(type="method_call", path=PATH, interface=IFACE, member="focused")
    with (
        tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f,
        conn.filter(rule, queue=calls),
    ):
        f.write(js)
        f.flush()
        try:
            (script_id,) = kwin_call(
                conn, "/Scripting", "org.kde.kwin.Scripting", "loadScript", "ss", (f.name, plugin)
            )
            kwin_call(conn, f"/Scripting/Script{script_id}", "org.kde.kwin.Script", "run")
            deadline = time.monotonic() + (watch or 2)
            while (left := deadline - time.monotonic()) > 0:
                try:
                    msg = conn.recv_until_filtered(calls, timeout=left)
                except TimeoutError:
                    return
                conn.send_message(new_method_return(msg))
                yield json.loads(msg.body[0])
                if not watch:
                    return
        finally:
            with contextlib.suppress(Exception):
                kwin_call(
                    conn, "/Scripting", "org.kde.kwin.Scripting", "unloadScript", "s", (plugin,)
                )
            Path(f.name).unlink(missing_ok=True)
            conn.close()


def focused_window() -> dict:
    with contextlib.closing(focus_events()) as events:
        return next(events, {})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--watch", type=float, metavar="SECONDS", help="keep reporting focus changes")
    args = ap.parse_args()
    t0 = time.monotonic()
    seen = False
    for info in focus_events(args.watch):
        if not seen:
            print(f"first answer after {(time.monotonic() - t0) * 1000:.0f} ms")
            seen = True
        print(json.dumps(info, ensure_ascii=False))
    if not seen:
        print("no answer from the KWin script", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
