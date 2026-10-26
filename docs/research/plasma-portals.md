# Plasma 6 portals for shortcuts, paste and selection

Date: 2026-10-26. Issue #4. Versions checked on the dev machine: Plasma/KWin 6.7.4, xdg-desktop-portal 1.22.1, xdg-desktop-portal-kde 6.7.4, libei 1.6.0, Fedora 44, keyboard layout `be` (AZERTY).
Prototypes live in [`plasma-portals/`](plasma-portals/). They are throwaway scripts: pure-Python D-Bus (jeepney) and Wayland (pywayland), each runnable with `uv run`.

## Summary / recommendation

- **The desktop boundary is feasible on Plasma 6 with portals, plus two non-portal pieces.**
  - Global shortcuts: GlobalShortcuts portal (v2). One dialog on first bind; it gives press *and* release events, so push-to-talk works.
  - Keystrokes: RemoteDesktop portal (v2) with `persist_mode=2`. One dialog, then restore tokens.
  - Clipboard: Wayland **ext-data-control-v1** directly, not QClipboard and not the Clipboard portal.
  - Focused app: a **KWin script** loaded over D-Bus.
- **Send keys as keysyms, never as raw keycodes.** On this machine's Belgian AZERTY layout, evdev keycode 30 (`KEY_A`) types `q`. A naive "Ctrl+A" by keycode would send **Ctrl+Q** and quit the focused app. Two ways to do it right:
  - `NotifyKeyboardKeysym`: KWin maps the keysym to the right key.
  - libei: look the keysym up in the keymap that the EIS server sends.
- **Use `NotifyKeyboardKeysym` for the first version, and keep libei (`ConnectToEIS`) as an option behind the boundary.**
  - The keysym route is D-Bus only: no native library and no keymap handling.
  - libei needs `libei.so.1` and `libxkbcommon` through ctypes (no maintained Python binding on PyPI), plus a keysym → keycode lookup ([`eis.py`](plasma-portals/eis.py) shows it in about 150 lines).
  - ADR-0003 says "RemoteDesktop portal (libei)". Both routes are the RemoteDesktop portal, so the ADR wording may need a small amendment.
- **Use the clipboard via ext-data-control.**
  - It works without a focused window, which orteki never has: the indicator must not steal focus.
  - It sees every MIME type, can save and restore them byte for byte, and tells us exactly when the target app fetched the paste (`send` event). That lets orteki restore the clipboard *after* the paste instead of after a guessed delay.
  - Verified here.
- **App identity matters.**
  - Register with `org.freedesktop.host.portal.Registry.Register(app_id)` before any portal call. It needs an installed `<app_id>.desktop` file.
  - Without it, a process started from Konsole is identified as `org.kde.konsole`. Its shortcuts and remote-control permission would then be stored under Konsole's name (see Q1).
- **D-Bus library: jeepney (or dbus-fast later), not QtDBus.**
  - PySide6 cannot register custom D-Bus types from Python. The portal signatures `a(sa{sv})` (BindShortcuts) and `h` fds (ConnectToEIS, SelectionRead) are therefore painful in QtDBus (unverified in code; based on PySide6 not exposing `qDBusRegisterMetaType`).
  - ADR-0004 keeps Qt out of the core.
  - jeepney 0.9 is pure Python, has blocking and asyncio APIs, and supports fd passing.
  - Open question: integrating the loop with the Qt event loop.

## Q1. Global shortcut via the GlobalShortcuts portal

Status: **plumbing verified here (no dialog); bind + press events need the owner.**

