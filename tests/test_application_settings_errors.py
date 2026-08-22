"""Settings loaders and mention wiring error paths: log instead of silent pass.

Characterization: on DB/search failure the app continues (fallback to default
months, no propagated exception) — the observable difference is only a log
record now.
"""
import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

from app.main import Application
from app.presentation.utils.date_utils import get_custom_months


async def test_load_month_settings_failure_falls_back_to_default(qapp, tmp_path, caplog):
    application = Application(qapp)
    await application.start(str(tmp_path / "fail.db"))
    try:
        before = get_custom_months()
        application._session.execute = AsyncMock(side_effect=RuntimeError("boom"))
        with caplog.at_level(logging.WARNING, logger="app.main"):
            await application._load_month_settings()  # must not raise
        # Fallback: month mapping is left untouched on failure
        assert get_custom_months() == before
        assert "Failed to load month settings" in caplog.text
    finally:
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
