"""NRI-0021 task 3.3 — the full «now» widget round trip on a real game.

Runs the real ``Application.start()`` on a throwaway temporary DB and pins the
binding the connector establishes for the widget (spec current-date «Виджет
„Сейчас: <дата>“», scenario «Смена даты пересчитывает всё»; spec qml-shell
«Выбор даты идёт через widgets-мост»): VM signal → parent-less
``ThemeDatePopup`` with the game-calendar grid prefilled with the served
value → one service transaction → the applied-value slot → ``nowChanged`` and
the island caption, all without a restart. The failure half (the modal, the
untouched caption) is pinned too — «any persistence error reaches the user».
"""
from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QDialog

import app.application.services.current_date_service as current_date_module
import app.presentation.wiring as wiring_module
from app.domain.game_calendar import MonthDay, reset_current_calendar
from app.infrastructure.repositories.game_settings_repository import CurrentDateValue
from app.main import Application
from app.presentation.views.calendar_wizard import CalendarWizardDialog
from tests.presentation.qml_helpers import find_item, track
FROZEN_TODAY = date(2027, 3, 14)


@pytest.fixture(autouse=True)
def autoaccept_calendar_wizard(monkeypatch):
    """Offscreen must not block on the C4 first-entry wizard modal loop (the
    seam the startup-order and composition suites pin)."""
    monkeypatch.setattr(
        CalendarWizardDialog,
        "exec",
        lambda self, *args: QDialog.DialogCode.Rejected,
    )


@pytest.fixture(autouse=True)
def frozen_real_today(monkeypatch):
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


async def _drain(predicate, attempts: int = 300) -> bool:
    """Let the wiring-spawned task run on the test loop until settled."""
    for _ in range(attempts):
        await asyncio.sleep(0.01)
        if predicate():
            return True
    return predicate()


class TestNowDateWidgetFlow:
    async def test_pick_flows_popup_service_vm_and_caption_without_restart(
        self, qapp, tmp_path
    ):
        application = Application(qapp)
        window = await application.start(_game_db(tmp_path, "NowFlow"))
        try:
            wiring = application._wiring
            vm = wiring.now_date_vm
            service = wiring.current_date_service
            assert vm is not None

            # The island chip opens on the seeded value (group 2's load).
            chip = find_item(window.search_bar.quick, "nowDateField")
            assert chip.property("display") == "Сейчас: 14 Март 2027"
            now_changed = track(vm.nowChanged)

            # 1. VM signal → widgets bridge opens top-level, prefilled with
            #    the current value (coordinate AND era of the grid).
            vm.requestDatePopup(12.0, 12.0, 140.0, 24.0)
            popup = wiring._now_date_popup
            assert popup is not None
            # Spec «Выбор даты идёт через widgets-мост»: a parent-less
            # top-level, never a child of the island or its widget.
            assert popup.parent() is None
            assert popup.calendar.selection() == MonthDay(2027, 3, 14)
            assert popup.calendar.is_bc() is False

            # 2. The master clicks «3 Ноябрь 44 г. до н.э.» (the grid's own
            #    era switch + a day tap — the popup's tested channel).
            popup.calendar.set_era(True)
            popup.calendar.day_selected.emit(MonthDay(44, 11, 3))

            # 3. One service transaction, then the VM mirror (design Д2).
            edited = CurrentDateValue(MonthDay(44, 11, 3), True)
            assert await _drain(lambda: service.value == edited)
            assert service.revision == 1
            assert await _drain(lambda: now_changed != [])
            assert now_changed == [()]

            # 4. The caption updated in the very same window — no restart
            #    (spec «Смена даты пересчитывает всё»).
            assert await _drain(
                lambda: chip.property("display") == "Сейчас: 03 Ноябрь 44 г. до н.э."
            )
            assert chip.property("display") == vm.caption
            assert not popup.isVisible()  # the popup closed on the pick
        finally:
            window.close()
            await application.shutdown()

    async def test_failed_write_reports_and_leaves_the_caption_alone(
        self, qapp, tmp_path, monkeypatch
    ):
        application = Application(qapp)
        window = await application.start(_game_db(tmp_path, "NowFail"))
        try:
            wiring = application._wiring
            vm = wiring.now_date_vm
            service = application._current_date_service

            reported = []
            monkeypatch.setattr(
                wiring_module,
                "QMessageBox",
                SimpleNamespace(critical=lambda *args: reported.append(args)),
            )

            async def boom(coord, is_bc=False):
                raise RuntimeError("диск сгорел")

            monkeypatch.setattr(service, "set_now", boom)
            now_changed = track(vm.nowChanged)

            vm.requestDatePopup(0.0, 0.0, 10.0, 10.0)
            popup = wiring._now_date_popup
            popup.calendar.day_selected.emit(MonthDay(1, 1, 1))

            assert await _drain(lambda: reported != [])
            assert "диск сгорел" in reported[0][2]
            # The served value, the VM mirror and the caption stayed put —
            # applyNow runs only on a committed transaction.
            assert service.value == CurrentDateValue(
                MonthDay(FROZEN_TODAY.year, FROZEN_TODAY.month, FROZEN_TODAY.day),
                False,
            )
            assert service.revision == 0
            assert vm.caption == "Сейчас: 14 Март 2027"
            assert now_changed == []
        finally:
            window.close()
            await application.shutdown()


def test_connector_without_the_now_pair_has_no_widget_area():
    """A unit-built connector (no service, no VM) simply has no widget
    section — the documented default of the group-3 parameters."""
    wiring = wiring_module.ApplicationWiring(
        SimpleNamespace(_image_store=None),
        None, None, None, None, None, None,
        uow=SimpleNamespace(lock=asyncio.Lock()),
    )

    wiring._connect_now_date()

    assert wiring._now_date_popup is None
    assert wiring.now_date_vm is None
