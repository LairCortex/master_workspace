"""Settings loaders and mention wiring error paths: log instead of silent pass.

Characterization: a corrupted calendar value opens the app on the
«Стандартный» preset with one warning (C2, task 5.1 — replaces the deleted
``_load_month_settings`` fallback test), an LLM-settings DB failure never
propagates, and a failed mention search is logged.

PR-010 re-pin: the old pin recorded the STATIC ``QMessageBox.warning`` — the
very call that killed the live qasync loop behind a nested modal cycle
(«Event loop stopped before Future completed»). The trap below inverts the
mechanics: any exec-like modal show reached from ``app.main`` during the
startup contour is a red test, while the sanctioned modeless ``show()`` on
the shared loop is recorded. The deferred ``call_soon`` channel (the same
one the first-run wizard rides, W3/NRI-0015) is driven by one loop yield, so
the pin proves: the window opens FIRST, the warning lands exactly once on
the next loop pass, and its close leaves the process alive.
"""
import asyncio
import json
import logging
import sqlite3
from unittest.mock import AsyncMock, MagicMock

import pytest
from PySide6.QtWidgets import QDialog

from app.domain.game_calendar import DEFAULT_MONTH_NAMES, current_calendar
from app.main import Application
from app.presentation.utils.calendar_warnings import MONTH_WARNING_TITLE
from app.presentation.views.calendar_wizard import CalendarWizardDialog


@pytest.fixture(autouse=True)
def autoaccept_calendar_wizard(monkeypatch):
    """The ``fail.db`` games started here are freshly seeded, so the C4
    first-entry wizard opens modally inside ``start()``; offscreen must not
    block on a real modal loop (tests/ui conftest convention, local copy)."""
    monkeypatch.setattr(
        CalendarWizardDialog,
        "exec",
        lambda self, *args: QDialog.DialogCode.Rejected,
    )


