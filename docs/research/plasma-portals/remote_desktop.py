# /// script
# requires-python = ">=3.12"
# dependencies = ["jeepney>=0.9", "pywayland>=0.4.19"]
# ///
"""Simulated keystrokes (select-all, paste, copy) through the XDG RemoteDesktop portal.

Every command except `check` starts a RemoteDesktop session. The first time, Plasma shows an
approval dialog (keep "Allow restoring on future sessions" ticked). The session is requested with
persist_mode=2 and the restore token is kept in ~/.local/state/orteki-research/, so later runs
should start without a dialog.

    portal.py install-desktop-file              # once, so the portal sees our own app id
    remote_desktop.py check                     # no dialog: CreateSession + SelectDevices only
    remote_desktop.py keys ctrl+a               # after a 5 s countdown, press Ctrl+A
    remote_desktop.py paste --text "Hallo"      # save clipboard, set text, Ctrl+V, restore
    remote_desktop.py paste --select-all        # rewrite-style: Ctrl+A first, then paste
    remote_desktop.py detect-selection          # copy, see whether the clipboard changed
    remote_desktop.py portal-clipboard          # try the Clipboard portal instead of data-control

Options: --backend notify (NotifyKeyboardKeysym, default) or eis (ConnectToEIS + libei),
--delay SECONDS before sending keys, --keys to override the copy / paste combination.
Run each script with `uv run docs/research/plasma-portals/<script>`.
"""

from __future__ import annotations

import argparse
import sys
import time

import clipboard
from focused_app import focused_window
from portal import RESPONSES, STATE_DIR, Portal, PortalError

KEYSYMS = {  # X11 keysym values, see xkbcommon-keysyms.h
    "ctrl": ("Control_L", 0xFFE3),
    "shift": ("Shift_L", 0xFFE1),
    "alt": ("Alt_L", 0xFFE9),
    "insert": ("Insert", 0xFF63),
    "a": ("a", 0x61),
    "c": ("c", 0x63),
    "v": ("v", 0x76),
}
TERMINALS = {"org.kde.konsole", "konsole", "org.kde.yakuake", "kitty", "Alacritty", "foot"}
DEVICE_KEYBOARD = 1


class RemoteDesktop:
    def __init__(self, backend: str = "notify", *, with_clipboard: bool = False) -> None:
        self.portal = Portal()
        p = self.portal
        self.session = p.create_session("RemoteDesktop")
        if with_clipboard:
            # Must happen before Start (Clipboard portal spec); KDE then marks the session.
            p.call("Clipboard", "RequestClipboard", "oa{sv}", (self.session, {}))
        self.token_file = (
            STATE_DIR / f"remote-desktop{'-clipboard' if with_clipboard else ''}.token"
        )
        options = {"types": ("u", DEVICE_KEYBOARD), "persist_mode": ("u", 2)}
        token = self.token_file.read_text().strip() if self.token_file.exists() else ""
        if token:
            options["restore_token"] = ("s", token)
        code, _ = p.request("RemoteDesktop", "SelectDevices", "oa{sv}", (self.session,), options)
        if code != 0:
            raise PortalError(f"SelectDevices: {RESPONSES.get(code, code)}")

        t0 = time.monotonic()
        code, res = p.request("RemoteDesktop", "Start", "osa{sv}", (self.session, ""), {})
        took = time.monotonic() - t0
        print(
            f"Start: {RESPONSES.get(code, code)} after {took:.2f} s "
            f"(restore token sent: {bool(token)}; a dialog usually means > 1 s)"
        )
        if code != 0:
            raise PortalError("RemoteDesktop session not started")
        new_token = res.pop("restore_token", None)
        print(f"  results: {res}; new restore token: {'yes' if new_token else 'no'}")
        if new_token:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            self.token_file.write_text(new_token)

        self.backend = backend
        self.kbd = None
        if backend == "eis":
            import eis

            (fd,) = p.call("RemoteDesktop", "ConnectToEIS", "oa{sv}", (self.session, {}))
            self.kbd = eis.EisKeyboard(fd.to_raw_fd())
            print("  ConnectToEIS: got an EIS fd and a resumed keyboard device")

    def combo(self, spec: str, hold: float = 0.02) -> None:
        keys = [KEYSYMS[k] for k in spec.lower().split("+")]
        if self.kbd:
            self.kbd.combo([name for name, _ in keys], hold)
            return
        for _, sym in keys:
            self._key(sym, 1)
        time.sleep(hold)
        for _, sym in reversed(keys):
            self._key(sym, 0)

    def _key(self, keysym: int, state: int) -> None:
        self.portal.call(
            "RemoteDesktop", "NotifyKeyboardKeysym", "oa{sv}iu", (self.session, {}, keysym, state)
        )

    def close(self) -> None:
        self.portal.close_session(self.session)
        self.portal.close()


