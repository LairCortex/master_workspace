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
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
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

            async def boom(coord, is_bc=False, hour=None):
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

    async def test_hour_choice_writes_saves_and_moves_the_caption_only(
        self, qapp, tmp_path
    ):
        """NRI-0023 task 9.1 full round trip (spec «Час меняет только
        подпись», «Час помнится после перезапуска»): combo activation → the
        VM's request channel → one service transaction (the day half rides
        along untouched) → the applied-value mirror repaints the caption and
        the island combo — while the ``nowChanged`` broadcast every derived
        surface (возраст/длительности/обводка/прокрутка) subscribes to never
        fires for the hour."""
        application = Application(qapp)
        window = await application.start(_game_db(tmp_path, "NowHour"))
        try:
            wiring = application._wiring
            vm = wiring.now_date_vm
            service = application._current_date_service
            now_changed = track(vm.nowChanged)
            combo = find_item(window.search_bar.quick, "nowHourCombo")
            chip = find_item(window.search_bar.quick, "nowDateField")

            # 21-я строка списка — час 20; запись идёт через set_now.
            vm.requestHour(21)
            edited = CurrentDateValue(
                MonthDay(FROZEN_TODAY.year, FROZEN_TODAY.month, FROZEN_TODAY.day),
                False,
                20,
            )
            assert await _drain(lambda: service.value == edited)
            assert service.revision == 1
            assert await _drain(lambda: vm.caption.endswith(", 20:00"))
            assert vm.hour == 20
            assert chip.property("display") == vm.caption
            assert combo.property("currentIndex") == 21
            # производные не дёргались: канал nowChanged для часа молчит
            assert now_changed == []

            # «—» снимает час: подпись и сохранённое значение возвращаются
            # к виду «без часа» (тот же канал, та же транзакция).
            vm.requestHour(0)
            assert await _drain(lambda: service.value.hour is None)
            assert service.revision == 2
            assert vm.caption == "Сейчас: 14 Март 2027"
            assert combo.property("currentIndex") == 0
            assert now_changed == []
        finally:
            window.close()
            await application.shutdown()

    async def test_date_edit_keeps_the_set_hour(self, qapp, tmp_path):
        """The popup answers with the date half only; the served hour is the
        other half of the same value and rides the write untouched — the
        value that comes back is (новая дата, преждний час)."""
        application = Application(qapp)
        window = await application.start(_game_db(tmp_path, "NowKeepHour"))
        try:
            wiring = application._wiring
            vm = wiring.now_date_vm
            service = application._current_date_service
            now_changed = track(vm.nowChanged)

            vm.requestHour(21)  # час 20
            assert await _drain(lambda: service.value.hour == 20)

            vm.requestDatePopup(0.0, 0.0, 10.0, 10.0)
            popup = wiring._now_date_popup
            popup.calendar.day_selected.emit(MonthDay(44, 11, 3))

            edited = CurrentDateValue(MonthDay(44, 11, 3), False, 20)
            assert await _drain(lambda: service.value == edited)
            assert service.revision == 2
            # смена ДНЯ — это редактирование и для производных: канал сработал
            assert await _drain(lambda: now_changed != [])
            assert vm.caption == "Сейчас: 03 Ноябрь 44, 20:00"
        finally:
            window.close()
            await application.shutdown()

    async def test_hour_popup_bridges_over_the_low_host_and_picks_hours_and_dash(
        self, qapp, tmp_path
    ):
        """Task 12.6 (A1 host half, spec «Все значения часов достижимы»): the
        list opens as its own top level, taller than the fixed-height search
        island that clips it (the live defect offscreen-invisible in the old
        posture) — the wheel/click route to hour 23 lands exactly there, and
        reopening with the current row highlighted answers «—» on its click."""
        application = Application(qapp)
        window = await application.start(_game_db(tmp_path, "NowHourBridge"))
        try:
            wiring = application._wiring
            vm = wiring.now_date_vm
            service = application._current_date_service
            now_changed = track(vm.nowChanged)

            vm.requestHourPopup(263.0, 78.0, 70.0, 24.0)  # the live anchor rect
            popup = wiring._now_hour_popup
            assert popup is not None and popup.isVisible()
            assert popup.parent() is None  # widgets bridge, never inside the host
            # The A1 pin in the real composition: the window outgrows the
            # island widget that previously cut the QML popup to ~2.3 rows.
            assert popup.height() > window.search_bar.height()
            assert [
                popup.list.item(i).text() for i in range(popup.list.count())
            ] == list(vm.hourOptions)  # «—» + 0…23, the VM's active-day list
            assert popup.list.currentRow() == 0

            # «колесо до конца, выбрать 23» — the deepest row, real mouse
            # click on its viewport rect after scrolling it into view.
            item = popup.list.item(popup.list.count() - 1)
            popup.list.setCurrentRow(popup.list.count() - 1)
            QTest.qWait(20)
            QTest.mouseClick(
                popup.list.viewport(), Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                popup.list.visualItemRect(item).center(),
            )
            edited = CurrentDateValue(
                MonthDay(FROZEN_TODAY.year, FROZEN_TODAY.month, FROZEN_TODAY.day),
                False,
                23,
            )
            assert await _drain(lambda: service.value == edited)
            assert service.revision == 1
            assert await _drain(lambda: vm.caption.endswith(", 23:00"))
            assert now_changed == []  # час — только подпись (spec)

            # Reopen: the current hour is the highlighted row; «—» returns.
            vm.requestHourPopup(263.0, 78.0, 90.0, 24.0)
            assert popup.list.currentRow() == 24
            popup.list.setCurrentRow(0)  # the «—» head, scrolled back in view
            QTest.qWait(20)
            QTest.mouseClick(
                popup.list.viewport(), Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                popup.list.visualItemRect(popup.list.item(0)).center(),
            )
            assert await _drain(lambda: service.value.hour is None)
            assert service.revision == 2
            assert await _drain(lambda: vm.caption == "Сейчас: 14 Март 2027")
            assert now_changed == []
        finally:
            window.close()
            await application.shutdown()

    async def test_failed_hour_write_reports_and_leaves_the_caption_alone(
        self, qapp, tmp_path, monkeypatch
    ):
        """Same modal posture as the date half: a failed hour transaction
        never moves the served value, the mirror or the caption."""
        application = Application(qapp)
        window = await application.start(_game_db(tmp_path, "NowHourFail"))
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

            async def boom(coord, is_bc=False, hour=None):
                raise RuntimeError("диск сгорел")

            monkeypatch.setattr(service, "set_now", boom)
            now_changed = track(vm.nowChanged)

            vm.requestHour(21)

            assert await _drain(lambda: reported != [])
            assert "диск сгорел" in reported[0][2]
            assert service.value.hour is None
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
    assert wiring._now_hour_popup is None
    assert wiring.now_date_vm is None
