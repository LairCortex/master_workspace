"""E2E scenario 8: custom month names are displayed on the timeline (and persist)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QLineEdit, QPushButton

from app.presentation.views.month_settings_dialog import MonthSettingsDialog

from tests.ui import helpers
from tests.ui.conftest import query_db

CUSTOM_MAY = "Медвежарь"


async def test_custom_months_displayed_on_timeline(app, wait_for):
    application, window = app
    db_path = Path(application._db_path)

    # An event starting on the first of May (the month that will be renamed)
    # and running into June, so the axis carries that month boundary as a tick.
    await helpers.create_event_via_ui(
        window, wait_for, "Фестиваль",
        start_date=QDate(1200, 5, 1), end_date=QDate(1200, 6, 20),
    )
    canvas = window.timeline_widget.rows_view
    await wait_for(lambda: helpers.has_event_named(window, "Фестиваль"))
    # The axis labels month boundaries through format_game_date with the game's
    # month names; the range start itself is never labeled (spec «Шкала времени»).
    await wait_for(lambda: "01 Май 1200" in canvas.axis_labels())
    assert "01 Июнь 1200" in canvas.axis_labels()

    # Settings dialog (menu action) → rename May.
    window.month_settings_action.trigger()
    await wait_for(lambda: bool(window.findChildren(MonthSettingsDialog)))
    dialog = window.findChildren(MonthSettingsDialog)[0]
    may_input = next(
        inp for inp in dialog.findChildren(QLineEdit) if inp.placeholderText() == "Май"
    )
    may_input.setText(CUSTOM_MAY)
    save_btn = next(b for b in dialog.findChildren(QPushButton) if b.text() == "Сохранить")
    save_btn.click()
    await helpers.wait_until_settled()  # the settings-save task owns the session

    # The scale re-renders with the custom month name on its axis.
    await wait_for(lambda: f"01 {CUSTOM_MAY} 1200" in canvas.axis_labels())

    # Stored in the game's game_settings (per-game key/value pattern).
    row = query_db(db_path, "SELECT value FROM game_settings WHERE key = 'custom_months'")
    assert row and CUSTOM_MAY in row[0][0]

    # Second save: the game_settings row already exists → update-in-place path.
    # Pick the VISIBLE dialog: the first one stayed in the child list after accept().
    window.month_settings_action.trigger()
    await wait_for(
        lambda: any(d.isVisible() for d in window.findChildren(MonthSettingsDialog))
    )
    dialog2 = next(d for d in window.findChildren(MonthSettingsDialog) if d.isVisible())
    may_input2 = next(
        inp for inp in dialog2.findChildren(QLineEdit) if inp.placeholderText() == "Май"
    )
    may_input2.setText(f"{CUSTOM_MAY}-2")
    save_btn2 = next(b for b in dialog2.findChildren(QPushButton) if b.text() == "Сохранить")
    save_btn2.click()
    await helpers.wait_until_settled()  # do not race the save task with shutdown
    await wait_for(lambda: f"01 {CUSTOM_MAY}-2 1200" in canvas.axis_labels())
    row2 = query_db(db_path, "SELECT value FROM game_settings WHERE key = 'custom_months'")
    assert row2 and f"{CUSTOM_MAY}-2" in row2[0][0]

    # Persistence: a fresh start on the same DB shows the custom names again.
    await application.shutdown()
    window2 = await application.start(str(db_path))
    try:
        canvas2 = window2.timeline_widget.rows_view
        await wait_for(lambda: f"01 {CUSTOM_MAY}-2 1200" in canvas2.axis_labels())
    finally:
        window.close()  # already closed by start(); safe no-op
        await application.shutdown()
