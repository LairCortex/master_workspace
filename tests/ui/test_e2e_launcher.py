"""E2E launcher scenarios: new game (1), open existing game (2), switch game (10)."""
from __future__ import annotations

from datetime import date

import shutil


from app.main import Application
from app.presentation.views.game_launcher_dialog import GameLauncherDialog

from tests.ui import helpers, timeline_probe


async def test_launcher_create_new_game(qapp, llm_client, tmp_games_dir, tmp_llm_config, dialog_input, wait_for):
    """Scenario 1: new game in launcher → main window with the name in title, empty timeline."""
    from app.presentation.theme import get_default_theme

    dialog = GameLauncherDialog(theme=get_default_theme())
    try:
        assert helpers.launcher_game_names(dialog) == []  # empty temporary games dir

        dialog_input["answer"] = ("Нове Королівство", True)
        # «Новая игра» — the island emits createRequested(""); the controller
        # asks QInputDialog (stubbed), creates via the VM and opens it at once.
        dialog.vm.createRequested.emit("")

        # the game catalog dir is created in the (temporary) games dir and selected
        assert dialog.selected_path == str(tmp_games_dir / "Нове Королівство" / "game.db")
        assert (tmp_games_dir / "Нове Королівство" / "game.db").exists()
        assert helpers.launcher_game_names(dialog) == ["Нове Королівство"]  # refreshed
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
        assert helpers.launcher_game_names(launcher) == ["Рассказ"]
        helpers.select_launcher_game(launcher, "Рассказ")
        helpers.open_launcher_game(launcher)
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
        assert not window.isVisible()  # previous window closed on switch
    finally:
        window.close()  # no-op if start() already closed it
        await application.shutdown()


async def test_switch_game_from_menu(qapp, llm_client, tmp_games_dir, tmp_llm_config, wait_for):
    """Scenario 10: switch game from the menu → new window opens, old one closed."""
    path_a = tmp_games_dir / "alpha.db"
    path_a.touch()
    path_b = tmp_games_dir / "beta.db"
    path_b.touch()

    application = Application(qapp, http=llm_client)
    window = await application.start(str(path_a))
    try:
        assert "alpha" in window.windowTitle()

        # Seed an event in alpha through the UI.
        await helpers.create_event_via_ui(window, wait_for, "Событие Альфа")

        # Real menu action: shutdown → launcher → start the selected game.
        window.switch_game_action.trigger()
        await wait_for(lambda: bool(window.findChildren(GameLauncherDialog)))
        launcher = window.findChildren(GameLauncherDialog)[0]
        # alpha and beta from the tmp games dir (newest-first, so set-compared)
        assert set(helpers.launcher_game_names(launcher)) == {"alpha", "beta"}
        helpers.select_launcher_game(launcher, "beta")
        helpers.open_launcher_game(launcher)
        assert launcher.selected_path == str(path_b)

        # The switch is async (shutdown → start); wait for the new window.
        await wait_for(lambda: "beta" in application._window.windowTitle())
        assert application._window is not window
        assert not window.isVisible()
    finally:
        application._window.close()
        await application.shutdown()


async def test_switch_game_entry_shows_visible_non_modal_titled_window(app, wait_for):
    """NRI-0014 3.1 (A1/A2): «Сменить игру…» gives a REAL non-modal window.

    spec game-launcher «Формат лаунчера зависит от точки входа»: opened from
    the menu the launcher is a visible titled window whose modality is
    NonModal (open() under a parent was a WindowModal sheet that silently
    blocked the rest of the menu, contradicting the code comment). Closing
    it without a choice returns to the same game, unchanged.
    """
    from PySide6.QtCore import Qt

    application, window = app
    title_before = window.windowTitle()

    window.switch_game_action.trigger()
    await wait_for(lambda: bool(window.findChildren(GameLauncherDialog)))
    launcher = window.findChildren(GameLauncherDialog)[0]
    assert launcher.windowModality() == Qt.WindowModality.NonModal
    assert not launcher.isModal()
    assert launcher.isVisible()
    assert launcher.windowTitle()  # non-empty: A2 wanted a visible title bar
    assert window.isEnabled()  # A1: the caller's window/menu stays alive

    # Closing without a choice: the key is released and the very same game
    # stays open — the switch flow was entered but never left.
    launcher.close()
    assert application._window is window
    assert window.windowTitle() == title_before
    assert window.isVisible()


async def test_switch_game_second_click_reuses_launcher_window(app, wait_for, monkeypatch):
    """NRI-0014 1.2: повторный «Сменить игру…» поднимает открытый лаунчер.

    The entry goes through MenuWindowRegistry (key ``launcher_switch``): a
    repeated click must not stack a second dialog (AB4); closing releases
    the key and the next open builds a fresh window again.
    """
    import asyncio

    import app.main as main_mod
    from app.presentation.window_registry import LAUNCHER_SWITCH_KEY

    application, window = app
    created: list[GameLauncherDialog] = []

    class CountingLauncher(GameLauncherDialog):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created.append(self)

    monkeypatch.setattr(main_mod, "GameLauncherDialog", CountingLauncher)

    window.switch_game_action.trigger()
    await wait_for(lambda: bool(created))
    launcher = created[0]

    # Second click while the launcher is open: the handler is synchronous,
    # so one loop turn drains it — no second dialog may have been created.
    window.switch_game_action.trigger()
    await asyncio.sleep(0)
    assert len(created) == 1
    assert application._window_registry.get(LAUNCHER_SWITCH_KEY) is launcher

    # Closing releases the key …
    launcher.close()
    assert application._window_registry.get(LAUNCHER_SWITCH_KEY) is None

    # … and the entry opens a fresh window again.
    window.switch_game_action.trigger()
    await wait_for(lambda: len(created) == 2)
    assert created[1] is not launcher
    created[1].close()
