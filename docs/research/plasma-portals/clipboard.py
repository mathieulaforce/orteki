# /// script
# requires-python = ">=3.12"
# dependencies = ["pywayland>=0.4.19"]
# ///
"""Clipboard save / set / restore through the Wayland ext-data-control-v1 protocol (pywayland).

    uv run docs/research/plasma-portals/clipboard.py types      # list the current MIME types
    uv run docs/research/plasma-portals/clipboard.py roundtrip  # save -> set test text -> restore

`roundtrip` replaces the clipboard for about a second, checks with `wl-paste` that other clients
see the test text, restores every saved MIME type byte for byte, checks again, then leaves a
detached child process serving the restored data (as `wl-copy` does) until someone copies.
The test text carries `x-kde-passwordManagerHint: secret`, so Klipper keeps it out of its history.

Unlike QClipboard on Wayland, data-control needs no focused window, and KWin offers it to every
client. Also imported by remote_desktop.py for the paste and selection-detection flows.
"""

from __future__ import annotations

import argparse
import errno
import os
import select
import subprocess
import sys
import time

from pywayland.client import Display
from pywayland.protocol.ext_data_control_v1 import ExtDataControlManagerV1
from pywayland.protocol.wayland import WlSeat

SECRET_HINT = {"x-kde-passwordManagerHint": b"secret"}
MAX_BYTES = 64 * 2**20


def text_payload(text: str, *, secret: bool = True) -> dict[str, bytes]:
    data = text.encode()
    payload = {"text/plain;charset=utf-8": data, "text/plain": data, "UTF8_STRING": data}
    return payload | (SECRET_HINT if secret else {})