def _make_corrupt_calendar_db(tmp_path, broken: str):
    """Minimal game DB whose only ``game_settings`` row is the damaged
    ``game_calendar`` value (the live repro shape of TC-CALS-013)."""
    db_path = tmp_path / "game" / "game.db"
    db_path.parent.mkdir(parents=True)
    (db_path.parent / "images").mkdir()
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE game_settings "
            "(key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '')"
        )
        conn.execute(
            "INSERT INTO game_settings (key, value) VALUES ('game_calendar', ?)",
            (broken,),
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


def _read_calendar_row(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            "SELECT value FROM game_settings WHERE key = 'game_calendar'"
        ).fetchone()[0]
    finally:
        conn.close()


class _FinishedSignalFake:
    """Stand-in for ``QDialog.finished``: records the connected handlers so
    the test can emit the «OK» close exactly like the real button does."""

    def __init__(self):
        self.handlers = []

    def connect(self, handler):
        self.handlers.append(handler)


def _install_modal_trap(monkeypatch):
    """Swap ``app.main.QMessageBox`` for a trap (PR-010): the static modal
    variants and any ``exec``/``exec_`` raise immediately — reintroducing a
    blocking show on the startup contour turns the test red at the exact
    call — while the allowed non-nesting ``show()`` only records the box."""

    def _blocking(name: str):
        def _hit(*args, **kwargs):
            raise AssertionError(
                f"PR-010: блокирующий показ «{name}» вернулся — вложенный цикл "
                "событий на qasync убивает старт (AGENTS: no application "
                "dialog enters a nested event loop)"
            )

        return _hit

    class TrapMessageBox:
        class Icon:
            Warning = "warning"

        class StandardButton:
            Ok = "ok"

        def __init__(self, parent=None):
            self.parent = parent
            self.icon = None
            self.title = None
            self.text = None
            self.buttons = None
            self.shown_via = None
            self.finished = _FinishedSignalFake()

        def setIcon(self, icon):
            self.icon = icon

        def setWindowTitle(self, title):
            self.title = title

        def setText(self, text):
            self.text = text

        def setStandardButtons(self, buttons):
            self.buttons = buttons

        def show(self):
            self.shown_via = "show"
            created.append(self)

        exec = _blocking("exec")
        exec_ = _blocking("exec_")
        warning = staticmethod(_blocking("QMessageBox.warning"))
        information = staticmethod(_blocking("QMessageBox.information"))
        critical = staticmethod(_blocking("QMessageBox.critical"))
        question = staticmethod(_blocking("QMessageBox.question"))

    created: list[TrapMessageBox] = []
    monkeypatch.setattr("app.main.QMessageBox", TrapMessageBox)
    return created


async def test_corrupted_calendar_setting_opens_on_preset_with_one_warning(
    qapp, tmp_path, monkeypatch, caplog
):
    """Task 5.1 (PR-010 re-pin): `start()` loads the calendar through the
    service; a damaged ``game_calendar`` value opens the game on the
    «Стандартный» preset, logs the details, leaves the row untouched, and
    shows exactly one Russian warning naming the cause — DEFERRED after the
    window is on screen, never through a nested modal loop (spec
    «Повреждённое значение календарь-ключа»)."""
    # A custom spec whose intercalary day points at a non-existent month —
    # exactly the «Битая кастомная спека» corruption the spec describes.
    broken = json.dumps(
        {
            "v": 1,
            "kind": "custom",
            "months": [{"name": "Светопрел", "length": 30}],
            "week_names": ["Буд", "Ведь"],
            "intercalary": [{"name": "Хмарь", "after_month": 9}],
        },
        ensure_ascii=False,
    )
    db_path = _make_corrupt_calendar_db(tmp_path, broken)
    boxes = _install_modal_trap(monkeypatch)

    application = Application(qapp)
    with caplog.at_level(
        logging.WARNING, logger="app.application.services.calendar_settings_service"
    ):
        window = await application.start(str(db_path))  # must not raise
    try:
        # The game opened fully, on the Gregorian preset...
        assert window.isVisible()
        assert dict(current_calendar().month_names) == dict(DEFAULT_MONTH_NAMES)
        # ...nothing was shown ON the startup contour (PR-010: the window
        # comes first, the warning rides the next loop pass)...
        assert boxes == []
        await asyncio.sleep(0)
        # ...where it lands exactly once, modeless, in Russian...
        assert len(boxes) == 1
        box = boxes[0]
        assert box.parent is window
        assert box.shown_via == "show"
        assert box.title == MONTH_WARNING_TITLE
        assert "«Стандартный»" in box.text
        assert "вставной день ссылается на несуществующий месяц" in box.text
        # ...while the machine-readable details went to the log.
        assert "intercalary_unknown_month" in caplog.text
        # The damaged row is left for the future C4 master (design D4).
        assert _read_calendar_row(db_path) == broken
    finally:
        window.close()
        await application.shutdown()
    # Task 5.2: closing the game returns the active calendar to the preset.
    assert dict(current_calendar().month_names) == dict(DEFAULT_MONTH_NAMES)


async def test_pr010_corrupt_calendar_warning_never_enters_nested_loop(
    qapp, tmp_path, monkeypatch
):
    """PR-010 regression pin in the live repro shape (``{"v": 2, "kind":
    "custom"}``): the trap turns any exec-like modal show red, yet start()
    returns a shown, live window on the preset; the single warning arrives
    on the ``call_soon`` channel after the window is up, and closing it via
    ``finished`` drops the live ref — the process survives (it used to die
    with «Event loop stopped before Future completed» inside start())."""
    db_path = _make_corrupt_calendar_db(
        tmp_path, json.dumps({"v": 2, "kind": "custom"})
    )
    boxes = _install_modal_trap(monkeypatch)

    application = Application(qapp)
    window = await application.start(str(db_path))  # the old code died here
    try:
        # Window first, fully working; the warning is still only scheduled.
        assert window.isVisible()
        assert dict(current_calendar().month_names) == dict(DEFAULT_MONTH_NAMES)
        assert boxes == []
        await asyncio.sleep(0)  # the deferred channel fires once...
        assert len(boxes) == 1
        await asyncio.sleep(0)  # ...and never a second time per open.
        assert len(boxes) == 1
        box = boxes[0]
        assert application._calendar_warning is box
        assert box.title == MONTH_WARNING_TITLE
        # corrupt_shape is a known code — the Russian reason, not silence.
        assert "«Стандартный»" in box.text
        assert "запись календаря имеет неверную структуру" in box.text
        # «OK» closes through the finished signal: the handler runs, the
        # live ref drops, and the loop has nothing to unwind — the app and
        # its window stay alive (the PR-010 death used to happen exactly
        # here, behind the button press).
        assert box.finished.handlers, "the box closed without a finished handler"
        for handler in box.finished.handlers:
            handler(0)  # QDialog.Accepted — what the «ОК» button emits
        assert application._calendar_warning is None
        assert window.isVisible()  # main window still alive and working
    finally:
        window.close()
        await application.shutdown()


async def test_load_llm_settings_failure_does_not_propagate(qapp, tmp_path, caplog):
    application = Application(qapp)
    await application.start(str(tmp_path / "fail.db"))
    try:
        application._session.execute = AsyncMock(side_effect=RuntimeError("boom"))
        with caplog.at_level(logging.WARNING, logger="app.main"):
            await application._load_llm_settings()  # must not raise
        assert "Failed to load LLM settings" in caplog.text
    finally:
        await application.shutdown()


async def test_mention_search_failure_is_logged(qapp, tmp_path, caplog, monkeypatch):
    application = Application(qapp)
    await application.start(str(tmp_path / "fail.db"))
    try:
        edit = MagicMock()
        connected = []
        edit.mention_search_requested.connect.side_effect = connected.append
        dialog = MagicMock()
        dialog.get_mention_edits.return_value = [edit]

        application._search_service.search_names = AsyncMock(
            side_effect=RuntimeError("boom")
        )
        application._wire_mentions_for_dialog(dialog, lambda t, i: None)
        assert len(connected) == 1
        with caplog.at_level(logging.ERROR, logger="app.main"):
            connected[0]("q")  # schedules the search coroutine
            await asyncio.sleep(0)  # let it run and hit the error
        assert "Mention search failed" in caplog.text
    finally:
        await application.shutdown()
