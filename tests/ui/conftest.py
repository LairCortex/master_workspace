"""Boot fixtures for the UI E2E layer (spec: ui-testing).

Full Application start on per-test temporary data:
- game DB — a real .db file in tmp_path (runs init_db/migrations as in production)
- games dir and LLM config file — redirected into tmp_path (monkeypatch seams:
  ``game_manager.get_games_dir`` and the ``CONFIG_FILE`` constant)
- LLM network — emulated by an ``httpx.MockTransport`` (no real requests)
- file/input modal dialogs — stubbed (offscreen must not block on modal loops)
"""
from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable

import httpx
import pytest
import pytest_asyncio
from PySide6.QtWidgets import QDialog, QFileDialog, QInputDialog, QMenu

from app.infrastructure.http import AppHttpClient
from app.main import Application

CANNED_LLM_CONTENT = "Сгенерированный текст из mock-LLM"
DEFAULT_WAIT_TIMEOUT_S = 10.0


# ── helpers ────────────────────────────────────────────────────────────────

def query_db(db_path: str | Path, sql: str, params: tuple = ()) -> list[tuple]:
    """Sync read from the game's SQLite file.

    Safe to call inside ``qtbot.waitUntil`` predicates (separate connection,
    so the async engine's own connection is never blocked).
    """
    conn = sqlite3.connect(str(db_path))
    try:
        return [tuple(row) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


class ModalControl:
    """Control over modal ``QDialog.exec()`` calls.

    Offscreen tests must never block on modal loops: every ``.exec()``
    auto-accepts after all registered hooks have been applied to the dialog.
    Hooks are per-modal (cleared after each exec), so tests register a hook,
    then trigger the modal action.
    """

    def __init__(self) -> None:
        self._hooks: list[Callable[[QDialog], None]] = []
        self.executed: list[QDialog] = []

    def on_exec(self, hook: Callable[[QDialog], None]) -> None:
        self._hooks.append(hook)

    def exec_result(self, dlg: QDialog):
        for hook in self._hooks:
            hook(dlg)
        self._hooks.clear()
        self.executed.append(dlg)
        return QDialog.DialogCode.Accepted


# ── fixtures ───────────────────────────────────────────────────────────────

class MenuControl:
    """Control over modal ``QMenu.exec()`` (context menus).

    The chooser registered via :meth:`choose` is applied to the menu before
    the (stubbed) ``exec()`` returns the selected action — or ``None``.
    """

    def __init__(self) -> None:
        self._chooser: Callable[[QMenu], Any] | None = None
        self.executed: list[QMenu] = []

    def choose(self, chooser: Callable[[QMenu], Any]) -> None:
        self._chooser = chooser

    def exec_result(self, menu: "QMenu", *args: Any) -> Any:
        self.executed.append(menu)
        action = self._chooser(menu) if self._chooser is not None else None
        self._chooser = None
        return action


@pytest.fixture
def tmp_games_dir(tmp_path, monkeypatch):
    """Games directory inside the test's tmp_path (monkeypatched seam)."""
    games_dir = tmp_path / "games"
    games_dir.mkdir()
    monkeypatch.setattr(
        "app.infrastructure.db.game_manager.get_games_dir",
        lambda: games_dir,
    )
    return games_dir


@pytest.fixture
def tmp_llm_config(tmp_path, monkeypatch):
    """LLM connection config file inside the test's tmp_path."""
    config_file = tmp_path / "llm_config.json"
    monkeypatch.setattr("app.infrastructure.llm.config.CONFIG_FILE", config_file)
    return config_file


@pytest_asyncio.fixture
async def llm_client():
    """AppHttpClient whose POST */chat/completions gets a canned 200 answer.

    One handler for connection check and generation — as in production.
    ``llm_client.requests`` logs every request for assertions.
    """
    requests_log: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_log.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": CANNED_LLM_CONTENT}}]},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    http = AppHttpClient(client=client)
    http.requests = requests_log  # dynamic test attribute
    yield http
    await client.aclose()


@pytest_asyncio.fixture
async def app(qapp, llm_client, tmp_games_dir, tmp_llm_config, tmp_path):
    """Fully started Application on a fresh temporary game DB.

    Deliberately outside ``tmp_games_dir`` (a sibling of it under ``tmp_path``)
    so the "current" test game does not show up in the launcher's list —
    tests that need it listed copy/create it into ``tmp_games_dir`` explicitly.

    Yields ``application, window``; teardown closes the window and shuts
    down the application.
    """
    # A dialog left open by a previous test stays an ACTIVE MODAL for the
    # whole process: window.close() does not close child QDialogs, and once
    # the new window activates, Qt re-arms the stale modal and silently
    # swallows every spontaneous event (QTest clicks included) aimed at the
    # new app. Old widgets helpers hid this by sending NON-spontaneous
    # events; the Q2.5a island probes use real synthetic input, so clear the
    # leak before booting — each test starts the way CI means it to.
    from PySide6.QtWidgets import QApplication as _QApp
    for leak in list(_QApp.topLevelWidgets()):
        if isinstance(leak, QDialog) and (leak.isVisible() or leak.isModal()):
            try:
                leak.done(QDialog.DialogCode.Rejected)
            except RuntimeError:
                pass  # C++ side already gone

    db_path = tmp_path / "game" / "game.db"
    db_path.parent.mkdir(parents=True)
    (db_path.parent / "images").mkdir()
    from app.infrastructure.ui_prefs.config import UiPrefsManager
    from app.presentation.theme import ThemeRuntime

    # Theme preference isolated into tmp_path: e2e runs must never read or
    # write the developer's real ~/.nri_manager/ui.json.
    theme = ThemeRuntime(prefs=UiPrefsManager(tmp_path / "ui.json"))
    application = Application(qapp, http=llm_client, theme=theme)
    window = await application.start(str(db_path))
    yield application, window
    window.close()
    # Drain the wiring's spawned session tasks before closing the session:
    # a dialog-open load task still in flight would otherwise race
    # ``session.close()`` mid-query (IllegalStateChangeError at teardown).
    # Tests that click into session-touching flows already wait when they
    # assert on the effect; this covers tasks nobody waited on.
    from tests.ui import helpers
    await helpers.wait_until_settled()
    await application.shutdown()


@pytest.fixture(autouse=True)
def file_dialogs(tmp_path, monkeypatch):
    """Stub QFileDialog pickers: paths are pre-defined by tests, no modals.

    ``file_dialogs["save"]`` / ``file_dialogs["open"]`` — paths to return.
    """
    state: dict[str, str | None] = {"save": None, "open": None}

    def fake_save(*args: Any, **kwargs: Any) -> tuple[str, str]:
        return (state["save"] or "", "")

    def fake_open(*args: Any, **kwargs: Any) -> tuple[str, str]:
        return (state["open"] or "", "")

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(fake_save))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(fake_open))
    return state


