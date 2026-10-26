import builtins
import importlib.util
from collections.abc import Callable
from typing import Any

import pytest

from orteki.app import main

has_pyside6 = importlib.util.find_spec("PySide6") is not None


def fail_pyside6_import(monkeypatch: pytest.MonkeyPatch, error: Callable[[], ImportError]) -> None:
    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:  # pyright: ignore[reportExplicitAny, reportAny]
        if name.startswith("PySide6"):
            raise error()
        return real_import(name, *args, **kwargs)  # pyright: ignore[reportAny]

    monkeypatch.setattr(builtins, "__import__", fake_import)


def test_without_pyside6_explains_how_to_install_the_gui_extra(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fail_pyside6_import(monkeypatch, lambda: ModuleNotFoundError("No module", name="PySide6"))

    assert main() == 1
    assert "orteki[gui]" in capsys.readouterr().err


def test_broken_qt_install_raises_the_real_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fail_pyside6_import(monkeypatch, lambda: ImportError("libEGL.so.1: cannot open shared object"))

    with pytest.raises(ImportError, match=r"libEGL\.so\.1"):
        _ = main()


@pytest.mark.skipif(not has_pyside6, reason="needs the gui extra")
def test_app_starts_headless(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")

    assert main() == 0
