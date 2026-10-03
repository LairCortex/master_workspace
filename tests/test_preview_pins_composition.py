"""NRI-0025 task 1.2: the composition root builds the preview-pins service.

Runs the real ``Application.start()`` on throwaway temporary game DBs and
pins the wiring the composition root establishes for the preview column's
pins: the game-bound ``PreviewPinsService`` exists after start, a fresh game
reads no pins (absent key = empty list), and a list saved through the
composed service survives an app restart in pin order — the storage half of
the spec «Закрепления хранятся в настройках игры и переживают перезапуск»
at the composition seam (the connector's slot lifecycle is group 5).
"""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QDialog

from app.application.services.preview_pins_service import PreviewPinsService
from app.domain.game_calendar import reset_current_calendar
from app.main import Application
from app.presentation.views.calendar_wizard import CalendarWizardDialog

PINS = [("character", 3), ("item", 1)]


@pytest.fixture(autouse=True)
def autoaccept_calendar_wizard(monkeypatch):
    """The started games are freshly seeded, so the C4 first-entry wizard
    opens; offscreen must not block on a real modal loop (the same seam the
    «now» composition suite pins)."""
    monkeypatch.setattr(
        CalendarWizardDialog,
        "exec",
        lambda self, *args: QDialog.DialogCode.Rejected,
    )


@pytest.fixture(autouse=True)
def _fresh_active_calendar():
    reset_current_calendar()
    yield
    reset_current_calendar()


def _game_db(tmp_path, name: str) -> str:
    game_dir = tmp_path / name
    game_dir.mkdir(parents=True, exist_ok=True)
    return str(game_dir / "game.db")


class TestPreviewPinsCompositionRoot:
    async def test_start_composes_the_service_and_absence_reads_empty(
        self, qapp, tmp_path
    ):
        application = Application(qapp)
        window = await application.start(_game_db(tmp_path, "PinGame"))
        try:
            service = application._preview_pins_service
            assert isinstance(service, PreviewPinsService)
            # a game nobody ever pinned opens with an empty column memory
            assert await application._wiring.run_locked(service.get_pins()) == []
        finally:
            window.close()
            await application.shutdown()

    async def test_saved_order_survives_app_restart(self, qapp, tmp_path) -> None:
        db = _game_db(tmp_path, "PinGame")
        application = Application(qapp)
        window = await application.start(db)
        try:
            # scheduled on the wiring lock like every session-touching task
            await application._wiring.run_locked(
                application._preview_pins_service.save_pins(PINS)
            )
        finally:
            window.close()
            await application.shutdown()

        # reopen the same game: the same pairs, the same order
        application = Application(qapp)
        window = await application.start(db)
        try:
            assert await application._wiring.run_locked(
                application._preview_pins_service.get_pins()
            ) == PINS
        finally:
            window.close()
            await application.shutdown()

    async def test_games_do_not_share_pins(self, qapp, tmp_path):
        db_a = _game_db(tmp_path, "PinA")
        db_b = _game_db(tmp_path, "PinB")
        application = Application(qapp)
        window = await application.start(db_a)
        try:
            await application._wiring.run_locked(
                application._preview_pins_service.save_pins(PINS)
            )
        finally:
            window.close()
            await application.shutdown()

        application = Application(qapp)
        window = await application.start(db_b)
        try:
            assert await application._wiring.run_locked(
                application._preview_pins_service.get_pins()
            ) == []
        finally:
            window.close()
            await application.shutdown()
