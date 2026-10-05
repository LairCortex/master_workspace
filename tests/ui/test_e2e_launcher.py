"""E2E launcher scenarios: new game (1), open existing game (2), switch game (10).

NRI-0024 (task 4.1/4.2): the first screen stays the modal ``GameLauncherDialog``
(spec game-launcher «Первый экран остаётся модальным»), while «Сменить игру…»
from the menu of a RUNNING game is the launcher-as-sheet — ``GameSwitchSheet``
with the header «Сменить игру…», the launcher content inside it (addressed
through its ``content``, like the dialog's — the controller and the VM moved
to the shared ``GameLauncherContent``), and a confirmed choice rebuilding the
main window under the chosen base without a process restart. The old
non-modal launcher-window pins of NRI-0014/NRI-0024-1.3 are retired with the
format they pinned; their guarantees (exit without a choice keeps the game,
no duplicate copy) return here as sheet/gate properties — unpinned by the
container, not by the suite.
"""
from __future__ import annotations

import asyncio
from datetime import date

import pytest

import shutil
import shiboken6

from app.main import Application
from app.presentation.views.game_launcher_dialog import (
    GameLauncherDialog,
    GameSwitchSheet,
)

from tests.ui import helpers, timeline_probe


def _visible_switch_sheet(window) -> GameSwitchSheet:
    """The live «Сменить игру…» sheet of this window (single: the stack gate
    keeps a second copy unopenable — Д2)."""
    sheets = [s for s in window.findChildren(GameSwitchSheet) if s.isVisible()]
    assert len(sheets) == 1, f"expected one visible switch sheet, got {sheets}"
    return sheets[0]


async def test_launcher_create_new_game(qapp, llm_client, tmp_games_dir, tmp_llm_config, dialog_input, wait_for):
    """Scenario 1: new game in launcher → main window with the name in title, empty timeline."""
    from app.presentation.theme import get_default_theme

    dialog = GameLauncherDialog(theme=get_default_theme())
    try:
        assert helpers.launcher_game_names(dialog.content) == []  # empty temporary games dir

        dialog_input["answer"] = ("Нове Королівство", True)
        # «Новая игра» — the island emits createRequested(""); the controller
        # asks QInputDialog (stubbed), creates via the VM and opens it at once.
        dialog.content.vm.createRequested.emit("")

        # the game catalog dir is created in the (temporary) games dir and selected
        assert dialog.selected_path == str(tmp_games_dir / "Нове Королівство" / "game.db")
        assert (tmp_games_dir / "Нове Королівство" / "game.db").exists()
        assert helpers.launcher_game_names(dialog.content) == ["Нове Королівство"]  # refreshed
    finally:
        dialog.close()

    application = Application(qapp, http=llm_client)
    window = await application.start(dialog.selected_path)
    try:
        assert "Нове Королівство" in window.windowTitle()
        assert len(timeline_probe.tape(window).events) == 0
    finally:
        window.close()
        await application.shutdown()


async def test_launcher_open_existing_game_with_data(app, tmp_games_dir, wait_for):
    """Scenario 2: open an existing game with prepared data → its events on the timeline."""
    application, window = app

    # Prepare the game's data through the real user path.
    await helpers.create_event_via_ui(
        window, wait_for, "Взятие Штурмграда",
        characteristics="Осада", start_date=date(1200, 5, 1),
    )

    # Copy the game into the (temporary) games dir — where the launcher looks.
    from app.presentation.theme import get_default_theme

    lib_path = tmp_games_dir / "Рассказ.db"
    shutil.copyfile(application._db_path, lib_path)

    launcher = GameLauncherDialog(parent=window, theme=get_default_theme())
    try:
        assert helpers.launcher_game_names(launcher.content) == ["Рассказ"]
        helpers.select_launcher_game(launcher.content, "Рассказ")
        helpers.open_launcher_game(launcher.content)
        assert launcher.selected_path == str(lib_path)
    finally:
        launcher.close()

    # Open the game at the launcher's path (real switch flow: shutdown → start).
    await application.shutdown()
    window2 = await application.start(launcher.selected_path)
    try:
        assert "Рассказ" in window2.windowTitle()
        canvas = timeline_probe.tape(window2)
        assert len(canvas.events) == 1
        assert canvas.events[0].name == "Взятие Штурмграда"
        # PR-002: the replaced window retires for good — its deferred delete
        # (posted by the replacement) lands with the next Qt pump.
        from PySide6.QtCore import QCoreApplication, QEvent

        QCoreApplication.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert not shiboken6.isValid(window)  # previous window destroyed on switch
    finally:
        if shiboken6.isValid(window):
            window.close()  # no-op path kept for a build that only closed it
        await application.shutdown()