@pytest.fixture(autouse=True)
def modal_qdialog(monkeypatch) -> ModalControl:
    """Auto-accept modal QDialog.exec() (pickers, message boxes) in offscreen.

    A plain function (not a bound method) is patched onto the class: the
    descriptor protocol then rebinds ``self`` for each ``dlg.exec()`` call.
    """
    control = ModalControl()

    def fake_exec(self, *args, **kwargs):
        return control.exec_result(self)

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    return control


@pytest.fixture(autouse=True)
def message_boxes(monkeypatch) -> list[tuple[str, str, str]]:
    """Record-and-dismiss QMessageBox static conveniences.

    ``QMessageBox.information/warning/critical/question`` are C++ static
    methods that spin a real nested modal loop — that hangs offscreen. The
    stubs log the call ``(kind, title, text)`` so tests can assert on it and
    return the default/Ok button (``question`` returns its ``defaultButton``).
    """
    from PySide6.QtWidgets import QMessageBox

    boxes: list[tuple[str, str, str]] = []

    def _dismiss(kind: str, parent, title: str, text: str, *args, **kwargs):
        boxes.append((kind, title, text))
        return QMessageBox.StandardButton.Ok

    def _question(parent, title, text, buttons=None, defaultButton=None, *args, **kwargs):
        boxes.append(("question", title, text))
        return defaultButton if defaultButton is not None else QMessageBox.StandardButton.No

    def _information(parent, title, text, *args, **kwargs):
        return _dismiss("information", parent, title, text, *args, **kwargs)

    def _warning(parent, title, text, *args, **kwargs):
        return _dismiss("warning", parent, title, text, *args, **kwargs)

    def _critical(parent, title, text, *args, **kwargs):
        return _dismiss("critical", parent, title, text, *args, **kwargs)

    monkeypatch.setattr(QMessageBox, "information", staticmethod(_information))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(_warning))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(_critical))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(_question))
    return boxes


