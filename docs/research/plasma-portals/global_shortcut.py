# /// script
# requires-python = ">=3.12"
# dependencies = ["jeepney>=0.9"]
# ///
"""Register global shortcuts through the XDG GlobalShortcuts portal and print press/release events.

    uv run docs/research/plasma-portals/portal.py install-desktop-file   # once
    uv run docs/research/plasma-portals/global_shortcut.py check         # no dialog
    uv run docs/research/plasma-portals/global_shortcut.py listen        # dialog on first run

`listen` binds two shortcuts (dictate: Ctrl+Alt+D, rewrite: Ctrl+Alt+R, both only preferred
triggers; Plasma's dialog lets you change them), then prints Activated / Deactivated for 60 s
with the hold time, to judge push-to-talk. Plasma stores the bindings in kglobalaccel under the
app id, so a second run should bind without a dialog. Remove them in System Settings > Shortcuts.
"""

from __future__ import annotations

import argparse
import time

from jeepney import MatchRule
from portal import IFACE, RESPONSES, Portal

SHORTCUTS = [
    (
        "dictate",
        {"description": ("s", "Dictate (hold to talk)"), "preferred_trigger": ("s", "CTRL+ALT+d")},
    ),
    (
        "rewrite",
        {"description": ("s", "Rewrite selection"), "preferred_trigger": ("s", "CTRL+ALT+r")},
    ),
]


def list_shortcuts(p: Portal, session: str) -> list:
    code, res = p.request("GlobalShortcuts", "ListShortcuts", "oa{sv}", (session,), {})
    return (
        res.get("shortcuts", []) if code == 0 else [f"ListShortcuts: {RESPONSES.get(code, code)}"]
    )


def cmd_check(_: argparse.Namespace) -> None:
    p = Portal()
    session = p.create_session("GlobalShortcuts")
    print(f"CreateSession: {session}")
    print(f"already bound for this app id: {list_shortcuts(p, session)}")
    p.close_session(session)


def cmd_listen(args: argparse.Namespace) -> None:
    p = Portal()
    session = p.create_session("GlobalShortcuts")
    print(f"already bound: {list_shortcuts(p, session)}")
    queues = {
        member: p.subscribe(
            MatchRule(type="signal", interface=IFACE + "GlobalShortcuts", member=member)
        )
        for member in ("Activated", "Deactivated")
    }
    t0 = time.monotonic()
    code, res = p.request(
        "GlobalShortcuts", "BindShortcuts", "oa(sa{sv})sa{sv}", (session, SHORTCUTS, ""), {}
    )
    print(f"BindShortcuts: {RESPONSES.get(code, code)} after {time.monotonic() - t0:.2f} s")
    for sid, info in res.get("shortcuts", []):
        print(f"  {sid}: {info.get('trigger_description')!r} ({info.get('description')})")
    print(f"press and hold the shortcuts; listening {args.seconds:.0f} s ...", flush=True)

    pressed: dict[str, int] = {}
    end = time.monotonic() + args.seconds
    while (left := end - time.monotonic()) > 0:
        p.pump(min(left, 0.2))
        for member, queue in queues.items():
            while queue:
                _, sid, ts, _opts = queue.popleft().body
                if member == "Activated":
                    pressed[sid] = ts
                    print(f"{time.strftime('%H:%M:%S')} pressed  {sid} (t={ts})")
                else:
                    held = ts - pressed.pop(sid, ts)
                    print(f"{time.strftime('%H:%M:%S')} released {sid} after {held} ms")
    p.close_session(session)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(required=True)
    sub.add_parser("check").set_defaults(func=cmd_check)
    li = sub.add_parser("listen")
    li.add_argument("--seconds", type=float, default=60)
    li.set_defaults(func=cmd_listen)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
