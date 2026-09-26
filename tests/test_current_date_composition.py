"""NRI-0021 task 2.3: the composition root loads the «now» and hands it over.

Runs the real ``Application.start()`` on throwaway temporary game DBs and
pins the wiring the composition root establishes for the game's «now»:
the service is built and loaded after the calendar became active, reaches
the presentation through ``ApplicationWiring``, the first run serves the
real today (frozen here), an explicit edit survives a restart, and a second
game opens on its own absent-key value — the spec scenarios «Новая игра
стартует сегодняшним днём», «Значение помнится после перезапуска» and «Игры
не обмениваются датами» at the storage/service seam.

The date widget's view model itself is group 3 (task 3.1); until it exists
this test pins the value's arrival at the wiring — the presentation's
carrier per design Д2.
"""
from __future__ import annotations

from datetime import date

import pytest
from PySide6.QtWidgets import QDialog

import app.application.services.current_date_service as current_date_module
from app.application.services.current_date_service import CurrentDateService
from app.domain.game_calendar import MonthDay, reset_current_calendar
from app.infrastructure.repositories.game_settings_repository import CurrentDateValue
from app.main import Application
from app.presentation.views.calendar_wizard import CalendarWizardDialog

FROZEN_TODAY = date(2027, 3, 14)


@pytest.fixture(autouse=True)
def autoaccept_calendar_wizard(monkeypatch):
    """The started games are freshly seeded, so the C4 first-entry wizard
    opens; offscreen must not block on a real modal loop (the same seam the
    startup-order suite pins)."""
    monkeypatch.setattr(
        CalendarWizardDialog,
        "exec",
        lambda self, *args: QDialog.DialogCode.Rejected,
    )


@pytest.fixture(autouse=True)
def frozen_real_today(monkeypatch):
    """Freeze the service module's «real today» reader: start() calls
    ``load()`` without arguments, so the seed comes from ``date.today()``."""

    class _FrozenDate:
        @staticmethod
        def today() -> date:
            return FROZEN_TODAY

    monkeypatch.setattr(current_date_module, "date", _FrozenDate)


@pytest.fixture(autouse=True)
def _fresh_active_calendar():
    reset_current_calendar()
    yield
    reset_current_calendar()


def _game_db(tmp_path, name: str) -> str:
    game_dir = tmp_path / name
    game_dir.mkdir(parents=True, exist_ok=True)
    return str(game_dir / "game.db")


class TestCurrentDateCompositionRoot:
    async def test_start_loads_today_into_the_service_and_the_wiring(
        self, qapp, tmp_path
    ):
        application = Application(qapp)
        window = await application.start(_game_db(tmp_path, "NowGame"))
        try:
            service = application._current_date_service
            assert isinstance(service, CurrentDateService)
            # first run without any saved key: the real today, standard era
            assert service.value == CurrentDateValue(
                MonthDay(FROZEN_TODAY.year, FROZEN_TODAY.month, FROZEN_TODAY.day),
                False,
            )
            assert service.revision == 0
            # the presentation carrier of Д2 — the wiring holds this very
            # service; group 3's widget VM is fed through it
            assert application._wiring.current_date_service is service
        finally:
            window.close()
            await application.shutdown()

    async def test_edit_survives_restart_and_games_stay_isolated(
        self, qapp, tmp_path
    ):
        db_a = _game_db(tmp_path, "GameA")
        db_b = _game_db(tmp_path, "GameB")
        edited = CurrentDateValue(MonthDay(44, 11, 3), True)

        application = Application(qapp)
        window = await application.start(db_a)
        try:
            # the master's edit runs through the same UoW the app shares —
            # scheduled on the wiring lock like every session-touching task
            # (a concurrent first-run wizard task may hold the session).
            await application._wiring.run_locked(
                application._current_date_service.set_now(
                    edited.coord, edited.is_bc
                )
            )
            assert application._current_date_service.value == edited
        finally:
            window.close()
            await application.shutdown()

        # reopen game A: the stored value, not the frozen today
        application = Application(qapp)
        window = await application.start(db_a)
        try:
            assert application._current_date_service.value == edited
        finally:
            window.close()
            await application.shutdown()

        # game B never saw game A's key: it opens on the real today
        application = Application(qapp)
        window = await application.start(db_b)
        try:
            assert application._current_date_service.value == CurrentDateValue(
                MonthDay(
                    FROZEN_TODAY.year, FROZEN_TODAY.month, FROZEN_TODAY.day
                ),
                False,
            )
        finally:
            window.close()
            await application.shutdown()
