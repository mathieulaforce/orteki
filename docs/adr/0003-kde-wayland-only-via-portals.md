# KDE Plasma on Wayland only, using desktop portals instead of ydotool

orteki targets only KDE Plasma 6 on Wayland. Global shortcuts use the XDG GlobalShortcuts portal and simulated keystrokes (paste, select-all) use the RemoteDesktop portal (libei), instead of the commonly suggested `ydotool`, which needs a root-level daemon with `/dev/uinput` access. All desktop interaction sits behind one boundary so other desktops, or `ydotool` as a fallback, can be added later without touching the core.