class DataControl:
    def __init__(self) -> None:
        self.display = Display()
        self.display.connect()
        self.manager = None
        self.seat = None
        self.offer_types: dict[object, list[str]] = {}
        self.selection = None  # current ext_data_control_offer_v1 or None
        self.selection_serial = 0  # bumps on every selection event
        self.source = None
        self.source_data: dict[str, bytes] = {}
        self.source_cancelled = False
        self.sends: list[str] = []  # MIME types other clients asked our source for

        registry = self.display.get_registry()
        registry.dispatcher["global"] = self._on_global
        self.display.roundtrip()
        if self.manager is None or self.seat is None:
            raise RuntimeError("compositor offers no ext_data_control_manager_v1 / wl_seat")
        self.device = self.manager.get_data_device(self.seat)
        self.device.dispatcher["data_offer"] = self._on_data_offer
        self.device.dispatcher["selection"] = self._on_selection
        self.device.dispatcher["primary_selection"] = lambda _d, offer: None
        self.display.roundtrip()

    # --- events ---------------------------------------------------------------------------
    def _on_global(self, registry, name, interface, version) -> None:
        if interface == "ext_data_control_manager_v1":
            self.manager = registry.bind(name, ExtDataControlManagerV1, 1)
        elif interface == "wl_seat" and self.seat is None:
            self.seat = registry.bind(name, WlSeat, min(version, 5))

    def _on_data_offer(self, _device, offer) -> None:
        types: list[str] = []
        self.offer_types[offer] = types
        offer.dispatcher["offer"] = lambda _o, mime: mime in types or types.append(mime)

    def _on_selection(self, _device, offer) -> None:
        old = self.selection
        if old is not None and old is not offer:
            self.offer_types.pop(old, None)
            old.destroy()
        self.selection = offer
        self.selection_serial += 1

    def _on_send(self, _source, mime, fd) -> None:
        self.sends.append(mime)
        try:
            os.set_blocking(fd, True)
            os.write(fd, self.source_data.get(mime, b""))
        except OSError as exc:
            if exc.errno != errno.EPIPE:
                raise
        finally:
            os.close(fd)

    def _on_cancelled(self, source) -> None:
        if source is self.source:
            self.source_cancelled = True
        source.destroy()

    # --- loop -----------------------------------------------------------------------------
    def pump(self, timeout: float = 0.0) -> None:
        self.display.dispatch(block=False)
        self.display.flush()
        fd = self.display.get_fd()
        if select.select([fd], [], [], max(timeout, 0))[0]:
            self.display.read()
            self.display.dispatch(block=False)

    def pump_for(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while (left := end - time.monotonic()) > 0:
            self.pump(left)

    def pump_until(self, done, timeout: float) -> bool:
        end = time.monotonic() + timeout
        while not done():
            left = end - time.monotonic()
            if left <= 0:
                return False
            self.pump(min(left, 0.05))
        return True

    # --- API ------------------------------------------------------------------------------
    def types(self) -> list[str]:
        self.pump(0)
        return list(self.offer_types.get(self.selection, [])) if self.selection else []

    def read(self, mime: str, timeout: float = 1.0) -> bytes | None:
        """Read one MIME type from the current selection (None on timeout / too large)."""
        if self.selection is None:
            return None
        r, w = os.pipe()
        self.selection.receive(mime, w)
        self.display.flush()
        os.close(w)
        chunks, size, end = [], 0, time.monotonic() + timeout
        try:
            while True:
                left = end - time.monotonic()
                if left <= 0:
                    return None
                ready = select.select([r], [], [], min(left, 0.05))[0]
                self.pump(0)  # serve our own source if we are the owner
                if not ready:
                    continue
                chunk = os.read(r, 1 << 16)
                if not chunk:
                    return b"".join(chunks)
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_BYTES:
                    return None
        finally:
            os.close(r)

    def snapshot(self, timeout: float = 1.0) -> tuple[dict[str, bytes], list[str]]:
        """Save every offered MIME type. Returns (saved, skipped)."""
        saved, skipped = {}, []
        for mime in self.types():
            data = self.read(mime, timeout)
            if data is None:
                skipped.append(mime)
            else:
                saved[mime] = data
        return saved, skipped

    def set(self, data: dict[str, bytes]) -> None:
        """Own the clipboard with `data`. Keep pumping so other clients can read it."""
        source = self.manager.create_data_source()
        source.dispatcher["send"] = self._on_send
        source.dispatcher["cancelled"] = self._on_cancelled
        for mime in data:
            source.offer(mime)
        self.source, self.source_data, self.source_cancelled = source, dict(data), False
        self.sends.clear()
        self.device.set_selection(source if data else None)
        self.display.roundtrip()

    def serve_until_replaced(self, max_seconds: float | None = None) -> None:
        end = None if max_seconds is None else time.monotonic() + max_seconds
        while not self.source_cancelled and (end is None or time.monotonic() < end):
            self.pump(1.0)

    def detach_and_serve(self) -> None:
        """Fork: the child keeps serving the current source until another client copies."""
        if os.fork() > 0:
            return
        os.setsid()
        devnull = os.open(os.devnull, os.O_RDWR)
        for fd in (0, 1, 2):
            os.dup2(devnull, fd)
        try:
            self.serve_until_replaced(max_seconds=24 * 3600)
        finally:
            os._exit(0)


def wl_paste(dc: DataControl, mime: str) -> bytes:
    """Read the clipboard as another client would, while we keep serving our source."""
    with subprocess.Popen(
        ["wl-paste", "--no-newline", "--type", mime], stdout=subprocess.PIPE
    ) as p:
        dc.pump_until(lambda: p.poll() is not None, 3)
        if p.poll() is None:
            p.kill()
        return p.stdout.read()


def describe(saved: dict[str, bytes]) -> str:
    return ", ".join(f"{m} ({len(b)} B)" for m, b in saved.items()) or "(empty)"


def cmd_types(_: argparse.Namespace) -> None:
    dc = DataControl()
    print("\n".join(dc.types()) or "(clipboard empty)")


def cmd_roundtrip(args: argparse.Namespace) -> None:
    dc = DataControl()
    t0 = time.monotonic()
    saved, skipped = dc.snapshot()
    print(f"saved in {(time.monotonic() - t0) * 1000:.0f} ms: {describe(saved)}")
    if skipped:
        print(f"skipped (timeout or > {MAX_BYTES} B): {skipped}")

    dc.set(text_payload(args.text))
    seen = wl_paste(dc, "text/plain;charset=utf-8").decode(errors="replace")
    print(f"wl-paste sees test text: {seen == args.text} ({seen!r})")

    dc.set(saved)
    ok = True
    for mime, data in saved.items():
        got = wl_paste(dc, mime)
        same = got == data
        ok &= same
        if not same:
            print(f"  MISMATCH {mime}: {len(got)} B vs {len(data)} B")
    print(f"restored {len(saved)} MIME types, byte-identical via wl-paste: {ok}")
    if not saved:
        print("previous clipboard was empty; nothing left to serve")
    elif args.no_detach:
        print("serving restored clipboard in the foreground until another client copies (Ctrl+C)")
        dc.serve_until_replaced()
    else:
        dc.detach_and_serve()
        print("a detached child keeps serving the restored clipboard until the next copy")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(required=True)
    sub.add_parser("types").set_defaults(func=cmd_types)
    rt = sub.add_parser("roundtrip")
    rt.add_argument("--text", default="orteki research #4 clipboard test")
    rt.add_argument("--no-detach", action="store_true")
    rt.set_defaults(func=cmd_roundtrip)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
