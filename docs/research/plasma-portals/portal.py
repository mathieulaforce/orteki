# /// script
# requires-python = ">=3.12"
# dependencies = ["jeepney>=0.9"]
# ///
"""Shared XDG desktop portal helpers for the Plasma portal prototypes (jeepney, blocking I/O).

Also a small CLI:
    uv run docs/research/plasma-portals/portal.py info                  # versions, no dialogs
    uv run docs/research/plasma-portals/portal.py install-desktop-file  # needed for --app-id
    uv run docs/research/plasma-portals/portal.py remove-desktop-file

Why an app id: xdg-desktop-portal identifies an unsandboxed caller by its systemd unit. A script
started from Konsole runs in `app-org.kde.konsole-<n>.scope`, so without registering it would be
treated as Konsole: shortcuts and remote-desktop permissions would be stored under Konsole's name.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import secrets
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any

from jeepney import DBusAddress, MatchRule, MessageType, new_method_call
from jeepney.bus_messages import message_bus
from jeepney.io.blocking import DBusConnection, open_dbus_connection
from jeepney.wrappers import unwrap_msg

DEFAULT_APP_ID = "io.github.mathieulaforce.OrtekiResearch"
DESKTOP_FILE = Path.home() / ".local/share/applications" / f"{DEFAULT_APP_ID}.desktop"
# ORTEKI_RESEARCH_APP_ID="" skips registering (the portal then derives the id from the systemd unit)
APP_ID = os.environ.get("ORTEKI_RESEARCH_APP_ID", DEFAULT_APP_ID) or None
STATE_DIR = Path.home() / ".local/state/orteki-research"

DESKTOP = DBusAddress("/org/freedesktop/portal/desktop", bus_name="org.freedesktop.portal.Desktop")
IFACE = "org.freedesktop.portal."


def _end_of_type(sig: str, i: int) -> int:
    if sig[i] == "a":
        return _end_of_type(sig, i + 1)
    if sig[i] in "({":
        close = ")" if sig[i] == "(" else "}"
        i += 1
        while sig[i] != close:
            i = _end_of_type(sig, i)
        return i + 1
    return i + 1


def split_signature(sig: str) -> list[str]:
    out, i = [], 0
    while i < len(sig):
        j = _end_of_type(sig, i)
        out.append(sig[i:j])
        i = j
    return out


def decode(sig: str, value: Any) -> Any:
    """Turn jeepney values into plain Python, unwrapping (signature, value) variants."""
    if sig == "v":
        return decode(*value)
    if sig.startswith("a{"):
        _, vsig = split_signature(sig[2:-1])
        return {k: decode(vsig, v) for k, v in value.items()}
    if sig.startswith("a"):
        return [decode(sig[1:], v) for v in value]
    if sig.startswith("("):
        return tuple(decode(s, v) for s, v in zip(split_signature(sig[1:-1]), value, strict=True))
    return value


def unvariant(value: Any) -> Any:
    return decode("v", value)


def vardict(value: dict) -> dict:
    return decode("a{sv}", value)


class PortalError(RuntimeError):
    pass


class Portal:
    """One session-bus connection that talks to org.freedesktop.portal.Desktop."""

    def __init__(self, app_id: str | None = APP_ID) -> None:
        self.conn: DBusConnection = open_dbus_connection(bus="SESSION", enable_fds=True)
        self.sender = self.conn.unique_name.lstrip(":").replace(".", "_")
        self.stack = contextlib.ExitStack()
        self.app_id = app_id
        if app_id:
            self.register(app_id)

    def close(self) -> None:
        self.stack.close()
        self.conn.close()

    # --- plumbing -------------------------------------------------------------------------
    def call(
        self,
        interface: str,
        method: str,
        signature: str | None = None,
        body: tuple = (),
        addr: DBusAddress = DESKTOP,
        timeout: float | None = 30,
    ) -> tuple:
        iface = interface if "." in interface else IFACE + interface
        msg = new_method_call(addr.with_interface(iface), method, signature, body)
        reply = self.conn.send_and_get_reply(msg, timeout=timeout)
        return unwrap_msg(reply)

    def add_match(self, rule: MatchRule) -> None:
        self.conn.send_and_get_reply(message_bus.AddMatch(rule))

    def subscribe(self, rule: MatchRule, size: int = 256) -> deque:
        """Route matching messages into a queue for the lifetime of this Portal."""
        if rule.message_type != MessageType.method_call:
            self.add_match(rule)
        queue: deque = deque(maxlen=size)
        self.stack.enter_context(self.conn.filter(rule, queue=queue))
        return queue

    def wait(self, queue: deque, timeout: float | None):
        """Next message from queue, or None on timeout (other traffic is still dispatched)."""
        if queue:
            return queue.popleft()
        try:
            return self.conn.recv_until_filtered(queue, timeout=timeout)
        except TimeoutError:
            return None

    def pump(self, seconds: float) -> None:
        """Dispatch incoming D-Bus traffic for a while (fills subscribed queues)."""
        end = time.monotonic() + seconds
        while (left := end - time.monotonic()) > 0:
            with contextlib.suppress(TimeoutError):
                self.conn.recv_messages(timeout=left)

    def request(
        self, interface: str, method: str, signature: str, args: tuple, options: dict
    ) -> tuple[int, dict]:
        """Call a portal method that returns a Request handle and wait for its Response."""
        token = "orteki_" + secrets.token_hex(4)
        path = f"/org/freedesktop/portal/desktop/request/{self.sender}/{token}"
        rule = MatchRule(type="signal", interface=IFACE + "Request", member="Response", path=path)
        self.add_match(rule)
        queue: deque = deque(maxlen=4)
        with self.conn.filter(rule, queue=queue):
            opts = {"handle_token": ("s", token), **options}
            self.call(interface, method, signature, (*args, opts))
            msg = self.conn.recv_until_filtered(queue, timeout=None)  # dialogs can take a while
        self.conn.send_and_get_reply(message_bus.RemoveMatch(rule))
        code, results = msg.body
        return code, vardict(results)

    # --- portal specifics -----------------------------------------------------------------
    def register(self, app_id: str) -> None:
        """org.freedesktop.host.portal.Registry.Register: must precede every other portal call."""
        try:
            self.call("org.freedesktop.host.portal.Registry", "Register", "sa{sv}", (app_id, {}))
        except Exception as exc:
            hint = ""
            if not DESKTOP_FILE.exists() and app_id == DEFAULT_APP_ID:
                hint = (
                    "\n  -> run: uv run docs/research/plasma-portals/portal.py install-desktop-file"
                )
            raise PortalError(f"Registry.Register({app_id!r}) failed: {exc}{hint}") from exc

    def version(self, interface: str) -> int | None:
        try:
            (value,) = self.call(
                "org.freedesktop.DBus.Properties", "Get", "ss", (IFACE + interface, "version")
            )
            return unvariant(value)
        except Exception:
            return None

    def create_session(self, interface: str, options: dict | None = None) -> str:
        token = "orteki_" + secrets.token_hex(4)
        opts = {"session_handle_token": ("s", token), **(options or {})}
        code, results = self.request(interface, "CreateSession", "a{sv}", (), opts)
        if code != 0:
            raise PortalError(f"{interface}.CreateSession response {code}")
        return results["session_handle"]

    def close_session(self, session: str) -> None:
        addr = DBusAddress(session, bus_name=DESKTOP.bus_name)
        with contextlib.suppress(Exception):
            self.call(IFACE + "Session", "Close", None, (), addr=addr)


RESPONSES = {0: "success", 1: "cancelled by user", 2: "other error"}


# --- CLI ----------------------------------------------------------------------------------
def cmd_info(_: argparse.Namespace) -> None:
    p = Portal(app_id=None)
    try:
        for name in ("GlobalShortcuts", "RemoteDesktop", "Clipboard", "InputCapture", "ScreenCast"):
            print(f"{name:16} version {p.version(name)}")
        (types,) = p.call(
            "org.freedesktop.DBus.Properties",
            "Get",
            "ss",
            (IFACE + "RemoteDesktop", "AvailableDeviceTypes"),
        )
        print(
            f"RemoteDesktop AvailableDeviceTypes = {unvariant(types)}"
            " (1 keyboard, 2 pointer, 4 touch)"
        )
        (reg,) = p.call(
            "org.freedesktop.DBus.Properties",
            "Get",
            "ss",
            ("org.freedesktop.host.portal.Registry", "version"),
        )
        print(f"host Registry    version {unvariant(reg)}")
    finally:
        p.close()
    for app_id in ("org.example.DoesNotExist", "org.kde.konsole"):
        try:
            Portal(app_id=app_id).close()
            print(f"Register({app_id!r}): ok")
        except PortalError as exc:
            print(f"Register({app_id!r}): {exc}")
    print(f"research desktop file present: {DESKTOP_FILE.exists()} ({DESKTOP_FILE})")


def cmd_install(_: argparse.Namespace) -> None:
    DESKTOP_FILE.parent.mkdir(parents=True, exist_ok=True)
    DESKTOP_FILE.write_text(
        "[Desktop Entry]\nType=Application\nName=orteki research prototype\n"
        "Comment=Throwaway portal prototype for orteki issue #4\n"
        "Exec=false\nNoDisplay=true\nIcon=audio-input-microphone\n"
    )
    print(f"wrote {DESKTOP_FILE}")


def cmd_remove(_: argparse.Namespace) -> None:
    DESKTOP_FILE.unlink(missing_ok=True)
    print(f"removed {DESKTOP_FILE}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(required=True)
    sub.add_parser("info").set_defaults(func=cmd_info)
    sub.add_parser("install-desktop-file").set_defaults(func=cmd_install)
    sub.add_parser("remove-desktop-file").set_defaults(func=cmd_remove)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