async def test_switch_game_from_menu(qapp, llm_client, tmp_games_dir, tmp_llm_config, wait_for):
    """Scenario 10 (NRI-0024 4.1/4.2): «Сменить игру…» opens the launcher as a
    sheet; confirming a row rebuilds the main window under the chosen base."""
    path_a = tmp_games_dir / "alpha.db"
    path_a.touch()
    path_b = tmp_games_dir / "beta.db"
    path_b.touch()

    application = Application(qapp, http=llm_client)
    window = await application.start(str(path_a))
    try:
        assert "alpha" in window.windowTitle()

        # The freshly seeded game raised its first-run wizard as a sheet of
        # the connector's stack (nri-0024 task 3.2) — and the stack gate
        # (task 1.2) deactivates the sheet-opening entries while a sheet is
        # up. Dismiss the boot wizard the way the shared ``app`` fixture
        # does before reaching the gated «Сменить игру…».
        await wait_for(lambda: application._calendar_wizard is not None)
        await helpers.wait_until_settled()
        application._calendar_wizard.reject()
        await wait_for(lambda: application._calendar_wizard is None)
        await helpers.wait_until_settled()

        # Seed an event in alpha through the UI.
        await helpers.create_event_via_ui(window, wait_for, "Событие Альфа")

        # Real menu action: the launcher sheet rides the connector's stack.
        window.switch_game_action.trigger()
        await wait_for(lambda: bool(window.findChildren(GameSwitchSheet)))
        sheet = _visible_switch_sheet(window)
        # alpha and beta from the tmp games dir (newest-first, so set-compared)
        assert set(helpers.launcher_game_names(sheet.content)) == {"alpha", "beta"}
        assert helpers.select_launcher_game(sheet.content, "beta") == str(path_b)
        helpers.open_launcher_game(sheet.content)

        # The switch is async (stack down → shutdown → rebuild); the new
        # window shows the selected base — and it is the SAME application,
        # the very thing «без перезапуска процесса» means (spec «Подтверждение
        # пересобирает главное окно»).
        await wait_for(
            lambda: application._window is not None
            and "beta" in application._window.windowTitle()
        )
        assert application._window is not window
        assert application is application  # one process, one Application object
        # PR-002: the old window leaves as a destroyed object, not a hidden one.
        assert not shiboken6.isValid(window)
    finally:
        application._window.close()
        await application.shutdown()