def countdown(seconds: float) -> dict:
    if seconds > 0:
        print(f"focus the target text field now; sending keys in {seconds:.0f} s ...", flush=True)
        time.sleep(seconds)
    win = focused_window()
    print(f"focused: {win.get('resourceClass')!r} ({win.get('caption')!r})")
    return win


def is_terminal(win: dict) -> bool:
    return bool({win.get("resourceClass"), win.get("desktopFileName")} & TERMINALS)


# --- commands -----------------------------------------------------------------------------
def cmd_check(_: argparse.Namespace) -> None:
    p = Portal()
    session = p.create_session("RemoteDesktop")
    print(f"CreateSession: {session}")
    p.call("Clipboard", "RequestClipboard", "oa{sv}", (session, {}))
    print("RequestClipboard: accepted (no reply payload)")
    code, _ = p.request(
        "RemoteDesktop",
        "SelectDevices",
        "oa{sv}",
        (session,),
        {"types": ("u", DEVICE_KEYBOARD), "persist_mode": ("u", 2)},
    )
    print(f"SelectDevices(keyboard, persist_mode=2): {RESPONSES.get(code, code)}")
    p.close_session(session)
    print("closed without Start (Start is the step that shows the dialog)")


def cmd_keys(args: argparse.Namespace) -> None:
    rd = RemoteDesktop(args.backend)
    try:
        countdown(args.delay)
        for spec in args.combos:
            rd.combo(spec)
            print(f"sent {spec}")
            time.sleep(0.1)
    finally:
        rd.close()


def cmd_paste(args: argparse.Namespace) -> None:
    rd = RemoteDesktop(args.backend)
    dc = clipboard.DataControl()
    try:
        win = countdown(args.delay)
        keys = args.keys or ("ctrl+shift+v" if is_terminal(win) else "ctrl+v")
        saved, skipped = dc.snapshot()
        print(f"saved clipboard: {clipboard.describe(saved)}; skipped: {skipped or 'none'}")
        if args.select_all:
            rd.combo("ctrl+a")
            print("sent ctrl+a")
        dc.set(clipboard.text_payload(args.text))
        t0 = time.monotonic()
        rd.combo(keys)
        print(f"sent {keys}")
        served = dc.pump_until(lambda: dc.sends, timeout=2.0)
        if served:
            print(
                f"target fetched the text after {(time.monotonic() - t0) * 1000:.0f} ms "
                f"as {dc.sends[0]!r}"
            )
            dc.pump_for(0.3)  # some apps ask for several types
        else:
            print("nobody fetched the clipboard within 2 s (paste did not happen?)")
        print(f"MIME types requested: {dc.sends}")
        dc.set(saved)
        print(f"restored {len(saved)} MIME types")
        if saved:
            dc.detach_and_serve()
            print("a detached child serves the restored clipboard until the next copy")
    finally:
        rd.close()


