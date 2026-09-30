"""Game-«now» defaults for new records (NRI-0021 task 6.1).

Spec «Дата „сейчас“ — дефолт новых записей» (current-date): opening the
creation card of an entity or the creation dialog of an event starts the date
bounds with the game's «now», not with the real today; the value is injected
by the facade from the widget VM (design Д5).  A «now» edit influences only
the defaults — the dates of already-saved records stay as they were (scenario
«Правка „сейчас“ не трогает сохранённые даты»): the edit flows populate() the
saved bounds over the seeded default and a later applyNow never rewrites
them.  The system-today fallback stays for sheets built without a game (the
same posture the age lines of tasks 4.3/4.4 keep).
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.domain.game_calendar import (
    MonthDay,
    current_calendar,
    reset_current_calendar,
    set_current_calendar,
)
from app.presentation.viewmodels.now_date_view_model import NowDateViewModel
from app.presentation.views.entity_card_dialog import EntityCardDialog
from app.presentation.views.event_dialog import EventDialog


@pytest.fixture(autouse=True)
def _standard_calendar():
    """The expected captions below are Gregorian — pin the preset calendar
    and hand back whatever the previous test left active."""
    saved = current_calendar()
    reset_current_calendar()
    yield
    set_current_calendar(saved)


def _now_vm(coord: MonthDay, is_bc: bool = False) -> NowDateViewModel:
    return NowDateViewModel(coord, is_bc)


# ── Card of a new entity ───────────────────────────────────────────────────


class TestCardDefaults:
    def test_new_card_opens_at_now(self, qtbot):
        # spec «Новая карточка открывается на „сейчас“»: both date bounds
        # carry the served game date, not the system today
        dialog = EntityCardDialog(
            None, "character", now_vm=_now_vm(MonthDay(2091, 5, 1))
        )
        qtbot.addWidget(dialog)
        assert dialog.vm._start_date == MonthDay(2091, 5, 1)
        assert dialog.vm.startIso == "2091-05-01"
        assert dialog.vm.startDisplay == "01 Май 2091"
        assert dialog.vm.endIso == "2091-05-01"
        assert dialog.vm.startBc is False and dialog.vm.endBc is False

    def test_bc_now_seeds_the_era_too(self, qtbot):
        # «сейчас» lives before our era — the default carries the era flag,
        # the field shows the same «г. до н.э.» caption as the widget
        dialog = EntityCardDialog(
            None, "item", now_vm=_now_vm(MonthDay(44, 3, 5), is_bc=True)
        )
        qtbot.addWidget(dialog)
        assert dialog.vm.startBc is True and dialog.vm.endBc is True
        assert dialog.vm.startDisplay == "05 Март 44 г. до н.э."

    def test_without_a_game_the_today_fallback_stays(self, qtbot):
        dialog = EntityCardDialog(None, "character")
        qtbot.addWidget(dialog)
        assert dialog.vm.startIso == date.today().isoformat()

    def test_saved_card_keeps_its_dates_across_now_edits(self, qtbot):
        # scenario «Правка „сейчас“ не трогает сохранённые даты»: an edit
        # card gets its stored bounds, a later «now» edit never rewrites them
        now_vm = _now_vm(MonthDay(2091, 5, 1))
        dialog = EntityCardDialog(None, "character", now_vm=now_vm)
        qtbot.addWidget(dialog)
        dialog.populate(
            SimpleNamespace(
                id=7,
                name="Герой",
                rating=3,
                start_date=date(1999, 1, 2),
                end_date=None,
                description=None,
            )
        )
        now_vm.applyNow(MonthDay(2100, 12, 31), False)
        assert dialog.vm.startIso == "1999-01-02"
        assert dialog.vm.endIso == "2091-05-01"  # open end — untouched default
        assert dialog.vm.startDisplay == "02 Январь 1999"


# ── Dialog of a new event ──────────────────────────────────────────────────


class TestEventDialogDefaults:
    def test_new_dialog_opens_at_now(self, qtbot):
        dialog = EventDialog(None, now_vm=_now_vm(MonthDay(2090, 5, 1)))
        qtbot.addWidget(dialog)
        assert dialog.vm._start_date == MonthDay(2090, 5, 1)
        assert dialog.vm.startIso == "2090-05-01"
        assert dialog.vm.startDisplay == "01 Май 2090"
        assert dialog.vm.endIso == "2090-05-01"
        assert dialog.vm.startBc is False and dialog.vm.endBc is False

    def test_bc_now_seeds_the_era_too(self, qtbot):
        dialog = EventDialog(
            None, now_vm=_now_vm(MonthDay(44, 3, 5), is_bc=True)
        )
        qtbot.addWidget(dialog)
        assert dialog.vm.startBc is True and dialog.vm.endBc is True
        assert dialog.vm.startDisplay == "05 Март 44 г. до н.э."

    def test_now_hour_is_not_inherited(self, qtbot):
        """NRI-0023 scenario «Час „сейчас“ не наследуется» (spec «Дата
        „сейчас“ — дефолт новых записей»): a «now» at «…, 20:00» seeds the
        new event with the DAY only — the hour and minute lists stay empty,
        the dialog consumes the coordinate half of the served value."""
        dialog = EventDialog(
            None, now_vm=NowDateViewModel(MonthDay(2090, 5, 1), False, 20)
        )
        qtbot.addWidget(dialog)
        assert dialog.vm.startIso == "2090-05-01"
        assert dialog.vm.start_time is None  # «без времени», не 20:00
        assert dialog.vm.selectedHourIndex == 0 and dialog.vm.selectedMinuteIndex == 0

    def test_without_a_game_the_today_fallback_stays(self, qtbot):
        dialog = EventDialog(None)
        qtbot.addWidget(dialog)
        assert dialog.vm.startIso == date.today().isoformat()

    def test_saved_event_keeps_its_dates_across_now_edits(self, qtbot):
        now_vm = _now_vm(MonthDay(2090, 5, 1))
        dialog = EventDialog(None, now_vm=now_vm)
        qtbot.addWidget(dialog)
        dialog.populate(
            SimpleNamespace(
                id=4,
                name="Битва",
                event_type=None,
                start_date=date(1812, 9, 7),
                end_date=date(1812, 9, 9),
                description=None,
                organizations=[],
                characters=[],
                items=[],
                locations=[],
            )
        )
        now_vm.applyNow(MonthDay(2100, 12, 31), False)
        assert dialog.vm.startIso == "1812-09-07"
        assert dialog.vm.endIso == "1812-09-09"