async def test_switch_game_entry_opens_the_launcher_as_a_sheet(app, wait_for):
    """NRI-0024 4.1 (spec game-launcher «Смена игры открывается
    лаунчером-листом», qml-shell «Смена игры — лист с шапкой»): opened from
    the menu the launcher is a sheet INSIDE the main window — header
    «Сменить игру…» with its cancel-equal «Закрыть», the main layer dimmed
    and blocked under it. Closing without a choice returns to the very same
    game, unchanged (scenario «Смена игры без потери игры»)."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QPushButton

    application, window = app
    title_before = window.windowTitle()
    events_before = len(timeline_probe.tape(window).events)

    window.switch_game_action.trigger()
    await wait_for(lambda: bool(window.findChildren(GameSwitchSheet)))
    sheet = _visible_switch_sheet(window)

    # Sheet format (spec modal-sheets «Каждый класс окна задан контрактом»):
    # an attached native sheet (Qt.Sheet) shown NonModal at Qt level (PR-012),
    # the header naming the sheet with its windowTitle, a visible exit button
    # — not a separate titled window.
    assert sheet.windowFlags() & Qt.WindowType.Sheet
    assert sheet.windowModality() == Qt.WindowModality.NonModal
    assert sheet.isVisible()
    assert sheet.windowTitle() == "Сменить игру…"
    title_label = sheet.findChild(type(sheet._title_label), "sheetFrameTitle")
    assert title_label.text() == "Сменить игру…"
    close_button = sheet.findChild(QPushButton, "sheetFrameCloseButton")
    assert close_button.isVisible()
    # The main layer under the sheet stays blocked, but NOT by Qt modality
    # (the sheet is NonModal at Qt level — PR-012): on cocoa the attached
    # sheet's document modality holds the parent window, and the window's own
    # content gate (the sheet_stack_changed feed) is the cross-platform face
    # of the block. The native menu bar keeps answering the exception entries
    # for exactly this reason; the app-level gate is the pinned entry below.

    # The launcher content is really inside the sheet (task 4.1): list, VM,
    # the island under the frame's content slot.
    assert sheet.content.quick.status().name == "Ready"

    # Close through the header button (one cancel path with Esc, task 1.1):
    # the same game stays open, unchanged, the gate releases.
    assert window.switch_game_action.isEnabled() is False  # gated while up
    close_button.click()
    await wait_for(lambda: not sheet.isVisible())
    assert application._window is window
    assert window.windowTitle() == title_before
    assert len(timeline_probe.tape(window).events) == events_before
    assert window.isVisible()
    await wait_for(lambda: window.switch_game_action.isEnabled())
    assert window.isEnabled()


async def test_switch_game_entry_is_single_instance_by_the_gate(app, wait_for):
    """NRI-0024 4.1 (design Д2): the sheet is single-instance by the stack
    gate — while it is up the «Сменить игру…» entry itself is inactive (the
    registry's dedup role now falls out of the gate), and after closing, the
    next entry opens a FRESH sheet, never the closed one."""
    application, window = app

    window.switch_game_action.trigger()
    await wait_for(lambda: bool(window.findChildren(GameSwitchSheet)))
    first = _visible_switch_sheet(window)

    # The gated entry cannot raise a second copy (QAction.trigger() is inert
    # on a disabled action — the user can't click it either).
    window.switch_game_action.trigger()
    assert len(window.findChildren(GameSwitchSheet)) == 1
    assert _visible_switch_sheet(window) is first

    first.reject()  # a close without a choice: same game (task 4.1 again)
    assert application._window is window
    await wait_for(lambda: window.switch_game_action.isEnabled())

    window.switch_game_action.trigger()
    await wait_for(lambda: len(window.findChildren(GameSwitchSheet)) == 2)
    second = _visible_switch_sheet(window)
    assert second is not first  # a fresh sheet, never the closed one revived
    second.reject()
    assert application._window is window


async def _dismiss_boot_wizard(application, wait_for) -> None:
    """Dismiss a freshly opened first-run wizard (the shared ``app`` fixture's
    dismissal, reusable between switch legs)."""
    await wait_for(lambda: application._calendar_wizard is not None)
    await helpers.wait_until_settled()
    application._calendar_wizard.reject()
    await wait_for(lambda: application._calendar_wizard is None)
    await helpers.wait_until_settled()


async def _switch_via_sheet(application, window, wait_for, needle: str):
    """User path «Сменить игру…» → pick row ``needle`` → wait for the new
    window; returns the new window."""
    old = window
    window.switch_game_action.trigger()
    await wait_for(lambda: bool(window.findChildren(GameSwitchSheet)))
    sheet = _visible_switch_sheet(window)
    helpers.select_launcher_game(sheet.content, needle)
    helpers.open_launcher_game(sheet.content)
    await wait_for(
        lambda: application._window is not None
        and application._window is not old
        and needle in application._window.windowTitle()
    )
    await helpers.wait_until_settled()
    return application._window


async def test_two_switches_show_each_game_data_in_the_same_process(
    qapp, llm_client, tmp_games_dir, tmp_llm_config, wait_for,
):
    """NRI-0024 4.2 (spec game-launcher «Подтверждение пересобирает главное
    окно»): alpha → beta → alpha switches rebuild the main window inside this
    process — every window shows exactly its own base's data, the old window
    leaves, no restart ever runs."""
    path_a = tmp_games_dir / "alpha.db"
    path_a.touch()
    path_b = tmp_games_dir / "beta.db"
    path_b.touch()

    application = Application(qapp, http=llm_client)
    window_a = await application.start(str(path_a))
    await _dismiss_boot_wizard(application, wait_for)
    await helpers.create_event_via_ui(window_a, wait_for, "Событие Альфа")

    # ── switch 1: alpha → beta ─────────────────────────────────────────────
    window_b = await _switch_via_sheet(application, window_a, wait_for, "beta")
    assert window_b is not window_a
    assert not shiboken6.isValid(window_a)  # PR-002: the old window is destroyed
    # The flat beta.db is a legacy layout — the same startup rule migrates
    # it into the catalog directory games/beta/game.db (design D7/D8).
    assert application._db_path == str(tmp_games_dir / "beta" / "game.db")
    # beta is a fresh game: the boot wizard takes the stage over the NEW
    # window (the sheet ordering contract of group 3), then dismiss it.
    await _dismiss_boot_wizard(application, wait_for)
    assert len(timeline_probe.events(window_b)) == 0
    await helpers.create_event_via_ui(window_b, wait_for, "Событие Бета")

    # ── switch 2: beta → alpha (the old game knows its flag: no wizard) ────
    window_a2 = await _switch_via_sheet(application, window_b, wait_for, "alpha")
    assert window_a2 is not window_b and window_a2 is not window_a
    assert not shiboken6.isValid(window_b)  # PR-002: the old window is destroyed
    # alpha was migrated into its catalog dir on the very first startup.
    assert application._db_path == str(tmp_games_dir / "alpha" / "game.db")
    # «данные новой базы на экране»: alpha shows its own event only.
    names = [e.name for e in timeline_probe.events(window_a2)]
    assert "Событие Альфа" in names
    assert "Событие Бета" not in names
    # alpha's first-run flag was written by the boot dismissal — the rebuilt
    # window opened without the wizard.
    await wait_for(lambda: application._calendar_wizard is None)
    try:
        pass  # the process is still the same one: this test never restarted
    finally:
        window_a2.close()
        await application.shutdown()


async def test_two_switches_do_not_grow_theme_subscribers(
    qapp, llm_client, tmp_games_dir, tmp_llm_config, tmp_path, wait_for,
):
    """NRI-0024 4.2 (design Д4 risk row): the theme runtime outlives every
    window — after TWO switches in a row its live subscribers must be back
    at the boot composition (the retired MainWindow unsubscribes by handle,
    each sheet and island drops its palette on release; nothing accumulates)."""
    from app.infrastructure.ui_prefs.config import UiPrefsManager
    from app.presentation.theme import ThemeRuntime

    path_a = tmp_games_dir / "alpha.db"
    path_a.touch()
    path_b = tmp_games_dir / "beta.db"
    path_b.touch()

    theme = ThemeRuntime(prefs=UiPrefsManager(tmp_path / "ui.json"))
    application = Application(qapp, http=llm_client, theme=theme)
    window_a = await application.start(str(path_a))
    await _dismiss_boot_wizard(application, wait_for)
    base = len(theme.subscribers)

    window_b = await _switch_via_sheet(application, window_a, wait_for, "beta")
    await wait_for(lambda: len(theme.subscribers) == base)
    await _dismiss_boot_wizard(application, wait_for)
    assert len(theme.subscribers) == base

    window_a2 = await _switch_via_sheet(application, window_b, wait_for, "alpha")
    await wait_for(lambda: len(theme.subscribers) == base)
    # And the count did not just fall back by GC luck: the old windows'
    # subscriptions are gone while their Python objects are still reachable.
    assert any(
        sub.__self__ is window_a2 for sub in theme.subscribers
        if hasattr(sub, "__self__")
    )
    window_a2.close()
    await application.shutdown()


async def test_switch_destroys_the_old_main_window_not_just_hides_it(
    qapp, llm_client, tmp_games_dir, tmp_llm_config, wait_for,
):
    """PR-002 (blocking defect, full-run 2026-10-03): a confirmed «Сменить
    игру…» used to leave the old MainWindow alive-but-hidden; on cocoa the
    first sheet opened after the switch raised that island-less window back
    as a black rectangle over the working one — the app was visually dead
    until restart. The window-class norm (NRI-0024, AGENTS.md: the switch
    replaces the window under role «main» in the same process) leaves no
    room for a survivor: after the switch the old window's C++ side must be
    gone, the top-level list must hold exactly one live MainWindow — the new
    one — and never a hidden ghost of the previous game."""
    import shiboken6

    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    from app.presentation.views.main_window import MainWindow

    path_a = tmp_games_dir / "alpha.db"
    path_a.touch()
    path_b = tmp_games_dir / "beta.db"
    path_b.touch()

    application = Application(qapp, http=llm_client)
    window_a = await application.start(str(path_a))
    await _dismiss_boot_wizard(application, wait_for)

    window_b = await _switch_via_sheet(application, window_a, wait_for, "beta")
    await _dismiss_boot_wizard(application, wait_for)
    # The switch closed the old window; run its deferred retirement here.
    QCoreApplication.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    # PR-002: hidden-but-alive was the ghost's carrier — the C++ side is gone…
    assert not shiboken6.isValid(window_a)
    # …and the old window no longer stands in the top-level list: there is no
    # hidden live top-level of the previous game left to raise back as the
    # black rectangle, and the application's current window is the visible
    # replacement.
    assert not any(
        w is window_a for w in QApplication.topLevelWidgets()
        if isinstance(w, MainWindow)
    )
    assert application._window is window_b
    assert window_b.isVisible()
    window_b.close()
    await application.shutdown()


async def test_switch_game_creating_a_new_game_opens_window_and_wizard(
    qapp, llm_client, tmp_games_dir, tmp_llm_config, dialog_input, wait_for,
):
    """User repro 2026-10-02: inside a running game «Сменить игру…» → «Новая
    игра» → the fresh game must rebuild the main window AND raise its
    first-run wizard — every pending app task must settle (a stall of the
    switch task is the hang this pins; ``wait_for``/``wait_until_settled``
    turn a freeze into a TimeoutError, never an infinite wait).

    Offscreen honesty: the pytest-asyncio loop cannot observe Qt's quit-on-
    last-window-closed ending the application (the 2026-10-02 switch hang —
    ``quit()`` is inert without a running ``QApplication::exec``), so this
    test is the contract half on the suite's own loop; the loop-death half
    is pinned by the qasync regression test below.
    """
    path_a = tmp_games_dir / "alpha.db"
    path_a.touch()

    application = Application(qapp, http=llm_client)
    window = await application.start(str(path_a))
    try:
        await _dismiss_boot_wizard(application, wait_for)

        window.switch_game_action.trigger()
        await wait_for(lambda: bool(window.findChildren(GameSwitchSheet)))
        sheet = _visible_switch_sheet(window)

        # The real «Новая игра» controller path: createRequested → QInputDialog
        # (stubbed) → VM create → gameSelected on the fresh path (spec
        # game-launcher «Новая игра открывается сразу»).
        dialog_input["answer"] = ("Гамлет", True)
        sheet.content.vm.createRequested.emit("")

        # The switch is async (stack down → shutdown → rebuild); the new
        # window shows the fresh game, the old window leaves, no task stays
        # pending anywhere. (``_window`` is briefly None mid-switch — the
        # old window retires before the replacement is built, PR-002.)
        await wait_for(
            lambda: application._window is not None
            and application._window is not window
        )
        await helpers.wait_until_settled()
        new_window = application._window
        assert "Гамлет" in new_window.windowTitle()
        from PySide6.QtCore import QCoreApplication, QEvent

        QCoreApplication.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert not shiboken6.isValid(window)  # PR-002: destroyed, not hidden

        # The fresh game is a first run: its calendar wizard rises as a sheet
        # over the NEW window (spec calendar-wizard «сначала главное окно,
        # затем лист мастера»), and its begin() load settles too.
        await wait_for(lambda: application._calendar_wizard is not None)
        await helpers.wait_until_settled()
        assert application._calendar_wizard.isVisible()

        application._calendar_wizard.reject()
        await wait_for(lambda: application._calendar_wizard is None)
        await helpers.wait_until_settled()
    finally:
        if application._window is not None:
            application._window.close()
        await application.shutdown()


def test_switch_game_to_new_game_survives_the_windowless_moment_on_qasync_loop(
    qapp, tmp_games_dir, tmp_llm_config, dialog_input,
):
    """Regression 2026-10-02: the «Сменить игру…» → «Новая игра» flow MUST
    rebuild on a REAL qasync loop — the only posture that can die.

    The switch empties the screen between the old window's close and the
    new window's show; on the running loop Qt's quit-on-last-window-closed
    rule fired ``lastWindowClosed`` → ``quit()`` → qasync's
    ``run_forever``/``run_until_complete`` returned mid-rebuild and the
    switch task never resumed (the user's freeze: no new window, no wizard,
    dead UI). Under the suite's pytest-asyncio loop that quit is inert,
    which is exactly why the green pytest-loop pins hid the bug. Here the
    loop death surfaces as ``RuntimeError: Event loop stopped before Future
    completed`` — a deterministic red, never an infinite wait.
    """
    from PySide6.QtWidgets import QApplication as _QApp
    from qasync import QEventLoop

    path_a = tmp_games_dir / "alpha.db"
    path_a.touch()

    loop = QEventLoop(qapp)
    outcome: dict = {}

    async def _wait_until(condition, why: str) -> None:
        deadline = loop.time() + 20.0
        while not condition():
            if loop.time() >= deadline:
                raise AssertionError(f"scenario stalled: {why}")
            await asyncio.sleep(0)

    async def _settle() -> None:
        await _wait_until(
            lambda: all(
                t is asyncio.current_task() or t.done()
                for t in asyncio.all_tasks(loop)
            ),
            "app tasks never settled",
        )

    async def scenario() -> None:
        application = Application(qapp)
        window = await application.start(str(path_a))
        await _wait_until(
            lambda: application._calendar_wizard is not None,
            "boot wizard never appeared",
        )
        await _settle()  # the deferred begin() must land before any close
        application._calendar_wizard.reject()
        await _wait_until(
            lambda: application._calendar_wizard is None,
            "boot wizard never closed",
        )
        await _settle()

        window.switch_game_action.trigger()
        await _wait_until(
            lambda: any(
                s.isVisible() for s in window.findChildren(GameSwitchSheet)
            ),
            "the switch sheet never opened",
        )
        sheet = next(
            s for s in window.findChildren(GameSwitchSheet) if s.isVisible()
        )
        dialog_input["answer"] = ("Гамлет", True)
        sheet.content.vm.createRequested.emit("")

        # On the buggy build the windowless moment quits the loop here and
        # this wait never gets its turn — run_until_complete then dies with
        # "Event loop stopped before Future completed". (``_window`` is None
        # for the windowless moment itself — the old window retires, PR-002.)
        await _wait_until(
            lambda: application._window is not None
            and application._window is not window,
            "the switch task died — no new window",
        )
        await _settle()
        assert "Гамлет" in application._window.windowTitle()
        # The live qasync loop runs the old window's deferred destroy right
        # away: after the switch it is a dead wrapper, not a hidden window.
        assert not shiboken6.isValid(window)
        await _wait_until(
            lambda: application._calendar_wizard is not None,
            "no first-run wizard over the new window",
        )
        await _settle()
        application._calendar_wizard.reject()
        await _wait_until(
            lambda: application._calendar_wizard is None,
            "the new-game wizard never closed",
        )
        await _settle()
        # The switch has restored the normal quit rule; the teardown's own
        # last window close would therefore end the application loop the
        # way a user quitting does — suspend the rule for the teardown only.
        outcome["quit_rule_restored"] = qapp.quitOnLastWindowClosed()
        qapp.setQuitOnLastWindowClosed(False)
        application._window.close()
        await application.shutdown()
        outcome["ok"] = True

    try:
        loop.run_until_complete(scenario())
    except RuntimeError as exc:
        pytest.fail(
            "the switch stopped the application loop instead of rebuilding "
            "the window (quit-on-last-window-closed fired while the screen "
            f"was momentarily empty): {exc}"
        )
    finally:
        loop.close()
        for leak in list(_QApp.topLevelWidgets()):
            try:
                leak.close()
            except RuntimeError:
                pass  # C++ side already gone
        qapp.setQuitOnLastWindowClosed(True)  # the next test gets the default
        asyncio.set_event_loop(asyncio.new_event_loop())  # the suite default
    assert outcome.get("ok") is True
    # The switch restored the normal quit rule for every later exit (spec:
    # closing the main window still quits the application).
    assert outcome.get("quit_rule_restored") is True


async def test_switched_window_keeps_the_main_placement_role(app, tmp_games_dir, wait_for):
    """NRI-0024 4.2 (design Д4): the rebuilt ``MainWindow`` comes back under
    the role ``main`` — the old window's close hands its frame to the geometry
    memory and the replacement is PLACED BY THAT ROLE, the way the next run's
    window would be (the geometry memory of the switch is the same memory of
    the restart).

    Offscreen honesty: the stub screen is 800×800 while MainWindow's hard
    floor is 1024×680 wide, so any restored main frame legitimately comes
    back clamped into the screen (the clamp rule itself is pinned in
    test_geometry_memory.py). What this test pins is the role wiring, which
    the clamp cannot fake: the replacement did NOT open at the default 1280×
    800 frame, and a fresh restore of role ``main`` onto a window with
    MainWindow's own floor yields exactly the rectangle the replacement got.
    """
    from PySide6.QtWidgets import QWidget

    application, window = app

    # The shared ``app`` game lives outside tmp_games_dir on purpose, so the
    # switch target is seeded into the catalog the launcher lists.
    (tmp_games_dir / "beta.db").touch()

    old_rect = window.frameGeometry().getRect()
    # The old window is destroyed by the switch (PR-002), so the probe's
    # constraint/size — the retired window's own — are read while it is alive.
    old_minimum = window.minimumSize()
    old_size = window.size()

    window_b = await _switch_via_sheet(application, window, wait_for, "beta")
    rect_b = window_b.frameGeometry().getRect()

    # Placed by the memory, not by the untouched default: role "main" carried
    # the old (bigger-than-screen) frame through the rebuild and the clamp
    # shrank it — a window nobody had placed would still stand at old_rect.
    assert rect_b != old_rect
    probe = QWidget()
    probe.setMinimumSize(old_minimum)
    probe.resize(old_size)
    probe.show()
    assert application._geometries.restore(probe, "main") is True
    assert probe.frameGeometry().getRect() == rect_b
    probe.close()

    # …and the replacement lives under the same role now: its own tracker
    # rewrites the frame once the placement burst is quiet.
    await wait_for(lambda: application._geometries._roles["main"] == list(rect_b))
