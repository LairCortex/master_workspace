"""E2E scenario 8: custom month names are displayed on the timeline (and persist).

Spec «Игровые месяцы» (simplify-event-timeline-flat-list): the flat row
captions and the «Выбор даты» chip use the game's month map, re-read live on
every rebuild — the ladder's day headers are gone (REMOVED «Лента дней и
карточки событий»), the flat list has one caption per event."""
from __future__ import annotations

import datetime
from pathlib import Path

from PySide6.QtCore import QDate
from app.presentation.views.month_settings_dialog import MonthSettingsDialog

from tests.presentation import qml_helpers
from tests.ui import helpers, timeline_probe
from tests.ui.conftest import query_db

CUSTOM_MAY = "Медвежарь"


def _row_captions(canvas) -> list[str]:
    """Game-formatted captions of every flat row the VM currently models."""
    return [row.caption for row in canvas.rows]


async def test_custom_months_displayed_on_timeline(app, wait_for):
    application, window = app
    db_path = Path(application._db_path)

    # An event starting on the first of May (the month that will be renamed)
    # and running into June: its single row caption carries both month names.
    await helpers.create_event_via_ui(
        window, wait_for, "Фестиваль",
        start_date=QDate(1200, 5, 1), end_date=QDate(1200, 6, 20),
    )
    canvas = timeline_probe.tape(window)
    await wait_for(lambda: helpers.has_event_named(window, "Фестиваль"))
    # The row caption carries the full game dates built from the game's month
    # names — one row, one caption (spec «Плоский список событий»).
    captions = _row_captions(canvas)
    assert len(captions) == 1
    assert "01 Май 1200" in captions[0]
    assert "20 Июнь 1200" in captions[0]

    # A window on the renamed month proves the chip caption reads the same
    # live map (spec «Игровые месяцы»: the chip spells window bounds in game
    # months); the event crosses it, so its row stays visible.
    window.timeline_widget.window_changed.emit(
        datetime.date(1200, 5, 1), datetime.date(1200, 5, 31)
    )
    await helpers.wait_until_settled()
    assert len(canvas.rows) == 1
    assert "01 Май 1200" in timeline_probe.chip_caption(window)

    # Settings dialog (menu action) → rename May.
    window.month_settings_action.trigger()
    await wait_for(lambda: bool(window.findChildren(MonthSettingsDialog)))
    dialog = window.findChildren(MonthSettingsDialog)[0]
    may_input = qml_helpers.find_item(dialog.quick, "monthField5")
    may_input.setProperty("text", CUSTOM_MAY)
    qml_helpers.click_item(dialog.quick, qml_helpers.find_item(dialog.quick, "saveButton"))
    await helpers.wait_until_settled()  # the settings-save task owns the session

    # The row caption and the chip re-read the live month map: the renamed
    # month answers with the custom name (both on rows and on the chip, the
    # rows rebuilt by the reload following the settings save).
    await wait_for(
        lambda: any(f"01 {CUSTOM_MAY} 1200" in cap for cap in _row_captions(canvas))
    )
    await wait_for(lambda: CUSTOM_MAY in timeline_probe.chip_caption(window))
    assert any("20 Июнь 1200" in cap for cap in _row_captions(canvas))

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
    may_input2 = qml_helpers.find_item(dialog2.quick, "monthField5")
    may_input2.setProperty("text", f"{CUSTOM_MAY}-2")
    qml_helpers.click_item(dialog2.quick, qml_helpers.find_item(dialog2.quick, "saveButton"))
    await helpers.wait_until_settled()  # do not race the save task with shutdown
    await wait_for(
        lambda: any(f"01 {CUSTOM_MAY}-2 1200" in cap for cap in _row_captions(canvas))
    )
    row2 = query_db(db_path, "SELECT value FROM game_settings WHERE key = 'custom_months'")
    assert row2 and f"{CUSTOM_MAY}-2" in row2[0][0]

    # Persistence: a fresh start on the same DB shows the custom names again.
    await application.shutdown()
    window2 = await application.start(str(db_path))
    try:
        canvas2 = timeline_probe.tape(window2)
        await wait_for(
            lambda: any(f"01 {CUSTOM_MAY}-2 1200" in cap for cap in _row_captions(canvas2))
        )
    finally:
        window.close()  # already closed by start(); safe no-op
        await application.shutdown()
