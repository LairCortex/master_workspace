"""MenuWindowRegistry contract (NRI-0014, design D1, spec qml-shell).

A repeated menu entry raises the live window instead of creating a second
one (defect AB4); closing is remembered (auto-``forget`` on ``finished``),
so the next open builds a fresh window — the char-sheet-list precedent,
generalized into one mechanism for every single-instance menu window.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog

from app.presentation.window_registry import MenuWindowRegistry


class _SpyDialog(QDialog):
    """Counts the raise/activate presses the registry performs on reuse."""

    def __init__(self) -> None:
        super().__init__()
        self.raise_calls = 0
        self.activate_calls = 0

    def raise_(self) -> None:
        self.raise_calls += 1
        super().raise_()

    def activateWindow(self) -> None:  # noqa: N802 — Qt API name
        self.activate_calls += 1
        super().activateWindow()


def test_second_open_reuses_live_window_without_calling_factory(qtbot):
    registry = MenuWindowRegistry()
    calls = []

    def factory():
        dlg = _SpyDialog()
        calls.append(dlg)
        return dlg

    first = registry.open("docs_readme", factory)
    qtbot.addWidget(first)
    assert len(calls) == 1
    assert first.isVisible()  # the registry shows the freshly created window

    second = registry.open("docs_readme", factory)

    assert len(calls) == 1  # no second object was built
    assert second is first
    assert first.raise_calls == 1 and first.activate_calls == 1

    registry.open("docs_readme", factory)
    assert first.raise_calls == 2 and first.activate_calls == 2


def test_close_forgets_and_next_open_creates_new_window(qtbot):
    registry = MenuWindowRegistry()
    calls = []

    def factory():
        dlg = QDialog()
        calls.append(dlg)
        return dlg

    first = registry.open("docs_changelog", factory)
    qtbot.addWidget(first)
    assert registry.get("docs_changelog") is first

    first.close()  # finished → auto-forget

    assert registry.get("docs_changelog") is None
    second = registry.open("docs_changelog", factory)
    qtbot.addWidget(second)
    assert len(calls) == 2
    assert second is not first


def test_delete_on_close_window_is_not_left_in_registry(qtbot):
    registry = MenuWindowRegistry()

    def factory():
        dlg = QDialog()
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        return dlg

    window = registry.open("launcher_switch", factory)
    assert registry.get("launcher_switch") is window

    window.close()
    qtbot.wait(0)  # process the deferred delete scheduled by WA_DeleteOnClose

    assert registry.get("launcher_switch") is None
    # And the next open is a healthy fresh window, not the deleted one.
    fresh = registry.open("launcher_switch", factory)
    qtbot.addWidget(fresh)
    assert fresh is not window


def test_two_keys_two_independent_windows(qtbot):
    """«Документация» and «Changelog» → distinct keys, each single-instance."""
    registry = MenuWindowRegistry()
    made: dict[str, QDialog] = {}

    def factory(name: str):
        def make():
            dlg = QDialog()
            made[name] = dlg
            return dlg

        return make

    readme = registry.open("docs_readme", factory("readme"))
    changelog = registry.open("docs_changelog", factory("changelog"))
    qtbot.addWidget(readme)
    qtbot.addWidget(changelog)

    assert set(made) == {"readme", "changelog"}
    assert readme is not changelog
    # Each key dedups on its own: re-opening the README reuses its window
    # and does not touch the changelog one.
    assert registry.open("docs_readme", factory("readme2")) is readme
    assert "readme2" not in made
    assert registry.get("docs_changelog") is changelog
