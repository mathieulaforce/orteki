"""Minimal libei sender over ctypes, for keystrokes through RemoteDesktop.ConnectToEIS.

Imported by remote_desktop.py (`--backend eis`). Uses the system libei.so.1 and libxkbcommon.so.0
(Fedora: libei, libxkbcommon). libei sends evdev keycodes, so a keysym such as `a` has to be
looked up in the keymap that the EIS server (KWin) hands out; on a Belgian AZERTY layout `a` is
KEY_Q (16), not KEY_A (30).
"""

from __future__ import annotations

import ctypes
import mmap
import os
import select
import time

ei = ctypes.CDLL("libei.so.1")
xkb = ctypes.CDLL("libxkbcommon.so.0")

P = ctypes.c_void_p
for name, res, argtypes in [
    ("ei_new_sender", P, [P]),
    ("ei_configure_name", None, [P, ctypes.c_char_p]),
    ("ei_setup_backend_fd", ctypes.c_int, [P, ctypes.c_int]),
    ("ei_get_fd", ctypes.c_int, [P]),
    ("ei_dispatch", None, [P]),
    ("ei_get_event", P, [P]),
    ("ei_event_get_type", ctypes.c_int, [P]),
    ("ei_event_get_seat", P, [P]),
    ("ei_event_get_device", P, [P]),
    ("ei_event_unref", P, [P]),
    ("ei_device_has_capability", ctypes.c_bool, [P, ctypes.c_int]),
    ("ei_device_get_name", ctypes.c_char_p, [P]),
    ("ei_device_keyboard_get_keymap", P, [P]),
    ("ei_keymap_get_fd", ctypes.c_int, [P]),
    ("ei_keymap_get_size", ctypes.c_size_t, [P]),
    ("ei_device_start_emulating", None, [P, ctypes.c_uint32]),
    ("ei_device_stop_emulating", None, [P]),
    ("ei_device_keyboard_key", None, [P, ctypes.c_uint32, ctypes.c_bool]),
    ("ei_device_frame", None, [P, ctypes.c_uint64]),
    ("ei_now", ctypes.c_uint64, [P]),
    ("ei_unref", P, [P]),
]:
    fn = getattr(ei, name)
    fn.restype, fn.argtypes = res, argtypes
ei.ei_seat_bind_capabilities.restype = None  # variadic, NULL-terminated

for name, res, argtypes in [
    ("xkb_context_new", P, [ctypes.c_int]),
    ("xkb_keymap_new_from_string", P, [P, ctypes.c_char_p, ctypes.c_int, ctypes.c_int]),
    ("xkb_keymap_min_keycode", ctypes.c_uint32, [P]),
    ("xkb_keymap_max_keycode", ctypes.c_uint32, [P]),
    (
        "xkb_keymap_key_get_syms_by_level",
        ctypes.c_int,
        [P, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(P)],
    ),
    ("xkb_keysym_from_name", ctypes.c_uint32, [ctypes.c_char_p, ctypes.c_int]),
]:
    fn = getattr(xkb, name)
    fn.restype, fn.argtypes = res, argtypes

EV_CONNECT, EV_DISCONNECT, EV_SEAT_ADDED = 1, 2, 3
EV_DEVICE_ADDED, EV_DEVICE_REMOVED, EV_DEVICE_PAUSED, EV_DEVICE_RESUMED = 5, 6, 7, 8
CAP_KEYBOARD = 1 << 2


class EisKeyboard:
    def __init__(self, fd: int, timeout: float = 3.0) -> None:
        self.ctx = ei.ei_new_sender(None)
        ei.ei_configure_name(self.ctx, b"orteki research")
        if ei.ei_setup_backend_fd(self.ctx, fd) != 0:
            raise RuntimeError("ei_setup_backend_fd failed")
        self.device = None
        self.resumed = False
        self.keymap: dict[int, int] = {}  # keysym -> evdev keycode (level 0 of layout 0)
        self.sequence = 0
        end = time.monotonic() + timeout
        while not (self.device and self.resumed):
            if time.monotonic() > end:
                raise RuntimeError("no resumed EIS keyboard device")
            self._dispatch(0.1)

    def _dispatch(self, timeout: float) -> None:
        select.select([ei.ei_get_fd(self.ctx)], [], [], timeout)
        ei.ei_dispatch(self.ctx)
        while ev := ei.ei_get_event(self.ctx):
            kind = ei.ei_event_get_type(ev)
            if kind == EV_SEAT_ADDED:
                ei.ei_seat_bind_capabilities(
                    P(ei.ei_event_get_seat(ev)), ctypes.c_int(CAP_KEYBOARD), P(None)
                )
            elif kind == EV_DEVICE_ADDED:
                dev = ei.ei_event_get_device(ev)
                if ei.ei_device_has_capability(dev, CAP_KEYBOARD):
                    self.device = dev
                    self._load_keymap(dev)
            elif kind == EV_DEVICE_RESUMED and ei.ei_event_get_device(ev) == self.device:
                self.resumed = True
            elif kind == EV_DEVICE_PAUSED and ei.ei_event_get_device(ev) == self.device:
                self.resumed = False
            elif kind == EV_DISCONNECT:
                raise RuntimeError("EIS server disconnected")
            ei.ei_event_unref(ev)

    def _load_keymap(self, dev) -> None:
        km = ei.ei_device_keyboard_get_keymap(dev)
        if not km:
            return
        size = ei.ei_keymap_get_size(km)
        with mmap.mmap(ei.ei_keymap_get_fd(km), size, prot=mmap.PROT_READ) as m:
            text = m.read(size).rstrip(b"\0")
        ctx = xkb.xkb_context_new(0)
        keymap = xkb.xkb_keymap_new_from_string(ctx, text, 1, 0)
        syms = P()
        for code in range(
            xkb.xkb_keymap_min_keycode(keymap), xkb.xkb_keymap_max_keycode(keymap) + 1
        ):
            n = xkb.xkb_keymap_key_get_syms_by_level(keymap, code, 0, 0, ctypes.byref(syms))
            if n > 0:
                sym = ctypes.cast(syms, ctypes.POINTER(ctypes.c_uint32))[0]
                self.keymap.setdefault(sym, code - 8)  # xkb keycode = evdev + 8

    def keycode(self, keysym_name: str) -> int:
        sym = xkb.xkb_keysym_from_name(keysym_name.encode(), 0)
        if sym not in self.keymap:
            raise KeyError(f"keysym {keysym_name!r} not on level 0 of the current layout")
        return self.keymap[sym]

    def combo(self, keysyms: list[str], hold: float = 0.02) -> None:
        codes = [self.keycode(k) for k in keysyms]
        self.sequence += 1
        ei.ei_device_start_emulating(self.device, self.sequence)
        for code in codes:
            ei.ei_device_keyboard_key(self.device, code, True)
            ei.ei_device_frame(self.device, ei.ei_now(self.ctx))
        time.sleep(hold)
        for code in reversed(codes):
            ei.ei_device_keyboard_key(self.device, code, False)
            ei.ei_device_frame(self.device, ei.ei_now(self.ctx))
        ei.ei_device_stop_emulating(self.device)
        self._dispatch(0)

    def close(self) -> None:
        ei.ei_unref(self.ctx)


def from_fd(fd: int) -> EisKeyboard:
    return EisKeyboard(os.dup(fd))