def cmd_detect_selection(args: argparse.Namespace) -> None:
    rd = RemoteDesktop(args.backend)
    dc = clipboard.DataControl()
    try:
        win = countdown(args.delay)
        keys = args.keys or ("ctrl+shift+c" if is_terminal(win) else "ctrl+c")
        saved, _ = dc.snapshot()
        before = dc.selection_serial
        t0 = time.monotonic()
        rd.combo(keys)
        changed = dc.pump_until(lambda: dc.selection_serial != before, timeout=args.wait)
        took = (time.monotonic() - t0) * 1000
        if not changed:
            print(
                f"sent {keys}: clipboard unchanged after {args.wait * 1000:.0f} ms -> NO selection"
            )
            return
        text = (dc.read("text/plain;charset=utf-8") or b"").decode(errors="replace")
        print(f"sent {keys}: clipboard changed after {took:.0f} ms -> selection present")
        print(f"  offered types: {dc.types()}")
        print(f"  selected text ({len(text)} chars): {text[:200]!r}")
        dc.set(saved)
        print(f"restored {len(saved)} MIME types")
        if saved:
            dc.detach_and_serve()
            print("a detached child serves the restored clipboard until the next copy")
    finally:
        rd.close()


def cmd_portal_clipboard(args: argparse.Namespace) -> None:
    rd = RemoteDesktop(args.backend, with_clipboard=True)
    p = rd.portal
    from jeepney import MatchRule

    rule = MatchRule(
        type="signal", interface="org.freedesktop.portal.Clipboard", member="SelectionOwnerChanged"
    )
    changes = p.subscribe(rule)
    try:
        for mime in ("text/plain;charset=utf-8", "text/plain"):
            try:
                (fd,) = p.call("Clipboard", "SelectionRead", "os", (rd.session, mime))
                with fd.to_file("rb") as f:
                    print(f"SelectionRead({mime!r}) right after Start: {f.read()[:80]!r}")
            except Exception as exc:
                print(f"SelectionRead({mime!r}) right after Start failed: {exc}")
        print(f"copy something within {args.wait:.0f} s to see SelectionOwnerChanged ...")
        msg = p.wait(changes, timeout=args.wait)
        if msg is None:
            print("no SelectionOwnerChanged signal")
            return
        from portal import vardict

        info = vardict(msg.body[1])
        print(f"SelectionOwnerChanged: {info}")
        if "text/plain;charset=utf-8" in info.get("mime_types", []):
            (fd,) = p.call(
                "Clipboard", "SelectionRead", "os", (rd.session, "text/plain;charset=utf-8")
            )
            with fd.to_file("rb") as f:
                print(f"SelectionRead after the change: {f.read()[:200]!r}")
    finally:
        rd.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--backend", choices=("notify", "eis"), default="notify")
    ap.add_argument("--delay", type=float, default=5.0)
    sub = ap.add_subparsers(required=True)
    sub.add_parser("check").set_defaults(func=cmd_check)
    k = sub.add_parser("keys")
    k.add_argument("combos", nargs="+", help="e.g. ctrl+a ctrl+v shift+insert")
    k.set_defaults(func=cmd_keys)
    pa = sub.add_parser("paste")
    pa.add_argument("--text", default="orteki: geplakt via de RemoteDesktop portal")
    pa.add_argument("--select-all", action="store_true")
    pa.add_argument("--keys", help="paste combo (default ctrl+v, ctrl+shift+v in terminals)")
    pa.set_defaults(func=cmd_paste)
    ds = sub.add_parser("detect-selection")
    ds.add_argument("--keys", help="copy combo (default ctrl+c, ctrl+shift+c in terminals)")
    ds.add_argument("--wait", type=float, default=0.5, help="seconds to wait for a change")
    ds.set_defaults(func=cmd_detect_selection)
    pc = sub.add_parser("portal-clipboard")
    pc.add_argument("--wait", type=float, default=15.0)
    pc.set_defaults(func=cmd_portal_clipboard)
    args = ap.parse_args()
    try:
        args.func(args)
    except PortalError as exc:
        sys.exit(f"error: {exc}")


if __name__ == "__main__":
    main()
