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

    # An event dated in May (the month that will be renamed).
    await helpers.create_event_via_ui(window, wait_for, "Фестиваль", start_date=QDate(1200, 5, 15))
    timeline = window.timeline_widget.list_widget
    await wait_for(lambda: any("15 Май 1200" in timeline.item(i).text() for i in range(timeline.count())))

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

    # The timeline re-renders with the custom month name.
    await wait_for(lambda: any(f"15 {CUSTOM_MAY} 1200" in timeline.item(i).text() for i in range(timeline.count())))

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
    await wait_for(lambda: any(f"15 {CUSTOM_MAY}-2 1200" in timeline.item(i).text() for i in range(timeline.count())))
    row2 = query_db(db_path, "SELECT value FROM game_settings WHERE key = 'custom_months'")
    assert row2 and f"{CUSTOM_MAY}-2" in row2[0][0]

    # Persistence: a fresh start on the same DB shows the custom names again.
    await application.shutdown()
    window2 = await application.start(str(db_path))
    try:
        timeline2 = window2.timeline_widget.list_widget
        await wait_for(lambda: any(
            f"15 {CUSTOM_MAY}-2 1200" in timeline2.item(i).text() for i in range(timeline2.count())
        ))
    finally:
        window.close()  # already closed by start(); safe no-op
        await application.shutdown()