- Plasma implements GlobalShortcuts **version 2** (introspected, and `version()` returns 2 in [globalshortcuts.cpp](https://invent.kde.org/plasma/xdg-desktop-portal-kde/-/blob/v6.7.4/src/globalshortcuts.cpp)). The KDE backend maps it onto kglobalaccel, which has the following consequences:
  - `BindShortcuts` shows a dialog only for **new** shortcut ids. Ids already known to kglobalaccel for this component are rebound silently. If the user rejects the dialog, the shortcuts are still registered with no key, "so we don't prompt on next application start" (source comment). **Bindings persist across restarts.**
  - The kglobalaccel component name is the **app id**. If the app id is empty it is `token_<session_handle_token>`, so an unregistered app must at least reuse a fixed `session_handle_token` (`componentName()` in [globalshortcuts.h](https://invent.kde.org/plasma/xdg-desktop-portal-kde/-/blob/v6.7.4/src/globalshortcuts.h)).
  - The portal emits both `Activated` and `Deactivated`, from kglobalaccel's `globalShortcutPressed` / `globalShortcutReleased`. The timestamps have millisecond granularity ([spec](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.GlobalShortcuts.html)). Hold-to-talk dictation is possible; the owner run measures it.
  - `preferred_trigger` uses the [shortcuts spec](https://specifications.freedesktop.org/shortcuts-spec/latest/) syntax, for example `CTRL+ALT+d`, parsed by `XdgShortcut::parse`. Users can change bindings in System Settings → Shortcuts. `ConfigureShortcuts` (v2) opens that page.
- **App id (important).**
  - For unsandboxed apps, xdg-desktop-portal takes the app id from the caller's systemd unit `app-<id>-<n>.scope`, and only if `<id>.desktop` exists ([xdp-app-info-host.c](https://github.com/flatpak/xdg-desktop-portal/blob/1.22.1/src/xdp-app-info-host.c)). On this machine, commands run from Konsole are in `app-org.kde.konsole-34783.scope` (checked with `/proc/self/cgroup`).
  - The fix is `org.freedesktop.host.portal.Registry.Register` (v1, present here), called before any other portal call ([spec XML](https://github.com/flatpak/xdg-desktop-portal/blob/1.22.1/data/org.freedesktop.host.portal.Registry.xml)).
  - Verified here: `Register('org.example.DoesNotExist')` fails with "App info not found", and `Register('org.kde.konsole')` succeeds. **orteki must install a `.desktop` file for its app id**, which a tray app wants anyway.
- Verified here (`global_shortcut.py check`, run without registering): `CreateSession` and `ListShortcuts` work with no dialog.

## Q2. Ctrl+A / Ctrl+V via RemoteDesktop, and persistence

Status: **session setup verified here up to `Start`; `Start` (dialog), the keystrokes and restore without a dialog need the owner.** Persistence was researched in source and is backed by a real persisted grant on this machine.

- Plasma implements RemoteDesktop **v2** (AvailableDeviceTypes = 7). v2 adds `persist_mode` / `restore_token` and `ConnectToEIS` ([spec](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.RemoteDesktop.html)).
- **Two input routes in the KDE backend** ([remotedesktop.cpp](https://invent.kde.org/plasma/xdg-desktop-portal-kde/-/blob/v6.7.4/src/remotedesktop.cpp)):
  - `NotifyKeyboardKeycode` / `NotifyKeyboardKeysym`: the portal process forwards them over KWin's privileged `org_kde_kwin_fake_input` protocol ([waylandintegration.cpp](https://invent.kde.org/plasma/xdg-desktop-portal-kde/-/blob/v6.7.4/src/waylandintegration.cpp)). For a keysym, KWin looks up the keycode in the **current layout** and sets the needed modifiers ([fakeinputbackend.cpp](https://invent.kde.org/plasma/kwin/-/blob/v6.7.4/src/backends/fakeinput/fakeinputbackend.cpp)).
  - `ConnectToEIS`: KWin's `org.kde.KWin.EIS.RemoteDesktop.connectToEIS` returns a libei socket ([eisbackend.cpp](https://invent.kde.org/plasma/kwin/-/blob/v6.7.4/src/plugins/eis/eisbackend.cpp)). The EIS keyboard device carries KWin's XKB keymap. libei sends **evdev keycodes** ([libei docs](https://libinput.pages.freedesktop.org/libei/)), so the client must map keysyms itself. After `ConnectToEIS`, the `Notify*` methods return errors (spec), so pick one route per session.
- **AZERTY trap, verified here with xkbcommon:**
  - On `us`: `a` → 30, `c` → 46, `v` → 47.
  - On `be`: `a` → **16**, `c` → 46, `v` → 47, and keycode 30 is `q`.
  - Ctrl+C and Ctrl+V happen to coincide on both layouts; Ctrl+A does not.
- **Persistence: yes, until revoked.**
  - `SelectDevices` takes `persist_mode` (0 none, 1 while running, 2 until revoked) and a single-use `restore_token`. `Start` returns a new token each time. The frontend stores the grant in the permission store, scoped to the app id ([xdp-session-persistence.c](https://github.com/flatpak/xdg-desktop-portal/blob/1.22.1/src/xdp-session-persistence.c)).
  - The KDE dialog has an "Allow restoring on future sessions" checkbox, ticked by default. A restore is accepted only if the requested **devices, screen sharing and clipboard flags match** the stored ones; otherwise the dialog is shown again.
  - KDE also has a "mega-authorization" table (`kde-authorized` / `remote-desktop`) that skips the dialog entirely for an app id. It is empty here.
  - Local evidence: the permission store's `remote-desktop` table already holds a persisted (mode-2) grant for `org.kde.kdeconnect.daemon`, so this path is used in practice on this machine.
- **Visible side effects:**
  - A restored start sends a "Remote control session started" notification (KNotification `remotedesktopstarted`).
  - While the session lives, the portal owns a "Remote Control" tray item (KStatusNotifierItem) with an "End" action. For keyboard-only sessions it is never set to Active (only `setStreams` does that), so it probably stays in the hidden tray section. Unverified: the owner should look.
  - Implication: orteki should keep **one long-lived session** rather than one per paste.
- Prototype: [`remote_desktop.py`](plasma-portals/remote_desktop.py), with `--backend notify|eis`. Verified here: `check` (CreateSession, RequestClipboard, SelectDevices with persist_mode=2) succeeds without a dialog.

## Q3. Clipboard save → paste → restore

Status: **save/set/restore verified here (text, 5 MIME types, byte-identical); the paste into a real app needs the owner.**

- **QClipboard is unsuitable on Wayland.**
  - Qt uses `wl_data_device`, whose selection is delivered "immediately before receiving keyboard focus and when a new selection is set while the client has keyboard focus" ([wayland.xml](https://gitlab.freedesktop.org/wayland/wayland/-/blob/main/protocol/wayland.xml)). Setting it needs an input serial.
  - orteki acts while another app is focused, so it would see a stale clipboard or none. The [Qt docs](https://doc.qt.io/qt-6/qclipboard.html) do not mention Wayland at all.
- **ext-data-control-v1** gives clipboard-manager access without focus ([protocol](https://gitlab.freedesktop.org/wayland/wayland-protocols/-/blob/main/staging/ext-data-control/ext-data-control-v1.xml)).
  - The spec calls it "privileged", but KWin 6.7 exposes it to **every** client: it is not in KWin's restricted list ([wayland_server.cpp](https://invent.kde.org/plasma/kwin/-/blob/v6.7.4/src/wayland_server.cpp)), and `wayland-info` shows `ext_data_control_manager_v1` v1 here.
  - `zwlr_data_control` is not offered.
  - pywayland 0.4.19 ships bindings for it, and wl-clipboard 2.2.1 uses it too.
- **Verified here** with `clipboard.py roundtrip`:
  - Saved 5 MIME types in 4 ms and set the test text; `wl-paste` saw it.
  - Restored all 5 types; `wl-paste` returned them byte-identical, and the sha256 of the text was unchanged before and after.
  - The test text was offered with `x-kde-passwordManagerHint: secret`, which Klipper skips ([historymodel.cpp](https://invent.kde.org/plasma/plasma-workspace/-/blob/v6.7.4/klipper/historymodel.cpp)). It did not appear in Klipper's history.
- **Restoring means owning the clipboard.** On Wayland, data is served by its owner, so orteki keeps serving the restored bytes until someone copies again. Fine for a long-running app; the prototype forks a child for this, like `wl-copy`. If orteki exits, Klipper's default `NoEmptyClipboard=true` refills the clipboard from history, usually as text only.
- **Paste timing:** the source receives `send(mime, fd)` when the target fetches the data. `paste` restores only after that (plus 300 ms for apps that fetch several types), with a 2 s fallback.
- **Images and multiple MIME types:**
  - The snapshot copies every offered type as bytes, so images and rich text are kept while orteki serves them.
  - Caveats:
    - Memory: everything is held in RAM; the prototype caps each type at 64 MiB.
    - Lazy or huge formats: some apps (e.g. office suites) offer many formats and render them on demand. The snapshot reads them all, with a 1 s per-type timeout; skipped types are lost.
    - Each restore lands in Klipper history again, de-duplicated by content (see [historymodel.cpp](https://invent.kde.org/plasma/plasma-workspace/-/blob/v6.7.4/klipper/historymodel.cpp)). Klipper's `IgnoreImages` setting governs images.
  - The image round trip is **not yet run**; see the owner checks.
- **Clipboard portal** (v1, KDE backend also on data-control, [clipboard.cpp](https://invent.kde.org/plasma/xdg-desktop-portal-kde/-/blob/v6.7.4/src/clipboard.cpp)): usable, but weaker.
  - It needs a RemoteDesktop session with `RequestClipboard` before `Start`, and the restore token must match that.
  - `SelectionOwnerChanged` fires only on *changes*, so the current MIME types are unknown right after start, and saving needs guessed types.
  - It adds a D-Bus hop per transfer.
  - Keep it as the fallback if KWin ever restricts data-control. `remote_desktop.py portal-clipboard` lets the owner try it.

## Q4. Selection detection (copy, then see whether the clipboard changed)

Status: **researched; needs the owner run in a browser field, a Qt app and Konsole.**

- **Method** (`remote_desktop.py detect-selection`):
  1. Snapshot the clipboard and note the data-control selection serial.
  2. Send the copy combo.
  3. Wait up to 500 ms for a new `selection` event. If one arrives, a selection exists and its text *is* the rewrite input. If not, there is no selection.
  4. Restore the snapshot.
  - No sentinel is needed: any copy, even of identical text, creates a new offer.
- **Copy and paste keys by app** (from focused-app detection):
  - Konsole defines copy as Ctrl+Shift+C or Ctrl+Insert, and paste as Ctrl+Shift+V or Shift+Insert ([SessionController.cpp](https://invent.kde.org/utilities/konsole/-/blob/master/src/session/SessionController.cpp), master branch).
  - Its copy action is **disabled when nothing is selected**, so detection works there.
  - Ctrl+A in a shell means "beginning of line", so terminals are natural **excluded apps** for select-all.
- **Known false positives (unverified, from app behaviour):**
  - Some editors copy the current line when nothing is selected, for example VS Code's `editor.emptySelectionClipboard` (default on).
  - Klipper records every detected selection in its history, because the copy is made by the target app and orteki cannot add the secret hint to it.
- **Latency budget:** the wait timeout is the price of "no selection". Owner timings will tell whether 500 ms can shrink.

## Q5. Focused application name via KWin

Status: **verified here.**

- [`focused_app.py`](plasma-portals/focused_app.py) loads a temporary KWin script through `org.kde.kwin.Scripting.loadScript`, runs it, and unloads it.
  - The script reads `workspace.activeWindow` ([KWin scripting API](https://develop.kde.org/docs/plasma/kwin/api/)) and calls back with `callDBus` with `resourceClass`, `resourceName`, `desktopFileName`, `caption` and `pid`.
  - With `--watch`, it also reports `workspace.windowActivated`.
- Result here: `{"resourceClass": "google-chrome", "desktopFileName": "google-chrome", …}` the first time, and `org.kde.konsole` later. The first answer arrived in **2–13 ms**. No permission or dialog is involved.
- **Use `desktopFileName` as the stable key for excluded apps**, with `resourceClass` as the fallback.
- For the product, load one long-lived script that pushes focus changes, rather than one script per query.
- **Risks:**
  - It relies on KWin's unrestricted session-bus scripting API, which is not a stable public contract. The same technique powers [kdotool](https://github.com/jinliu/kdotool).
  - `org.kde.KWin.getWindowInfo(uuid)` exists, but there is no "active window" D-Bus method (introspected).

## Local machine

- Fedora 44, kernel 7.1.8. Packages: `plasmashell 6.7.4`, `kwin 6.7.4`, `xdg-desktop-portal-1.22.1`, `xdg-desktop-portal-kde-6.7.4`, `libei-1.6.0` (`libei.so.1`, `liboeffis.so.1`, `libeis.so.1`), `wl-clipboard 2.2.1^git20251124`, `qt6-qtbase-6.11.1`. Session: Wayland, `XDG_CURRENT_DESKTOP=KDE`.
- Portal interface versions (introspected): GlobalShortcuts 2, RemoteDesktop 2 (devices 7), Clipboard 1, InputCapture 2, ScreenCast 5, host Registry 1. `kde-portals.conf`: `default=kde`.
- Wayland globals include `ext_data_control_manager_v1` v1, `zwp_input_method_v1` and `zwlr_layer_shell_v1`. There is no `zwlr_data_control`.
- Not installed: `ydotool`, `wtype`, `kdotool`, `xkbcli`. Python bindings (jeepney, pywayland) come from PyPI through `uv run`. `snegg`, the libei Python binding, is not on PyPI.
- liboeffis performs the portal handshake itself but has no `persist_mode` or restore-token support (no mention in [liboeffis.c](https://gitlab.freedesktop.org/libinput/libei/-/blob/1.6.0/src/liboeffis.c)). Do the handshake ourselves and pass the fd to `ei_setup_backend_fd`.

## Owner checks (interactive)

Run these from the repo root on the Plasma session. Do not run them over SSH: the dialogs appear on the desktop.

```sh
uv run docs/research/plasma-portals/portal.py install-desktop-file   # app id io.github.mathieulaforce.OrtekiResearch
uv run docs/research/plasma-portals/portal.py info                   # sanity check, no dialog
```

| # | Command | What to do | Expect | Result |
|---|---|---|---|---|
| 1 | `uv run docs/research/plasma-portals/global_shortcut.py listen` | Approve the shortcut dialog, then press and hold Ctrl+Alt+D, then press Ctrl+Alt+R | `pressed dictate` / `released dictate after N ms` | |
| 2 | same command again | Nothing | `BindShortcuts: success` in well under 1 s, no dialog | |
| 3 | `uv run docs/research/plasma-portals/remote_desktop.py keys ctrl+a` | Approve the dialog (keep "Allow restoring" ticked), then click into a browser text field with text within 5 s | All text selected; `new restore token: yes` | |
| 4 | same command again | Nothing to approve | `restore token sent: True`, Start < 1 s, no dialog; was a notification or tray icon shown? | |
| 5 | `… remote_desktop.py paste --text "Hallo wereld"` | Copy something first, focus a browser field within 5 s | "Hallo wereld" pasted; `target fetched…`; then `wl-paste` prints your earlier copy | |
| 6 | `… remote_desktop.py paste --select-all` | Focus a Kate or KWrite document containing text | All text replaced by the test text; clipboard restored | |
| 7 | `… remote_desktop.py paste` | Focus Konsole at a prompt | Text inserted with Ctrl+Shift+V (chosen automatically) | |
| 8 | `… remote_desktop.py detect-selection` | Browser field: run once with text selected, once without | `selection present` + text / `NO selection` | |
| 9 | same command | Qt app (Kate or KWrite), with and without a selection | as above (does Kate copy the line when nothing is selected?) | |
| 10 | same command | Konsole, with and without a mouse selection | as above, using Ctrl+Shift+C | |
| 11 | `… remote_desktop.py --backend eis keys ctrl+a` | Focus a text field | Text selected through libei (`a` mapped to keycode 16 on AZERTY) | |
| 12 | Copy an image (e.g. Spectacle "Copy to clipboard"), then `uv run docs/research/plasma-portals/clipboard.py roundtrip` | Nothing | `image/png` saved and restored byte-identical; paste it in an app afterwards | |
| 13 | `… remote_desktop.py portal-clipboard` | Approve the new dialog (different flags), then copy text within 15 s | Does `SelectionRead` work right after Start? `SelectionOwnerChanged` with mime_types | |
| 14 | `uv run docs/research/plasma-portals/focused_app.py --watch 20` | Switch between apps | One line per focus change | |

`…` stands for `uv run docs/research/plasma-portals/`.

Clean up afterwards:
- Shortcuts: System Settings → Shortcuts, remove "orteki research prototype".
- Restore tokens: `rm -r ~/.local/state/orteki-research`.
- Desktop file: `portal.py remove-desktop-file`.
- The remote-desktop grant stays in the permission store. Remove it with `busctl --user call org.freedesktop.impl.portal.PermissionStore /org/freedesktop/impl/portal/PermissionStore org.freedesktop.impl.portal.PermissionStore DeletePermission sss remote-desktop <id> io.github.mathieulaforce.OrtekiResearch`, where `<id>` comes from `… List s remote-desktop`.

## Open questions

- Does a keyboard-only RemoteDesktop session show a tray icon or a notification on every orteki start (owner checks #4)? If it does, is that acceptable UX?
- How should the D-Bus and Wayland loops integrate with Qt: jeepney's asyncio API plus `QtAsyncio`/qasync, or a worker thread? A small spike is needed before building the boundary.
- Will KWin keep ext-data-control and the scripting D-Bus API open to unprivileged clients? Watch Plasma release notes. Fallbacks: the Clipboard portal, and `org.kde.KWin.getWindowInfo`.
- Rewrite with no selection: send Ctrl+A in non-excluded apps (the plan in CONTEXT.md), or ask? This depends on the false positives from checks #8–#10.
- ADR-0003 wording: "RemoteDesktop portal (libei)" versus the recommended `NotifyKeyboardKeysym`.

## Sources

- xdg-desktop-portal 1.22.1 spec XML: [GlobalShortcuts](https://github.com/flatpak/xdg-desktop-portal/blob/1.22.1/data/org.freedesktop.portal.GlobalShortcuts.xml), [RemoteDesktop](https://github.com/flatpak/xdg-desktop-portal/blob/1.22.1/data/org.freedesktop.portal.RemoteDesktop.xml), [Clipboard](https://github.com/flatpak/xdg-desktop-portal/blob/1.22.1/data/org.freedesktop.portal.Clipboard.xml), [host Registry](https://github.com/flatpak/xdg-desktop-portal/blob/1.22.1/data/org.freedesktop.host.portal.Registry.xml). Code: [xdp-app-info-host.c](https://github.com/flatpak/xdg-desktop-portal/blob/1.22.1/src/xdp-app-info-host.c), [registry.c](https://github.com/flatpak/xdg-desktop-portal/blob/1.22.1/src/registry.c), [xdp-session-persistence.c](https://github.com/flatpak/xdg-desktop-portal/blob/1.22.1/src/xdp-session-persistence.c). Rendered docs: [flatpak.github.io/xdg-desktop-portal](https://flatpak.github.io/xdg-desktop-portal/docs/).
- xdg-desktop-portal-kde v6.7.4: [remotedesktop.cpp](https://invent.kde.org/plasma/xdg-desktop-portal-kde/-/blob/v6.7.4/src/remotedesktop.cpp), [globalshortcuts.cpp](https://invent.kde.org/plasma/xdg-desktop-portal-kde/-/blob/v6.7.4/src/globalshortcuts.cpp), [clipboard.cpp](https://invent.kde.org/plasma/xdg-desktop-portal-kde/-/blob/v6.7.4/src/clipboard.cpp), [waylandintegration.cpp](https://invent.kde.org/plasma/xdg-desktop-portal-kde/-/blob/v6.7.4/src/waylandintegration.cpp), [RemoteDesktopDialog.qml](https://invent.kde.org/plasma/xdg-desktop-portal-kde/-/blob/v6.7.4/src/RemoteDesktopDialog.qml), [screencast.cpp](https://invent.kde.org/plasma/xdg-desktop-portal-kde/-/blob/v6.7.4/src/screencast.cpp).
- KWin v6.7.4: [wayland_server.cpp](https://invent.kde.org/plasma/kwin/-/blob/v6.7.4/src/wayland_server.cpp), [fakeinputbackend.cpp](https://invent.kde.org/plasma/kwin/-/blob/v6.7.4/src/backends/fakeinput/fakeinputbackend.cpp), [eisbackend.cpp](https://invent.kde.org/plasma/kwin/-/blob/v6.7.4/src/plugins/eis/eisbackend.cpp), [scripting.h](https://invent.kde.org/plasma/kwin/-/blob/v6.7.4/src/scripting/scripting.h), [workspace_wrapper.h](https://invent.kde.org/plasma/kwin/-/blob/v6.7.4/src/scripting/workspace_wrapper.h), [KWin scripting API](https://develop.kde.org/docs/plasma/kwin/api/).
- Klipper v6.7.4: [historymodel.cpp](https://invent.kde.org/plasma/plasma-workspace/-/blob/v6.7.4/klipper/historymodel.cpp), [klipper.kcfg](https://invent.kde.org/plasma/plasma-workspace/-/blob/v6.7.4/klipper/klipper.kcfg).
- Konsole: [SessionController.cpp](https://invent.kde.org/utilities/konsole/-/blob/master/src/session/SessionController.cpp).
- libei 1.6.0: [libei.h](https://gitlab.freedesktop.org/libinput/libei/-/blob/1.6.0/src/libei.h), [docs](https://libinput.pages.freedesktop.org/libei/).
- Wayland: [wayland.xml](https://gitlab.freedesktop.org/wayland/wayland/-/blob/main/protocol/wayland.xml), [ext-data-control-v1](https://gitlab.freedesktop.org/wayland/wayland-protocols/-/blob/main/staging/ext-data-control/ext-data-control-v1.xml). Qt: [QClipboard](https://doc.qt.io/qt-6/qclipboard.html).
- Libraries: [jeepney](https://pypi.org/project/jeepney/) 0.9.0, [pywayland](https://pypi.org/project/pywayland/) 0.4.19, [dbus-fast](https://pypi.org/project/dbus-fast/) 5.2.0, [kdotool](https://github.com/jinliu/kdotool).
