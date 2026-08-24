"""E2E launcher scenarios: new game (1), open existing game (2), switch game (10)."""
from __future__ import annotations

import shutil

from PySide6.QtCore import QDate

from app.main import Application
from app.presentation.views.game_launcher_dialog import GameLauncherDialog

from tests.ui import helpers


async def test_launcher_create_new_game(qapp, llm_client, tmp_games_dir, tmp_llm_config, dialog_input, wait_for):
    """Scenario 1: new game in launcher → main window with the name in title, empty timeline."""
    dialog = GameLauncherDialog()
    try:
        assert dialog.list_widget.count() == 0  # empty temporary games dir

        dialog_input["answer"] = ("Нове Королівство", True)
        dialog.new_button.click()

        # the game catalog dir is created in the (temporary) games dir and selected
        assert dialog.selected_path == str(tmp_games_dir / "Нове Королівство" / "game.db")
        assert (tmp_games_dir / "Нове Королівство" / "game.db").exists()
        assert dialog.list_widget.count() == 1  # list refreshed
    finally:
        dialog.close()

    application = Application(qapp, http=llm_client)
    window = await application.start(dialog.selected_path)
    try:
        assert "Нове Королівство" in window.windowTitle()
        assert window.timeline_widget.list_widget.count() == 0
    finally:
        window.close()
        await application.shutdown()


async def test_launcher_open_existing_game_with_data(app, tmp_games_dir, wait_for):
    """Scenario 2: open an existing game with prepared data → its events on the timeline."""
    application, window = app

    # Prepare the game's data through the real user path.
    await helpers.create_event_via_ui(
        window, wait_for, "Взятие Штурмграда",
        characteristics="Осада", start_date=QDate(1200, 5, 1),
    )

    # Copy the game into the (temporary) games dir — where the launcher looks.
    lib_path = tmp_games_dir / "Рассказ.db"
    shutil.copyfile(application._db_path, lib_path)

    launcher = GameLauncherDialog(parent=window)
    try:
        assert launcher.list_widget.count() == 1
        item = launcher.list_widget.item(0)
        assert "Рассказ" in item.text()
        helpers.select_item(launcher.list_widget, item)
        launcher.open_button.click()
        assert launcher.selected_path == str(lib_path)
    finally:
        launcher.close()

    # Open the game at the launcher's path (real switch flow: shutdown → start).
    await application.shutdown()
    window2 = await application.start(launcher.selected_path)
    try:
        assert "Рассказ" in window2.windowTitle()
        timeline = window2.timeline_widget.list_widget
        assert timeline.count() == 1
        assert "Взятие Штурмграда" in timeline.item(0).text()
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
        assert launcher.list_widget.count() == 2  # alpha and beta from the tmp games dir
        beta = next(
            launcher.list_widget.item(i)
            for i in range(launcher.list_widget.count())
            if "beta" in launcher.list_widget.item(i).text()
        )
        helpers.select_item(launcher.list_widget, beta)
        launcher.open_button.click()
        assert launcher.selected_path == str(path_b)

        # The switch is async (shutdown → start); wait for the new window.
        await wait_for(lambda: "beta" in application._window.windowTitle())
        assert application._window is not window
        assert not window.isVisible()
    finally:
        application._window.close()
        await application.shutdown()