@pytest.fixture(autouse=True)
def menu_qmenu(monkeypatch) -> MenuControl:
    """Stub context-menu execution: the registered chooser picks the action.

    PySide6 does not dispatch C++ methods through Python class-attribute
    overrides, so the ``QMenu`` symbol of the single module that constructs
    menus (timeline_island, since the Q2.5a island port) is replaced with a
    Python subclass whose ``exec`` is stubbed.
    """
    control = MenuControl()
    import app.presentation.views.timeline_island as timeline_island_mod

    class _StubbedContextMenu(QMenu):
        def exec(self, *args, **kwargs):  # Qt API name
            return control.exec_result(self, *args)

    monkeypatch.setattr(timeline_island_mod, "QMenu", _StubbedContextMenu)
    return control


@pytest.fixture
def dialog_input(monkeypatch) -> dict[str, Any]:
    """Stub QInputDialog.getText; tests set ``dialog_input["answer"] = (text, ok)``."""
    state: dict[str, Any] = {"answer": ("", False)}

    def fake_get_text(*args: Any, **kwargs: Any) -> tuple[str, bool]:
        return state["answer"]

    monkeypatch.setattr(QInputDialog, "getText", staticmethod(fake_get_text))
    return state


@pytest.fixture
def dialog_item(monkeypatch) -> dict[str, Any]:
    """Stub QInputDialog.getItem; tests set ``dialog_item["answer"] = (text, ok)``."""
    state: dict[str, Any] = {"answer": ("", False)}

    def fake_get_item(*args: Any, **kwargs: Any) -> tuple[str, bool]:
        return state["answer"]

    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(fake_get_item))
    return state


@pytest.fixture
def wait_for(qtbot):
    """Deterministic async wait with a fixed timeout (coroutine: ``await wait_for(cond)``).

    Two pumps are required (the test loop is pytest-asyncio's, not qasync):
    - ``await asyncio.sleep(0)`` turns the asyncio loop so application tasks
      (DB writes, LLM requests scheduled from Qt signal handlers) progress;
    - ``qtbot.wait(1)`` turns the Qt event loop so Qt timers (e.g. search
      debounce) and posted events fire. A 1 ms tick keeps the pump cheap:
      every app await-hop must not be padded by a 10 ms Qt wait.
    """

    async def _wait(condition: Callable[[], bool], timeout_s: float = DEFAULT_WAIT_TIMEOUT_S) -> None:
        t0 = time.perf_counter()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        while not condition():
            if loop.time() >= deadline:
                raise TimeoutError(f"wait_for: condition not met within {timeout_s} s")
            await asyncio.sleep(0)
            qtbot.wait(1)
        _dt = time.perf_counter() - t0
        if _dt > 2.0:
            print(f"[PUMP] wait_for took {_dt:.2f}s", flush=True)

    return _wait
