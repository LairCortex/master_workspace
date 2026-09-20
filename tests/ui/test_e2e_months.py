"""E2E scenario 8: month names obtained by migrating the deprecated setting
display on the timeline (ui-testing «Кастомные месяцы», piece C2).

The month-settings dialog is deleted (roadmap C2): the game's names now come
from the ``game_calendar`` key, and the legacy ``custom_months`` row is
carried into it once when the game opens. This test boots the real app,
creates an event across two months, closes the game, plants a legacy
``custom_months`` row directly in the file (as a pre-C2 app version wrote it),
reopens, and asserts both sides of the C2 contract on the UI and the data:
the timeline captions and the «Выбор даты» chip speak the migrated names,
``game_calendar`` appeared, and ``custom_months`` is gone.
"""
from __future__ import annotations

import datetime
import json
import sqlite3
from pathlib import Path

from PySide6.QtCore import QDate

from tests.ui import helpers, timeline_probe
from tests.ui.conftest import query_db

CUSTOM_MAY = "Медвежарь"


def _row_captions(canvas) -> list[str]:
    """Game-formatted captions of every flat row the VM currently models."""
    return [row.caption for row in canvas.rows]


async def test_migrated_month_names_display_on_timeline(app, wait_for):
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

    # A window on the month that will be renamed proves the chip caption
    # reads the same live calendar (spec «Игровые месяцы»: the chip spells
    # window bounds in game months); the event crosses it, so its row stays
    # visible.
    window.timeline_widget.window_changed.emit(
        datetime.date(1200, 5, 1), datetime.date(1200, 5, 31)
    )
    await helpers.wait_until_settled()
    assert len(canvas.rows) == 1
    assert "01 Май 1200" in timeline_probe.chip_caption(window)

    # A regular close hands the whole file back to the disk…
    await application.shutdown()

    # …and an old-version month-names row is planted as the removed dialog
    # used to write it (key ``custom_months``).
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO game_settings (key, value) VALUES ('custom_months', ?)",
        (json.dumps({"5": CUSTOM_MAY}, ensure_ascii=False),),
    )
    conn.commit()
    conn.close()

    # Reopening migrates the key into ``game_calendar`` and activates the
    # renamed preset (spec «Перенос устаревшей настройки названий месяцев»).
    window2 = await application.start(str(db_path))
    try:
        canvas2 = timeline_probe.tape(window2)
        # The row caption re-reads the live calendar: the migrated month
        # answers with the game's name while the untouched month stays
        # Gregorian.
        await wait_for(
            lambda: any(f"01 {CUSTOM_MAY} 1200" in cap for cap in _row_captions(canvas2))
        )
        assert any("20 Июнь 1200" in cap for cap in _row_captions(canvas2))

        # The chip speaks the same calendar.
        window2.timeline_widget.window_changed.emit(
            datetime.date(1200, 5, 1), datetime.date(1200, 5, 31)
        )
        await helpers.wait_until_settled()
        await wait_for(lambda: CUSTOM_MAY in timeline_probe.chip_caption(window2))

        # Storage side of the migration (spec): the new key carries the
        # override, the deprecated key is deleted — repeated opens do not
        # migrate again.
        new = query_db(db_path, "SELECT value FROM game_settings WHERE key = 'game_calendar'")
        assert new and CUSTOM_MAY in new[0][0]
        old = query_db(db_path, "SELECT value FROM game_settings WHERE key = 'custom_months'")
        assert not old
    finally:
        window2.close()
