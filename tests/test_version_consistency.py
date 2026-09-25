"""NRI-0016 6.1 (AB7, spec app-version): one version source, one visible line.

The UI reads the number ONLY from ``app.__version__``; the package metadata
(``pyproject.toml``) is pinned equal to it here (design V7: the CHANGELOG
sync stays a release-procedure concern, not a test, because of its history
tail). The «О приложении» entry is a disabled display line showing the same
number — never active, never a literal, never parsed from the Changelog.
"""
from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path
from unittest.mock import MagicMock

from app import __version__

_REPO = Path(__file__).resolve().parent.parent


def _string_literals(source: str) -> list[str]:
    return [
        n.value
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]


_VERSION_LITERAL_STUB = re.compile(r"Версия\s*\d")


def test_pyproject_version_equals_app_dunder_version():
    data = tomllib.loads((_REPO / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["version"] == __version__


def test_about_menu_shows_the_disabled_version_line(qtbot):
    from PySide6.QtWidgets import QMenu

    from app.presentation.views.main_window import MainWindow

    w = MainWindow(
        timeline_vm=MagicMock(), detail_vm=MagicMock(), search_vm=MagicMock(),
    )
    qtbot.addWidget(w)
    action = w.version_action
    assert action.text() == f"Версия {__version__}"
    assert action.isEnabled() is False
    # The line sits in the «О приложении» menu and is shown always.
    about = next(
        m for m in w.menuBar().findChildren(QMenu)
        if m.menuAction().text() == "О приложении"
    )
    assert action in about.actions()


def test_version_line_is_not_a_hardcoded_literal():
    # Design V7: the menu interpolates app.__version__ and must not restate
    # it — bumping __version__ alone moves the caption.
    import inspect

    from app.presentation.views import main_window as mw

    source = inspect.getsource(mw)
    assert 'f"Версия {__version__}"' in source
    # No plain string restates a concrete number next to «Версия» (the
    # compile-time fragment of the f-string alone — «Версия » — is allowed).
    offending = [s for s in _string_literals(source) if _VERSION_LITERAL_STUB.search(s)]
    assert offending == []
