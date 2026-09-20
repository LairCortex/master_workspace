"""Settings loaders and mention wiring error paths: log instead of silent pass.

Characterization: a corrupted calendar value opens the app on the
«Стандартный» preset with one warning (C2, task 5.1 — replaces the deleted
``_load_month_settings`` fallback test), an LLM-settings DB failure never
propagates, and a failed mention search is logged.
"""
import asyncio
import json
import logging
import sqlite3
from unittest.mock import AsyncMock, MagicMock

from PySide6.QtWidgets import QMessageBox

from app.domain.game_calendar import DEFAULT_MONTH_NAMES, current_calendar
from app.main import Application
from app.presentation.utils.calendar_warnings import MONTH_WARNING_TITLE


async def test_corrupted_calendar_setting_opens_on_preset_with_one_warning(
    qapp, tmp_path, monkeypatch, caplog
):
    """Task 5.1: `start()` loads the calendar through the service; a damaged
    ``game_calendar`` value opens the game on the «Стандартный» preset, shows
    exactly one Russian warning citing the cause, logs the details and leaves
    the row untouched (spec «Повреждённое значение календарь-ключа»)."""
    db_path = tmp_path / "game" / "game.db"
    db_path.parent.mkdir(parents=True)
    (db_path.parent / "images").mkdir()
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

    warnings: list[tuple[str, str]] = []

    def _record_warning(parent, title, text, *args, **kwargs):
        warnings.append((title, text))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(_record_warning))

    application = Application(qapp)
    with caplog.at_level(
        logging.WARNING, logger="app.application.services.calendar_settings_service"
    ):
        window = await application.start(str(db_path))  # must not raise
    try:
        # The game opened fully, on the Gregorian preset...
        assert dict(current_calendar().month_names) == dict(DEFAULT_MONTH_NAMES)
        # ...with exactly one Russian warning naming the reason...
        assert len(warnings) == 1
        assert warnings[0][0] == MONTH_WARNING_TITLE
        assert "«Стандартный»" in warnings[0][1]
        assert "вставной день ссылается на несуществующий месяц" in warnings[0][1]
        # ...while the machine-readable details went to the log.
        assert "intercalary_unknown_month" in caplog.text
        # The damaged row is left for the future C4 master (design D4).
        conn = sqlite3.connect(str(db_path))
        try:
            stored = conn.execute(
                "SELECT value FROM game_settings WHERE key = 'game_calendar'"
            ).fetchone()
        finally:
            conn.close()
        assert stored[0] == broken
    finally:
        window.close()
        await application.shutdown()
    # Task 5.2: closing the game returns the active calendar to the preset.
    assert dict(current_calendar().month_names) == dict(DEFAULT_MONTH_NAMES)


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
