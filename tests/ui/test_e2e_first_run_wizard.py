"""E2E of the first-run wizard boot contour (NRI-0015 tasks 2.1/2.4, W3=FI-6).

Spec calendar-wizard «Первый запуск не вкладывает цикл событий», scenarios
«Запуск после показа окна» and «Применить на первом запуске видно».

Task 2.1 is the red line of the startup contour: the old path ran the first
wizard through ``await begin() + exec()`` INSIDE ``Application.start()`` — on
the live qasync loop that nested modal loop re-entered the running start task
(«Cannot enter into task») and the user of a failing «Применить» saw nothing
but a console traceback (FI-6). The target contour pinned here:

* ``Application.start()`` completes without ever running the wizard through
  ``exec()`` (the suite's ModalControl sees no wizard exec at all);
* the main window is the first thing on screen; the very wizard the menu entry
  builds (an own ApplicationModal top-level) then opens over it;
* cancel returns to that shown window, and the close-as-preset finish writes
  the «показан» flag exactly as the old boot close did;
* a failed application on the first run shows the same visible reason window
  the menu flow shows, the wizard stays alive and on the loop no
  «Cannot enter into task» arrives at the exception handler;
* a first-run wizard still open when the game closes is closed by
  ``shutdown()`` through its finish step — the flag survives the game, the
  live-audit FI-6 symptom («флаг не дописывается») never returns.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from PySide6.QtCore import Qt

from app.domain.game_calendar import StandardCalendar
from app.infrastructure.calendar_storage import encode_calendar
from app.infrastructure.repositories.game_settings_repository import (
    CALENDAR_SETTINGS_KEY,
    CALENDAR_WIZARD_SEEN_KEY,
)
from app.main import Application
from app.presentation.views.calendar_wizard import APPLY_ERROR_TITLE, CalendarWizardDialog

from tests.ui import helpers
from tests.ui.conftest import query_db


def _settings_rows(db_path: Path) -> dict[str, str]:
    return dict(query_db(db_path, "SELECT key, value FROM game_settings"))


def _new_game(tmp_path, name: str) -> Path:
    db_path = tmp_path / name / "game.db"
    db_path.parent.mkdir(parents=True)
    (db_path.parent / "images").mkdir()
    return db_path


async def _boot_first_run(application: Application, db_path: Path, wait_for):
    """start() over a freshly seeded game + the deferred wizard on screen."""
    window = await application.start(str(db_path))
    await wait_for(lambda: application._calendar_wizard is not None)
    await helpers.wait_until_settled()  # the draft read of begin() done
    return window, application._calendar_wizard


async def test_first_run_wizard_opens_after_start_and_cancel_returns(
    qapp, llm_client, tmp_llm_config, modal_qdialog, tmp_path, wait_for
):
    """Scenario «Запуск после показа окна»: start completes, window shown, the
    menu-shaped wizard opens over it, «Отменить» returns into the window."""
    problems: list[str] = []
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()
    # W3 was «Cannot enter into task» arriving HERE — collect, then assert empty.
    loop.set_exception_handler(lambda _l, ctx: problems.append(repr(ctx)))
    db_path = _new_game(tmp_path, "firstrun")
    try:
        application = Application(qapp, http=llm_client)
        execs_before = len(modal_qdialog.executed)
        window = await application.start(str(db_path))
        try:
            # start() finished — and never entered a modal exec for the wizard.
            assert not [
                d for d in modal_qdialog.executed[execs_before:]
                if isinstance(d, CalendarWizardDialog)
            ]
            # The window is the first thing the user gets; the wizard is not
            # even constructed while the startup coroutine is still in flight.
            assert window.isVisible()
            assert application._calendar_wizard is None

            # …then the deferred call opens the same wizard the menu builds.
            await wait_for(lambda: application._calendar_wizard is not None)
            wizard = application._calendar_wizard
            assert isinstance(wizard, CalendarWizardDialog)
            assert wizard.isVisible()
            # NRI-0014 D5/D6 shape carried over untouched (task 2.4): an own
            # application-modal top-level, parented to the window only.
            assert wizard.window() is wizard
            assert wizard.windowModality() == Qt.WindowModality.ApplicationModal
            assert wizard.parent() is window
            await helpers.wait_until_settled()
            assert wizard._stack.currentWidget() is wizard._pages["choice"]

            # Cancel returns to the shown window; the close-as-preset finish
            # writes the flag through the still-live session.
            wizard._cancel_button.click()
            assert not wizard.isVisible()
            assert window.isVisible()
            await helpers.wait_until_settled()
            rows = _settings_rows(db_path)
            assert rows[CALENDAR_WIZARD_SEEN_KEY] == "1"
            assert rows[CALENDAR_SETTINGS_KEY] == encode_calendar(StandardCalendar())
        finally:
            window.close()
            await application.shutdown()
    finally:
        loop.set_exception_handler(previous_handler)
    assert not [p for p in problems if "Cannot enter into task" in p]


async def test_first_run_apply_failure_shows_the_reason_window(
    qapp, llm_client, tmp_llm_config, tmp_path, wait_for, message_boxes,
    monkeypatch,
):
    """Scenario «Применить на первом запуске видно»: a promote error on the
    first run reaches the user through the same visible window the menu path
    shows — the wizard stays alive, the loop logs no nested-task conflict."""
    problems: list[str] = []
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _l, ctx: problems.append(repr(ctx)))
    db_path = _new_game(tmp_path, "applyfail")
    try:
        application = Application(qapp, http=llm_client)
        window, wizard = await _boot_first_run(application, db_path, wait_for)
        try:
            async def boom(*args, **kwargs):
                raise RuntimeError("диск отказал")

            monkeypatch.setattr(application._calendar_service, "promote_draft", boom)
            wizard._apply_button.click()  # «Стандартный» promotes right away
            await wizard.wait_idle()

            # Spec «Ошибки применения…»: the reason window is shown — not just
            # a console line — and the wizard keeps its state.
            assert ("warning", APPLY_ERROR_TITLE, "диск отказал") in message_boxes
            assert wizard.isVisible()
            assert application._calendar_wizard is wizard

            # Lift the pinned failure, then close the way the user would.
            monkeypatch.undo()
            wizard._cancel_button.click()
            await helpers.wait_until_settled()
        finally:
            window.close()
            await application.shutdown()
    finally:
        loop.set_exception_handler(previous_handler)
    assert not [p for p in problems if "Cannot enter into task" in p]


async def test_first_run_wizard_left_open_is_finished_by_shutdown(
    qapp, llm_client, tmp_llm_config, tmp_path, wait_for
):
    """Live-audit FI-6 tail: closing the game with the first-run wizard still
    open must still run the close step (close-as-preset + «показан») — the
    flag is written through the live session before it closes, the silent loss
    («флаг не дописывается») never returns."""
    db_path = _new_game(tmp_path, "leftopen")
    application = Application(qapp, http=llm_client)
    window, _wizard = await _boot_first_run(application, db_path, wait_for)

    window.close()
    await application.shutdown()

    assert application._calendar_wizard is None
    assert application._first_run_finish is None  # the finish task was awaited
    rows = _settings_rows(db_path)
    assert rows[CALENDAR_WIZARD_SEEN_KEY] == "1"
    assert rows[CALENDAR_SETTINGS_KEY] == encode_calendar(StandardCalendar())
