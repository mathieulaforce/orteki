# Python 3.12 with PySide6

orteki is written in Python 3.12 (pinned with `uv`) with a PySide6 (Qt) UI. Python has the strongest local speech and LLM libraries (faster-whisper, llama-cpp-python), Qt is KDE's native toolkit (tray, LayerShellQt indicator), and agents write and test Python well. Electron + TypeScript (weaker in-process Whisper), Tauri/Rust (steeper curve, WebKitGTK issues on NVIDIA Wayland) and a Python daemon with a separate web UI (two languages) were rejected.
