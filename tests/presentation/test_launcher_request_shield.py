"""Live-audit 2026-10-13 finding 4: launcher requests under a nested dialog.

An accessibility press bypasses modality: while the «Новая игра» picker ran
its nested ``exec()`` loop, a synthetic press on a launcher row fired
``openRequested`` → ``gameSelected`` → the host closed INSIDE the nested loop
and the island release ran under the still-live QML handler —
«Object destroyed while one of its QML signal handlers is in progress» aborted
the process. A real mouse cannot reach the screen while the picker is up, so
every controller request answers as the no-op the modality already promises
while a foreign modal/popup is active. The launcher's OWN ``exec()`` modality
(the first-run frame is the active modal widget) is not a nesting — without
that exception the whole screen would go dead.
"""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog

import app.infrastructure.db.game_manager as game_manager
from app.infrastructure.ui_prefs.config import UiPrefsManager
from app.presentation.theme.compiler import tokens_file_path
from app.presentation.theme.runtime import ThemeRuntime
from app.presentation.views.game_launcher_dialog import GameLauncherContent

from tests.presentation.test_launcher_qml import FakeCatalog


@pytest.fixture
def content(qtbot, monkeypatch, tmp_path):
    """The launcher island+controller on a private catalog and a private runtime."""
    fake = FakeCatalog()
    for fn in (
        "list_games", "create_game", "delete_game",
        "import_game", "read_archive_meta",
    ):
        monkeypatch.setattr(game_manager, fn, getattr(fake, fn))
    tokens = tmp_path / "tokens.json"
    tokens.write_text(tokens_file_path().read_text(encoding="utf-8"), encoding="utf-8")
    runtime = ThemeRuntime(prefs=UiPrefsManager(tmp_path / "ui.json"), tokens_path=tokens)
    widget = GameLauncherContent(theme=runtime)
    qtbot.addWidget(widget)
    return widget


def _nest(monkeypatch, modal=None, popup=None) -> None:
    """Project a foreign modal/popup as the active one (the picker's effect)."""
    monkeypatch.setattr(QApplication, "activeModalWidget", lambda *a: modal)
    monkeypatch.setattr(QApplication, "activePopupWidget", lambda *a: popup)


def boom(*a, **k):  # any reach here means the request was NOT shielded
    raise AssertionError("controller handler ran under a nested dialog")


def test_open_under_foreign_modal_is_noop(content, monkeypatch):
    chosen: list[str] = []
    content.gameSelected.connect(chosen.append)
    _nest(monkeypatch, modal=QDialog())

    content._on_open_requested("/games/Погоня/game.db")
    assert chosen == []


def test_open_without_nesting_still_opens(content, monkeypatch):
    _nest(monkeypatch)
    chosen: list[str] = []
    content.gameSelected.connect(chosen.append)

    content._on_open_requested("/games/Погоня/game.db")
    assert chosen == ["/games/Погоня/game.db"]


def test_own_frame_modal_is_not_nesting(content, monkeypatch):
    # The first-run launcher is shown under its own exec(): its frame IS the
    # active modal widget, and every request must stay live.
    _nest(monkeypatch, modal=content.window())
    chosen: list[str] = []
    content.gameSelected.connect(chosen.append)

    content._on_open_requested("/games/Погоня/game.db")
    assert chosen == ["/games/Погоня/game.db"]


def test_active_popup_counts_as_nesting(content, monkeypatch):
    _nest(monkeypatch, popup=QDialog())
    chosen: list[str] = []
    content.gameSelected.connect(chosen.append)

    content._on_open_requested("/games/Погоня/game.db")
    assert chosen == []


def test_every_request_noops_under_modal(content, monkeypatch):
    _nest(monkeypatch, modal=QDialog())
    monkeypatch.setattr(content.vm, "create", boom)
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(boom))
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(boom))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(boom))
    toggles: list[bool] = []
    monkeypatch.setattr(content._theme, "toggle", lambda: toggles.append(True))

    content._on_create_requested("")
    content._on_import_requested("")
    # vm.games is empty: unshielded this would IndexError on vm.games[0].
    content._on_delete_requested(0)
    content._on_theme_toggle()
    assert toggles == []
