"""Read-only derived lines in the entity card and the event dialog (NRI-0021
tasks 4.3/4.4).

Spec «Read-only отображение производных величин»: the card of a character or
item shows the plain-text row «Возраст: <формула>» under the date fields and
the event dialog shows «С начала: <формула>».  Neither row is an input and
neither enters the save result (scenario «Строка карточки не редактируется и
не сохраняется» — pinned here by the equality of the two frozen results built
with and without a game «now»); locations and organizations never get the row
(scenario «Локация без возраста»); an open card/dialog follows every «now»
edit without re-opening (scenario «Открытая карточка следит за „сейчас“»),
and the subscription leaves with the window (design Д2 teardown — «после
закрытия карточки подписки нет»).  The formulas themselves are pinned by the
single-rule tests of tasks 1.2–1.4; here only placement, read-only-ness,
result purity and the subscription lifecycle are checked.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.domain.game_calendar import (
    CalendarSpec,
    CustomCalendar,
    MonthDay,
    MonthSpec,
    current_calendar,
    reset_current_calendar,
    set_current_calendar,
)
from app.presentation.viewmodels.now_date_view_model import NowDateViewModel
from app.presentation.views.entity_card_dialog import EntityCardDialog
from app.presentation.views.event_dialog import EventDialog
from tests.presentation.qml_helpers import find_item


@pytest.fixture(autouse=True)
def _standard_calendar():
    """The age arithmetic dispatches on the active calendar — pin the preset
    (all expected words below are Gregorian) and hand back whatever the
    previous test left active."""
    saved = current_calendar()
    reset_current_calendar()
    yield
    set_current_calendar(saved)


def _now_vm(coord: MonthDay, is_bc: bool = False) -> NowDateViewModel:
    return NowDateViewModel(coord, is_bc)


# ── Task 4.3 — the card's read-only age line ──────────────────────────────


class TestCardAgeVm:
    def test_line_absent_while_no_now_is_mirrored(self, qtbot):
        dialog = EntityCardDialog(None, "character")
        qtbot.addWidget(dialog)
        assert dialog.vm.ageText == ""

    @pytest.mark.parametrize("entity_type", ("location", "organization"))
    def test_age_free_types_never_carry_the_line(self, qtbot, entity_type):
        dialog = EntityCardDialog(
            None, entity_type, now_vm=_now_vm(MonthDay(2091, 5, 1))
        )
        qtbot.addWidget(dialog)
        dialog.vm.set_dates(start=date(2088, 5, 1))
        assert dialog.vm.ageText == ""

    @pytest.mark.parametrize("entity_type", ("character", "item"))
    def test_age_types_count_start_to_now(self, qtbot, entity_type):
        # spec «Живущая сущность»: the plain-text row carries the one formula
        # (an open-ended card — «Бессрочно», so the count really runs to «now»)
        dialog = EntityCardDialog(
            None, entity_type, now_vm=_now_vm(MonthDay(2091, 5, 1))
        )
        qtbot.addWidget(dialog)
        dialog.vm.set_dates(start=date(2088, 5, 1))
        dialog.vm.set_no_end(True)
        assert dialog.vm.ageText == "Возраст: 3 года"

    def test_end_earlier_than_now_closes_the_count(self, qtbot):
        # spec «Сущность с закрытым концом»: 2080 → 2090, «сейчас» 2095
        dialog = EntityCardDialog(
            None, "item", now_vm=_now_vm(MonthDay(2095, 1, 1))
        )
        qtbot.addWidget(dialog)
        dialog.vm.set_dates(start=date(2080, 5, 1), end=date(2090, 5, 1))
        assert dialog.vm.ageText == "Возраст: 10 лет"

    def test_no_end_switch_moves_the_count_target_to_now(self, qtbot):
        # «Бессрочно» re-selects which end the rule counts to (task 4.3)
        dialog = EntityCardDialog(
            None, "item", now_vm=_now_vm(MonthDay(2095, 5, 1))
        )
        qtbot.addWidget(dialog)
        dialog.vm.set_dates(start=date(2088, 5, 1), end=date(2090, 5, 1))
        assert dialog.vm.ageText == "Возраст: 2 года"
        dialog.vm.set_no_end(True)
        assert dialog.vm.ageText == "Возраст: 7 лет"

    def test_start_after_now_reads_forward(self, qtbot):
        # spec «Ещё не начавшаяся сущность»
        dialog = EntityCardDialog(
            None, "character", now_vm=_now_vm(MonthDay(2091, 5, 1))
        )
        qtbot.addWidget(dialog)
        dialog.vm.set_dates(start=date(2091, 8, 1))
        assert dialog.vm.ageText == "Возраст: через 3 мес."

    def test_date_edits_reevaluate_the_line(self, qtbot):
        dialog = EntityCardDialog(
            None, "character", now_vm=_now_vm(MonthDay(2091, 5, 1))
        )
        qtbot.addWidget(dialog)
        with qtbot.waitSignal(dialog.vm.ageTextChanged):
            # end after «now» — the living-entity case of the one rule
            dialog.vm.set_dates(start=date(2088, 5, 1), end=date(2092, 5, 1))
        assert dialog.vm.ageText == "Возраст: 3 года"

    def test_apply_now_reemits_and_recomputes(self, qtbot):
        dialog = EntityCardDialog(None, "character")
        qtbot.addWidget(dialog)
        dialog.vm.set_dates(start=date(2088, 5, 1), end=date(2092, 5, 1))
        with qtbot.waitSignal(dialog.vm.ageTextChanged):
            dialog.vm.applyNow(MonthDay(2091, 5, 1), False)
        assert dialog.vm.ageText == "Возраст: 3 года"


class TestCardIslandRow:
    """QML/QAccessible face: the row is a plain named Text bound to the VM."""

    def test_age_row_is_plain_named_text_bound_to_the_vm(self, qtbot):
        dialog = EntityCardDialog(
            None, "character", now_vm=_now_vm(MonthDay(2091, 5, 1))
        )
        qtbot.addWidget(dialog)
        dialog.vm.set_dates(start=date(2088, 5, 1))
        dialog.vm.set_no_end(True)
        row = find_item(dialog.quick, "entityAgeText")
        assert row.metaObject().className() == "QQuickText"  # text, never an input
        assert row.property("text") == "Возраст: 3 года"
        assert row.property("text") == dialog.vm.ageText
        assert row.property("visible") is True

    def test_age_free_card_hides_the_row(self, qtbot):
        dialog = EntityCardDialog(
            None, "location", now_vm=_now_vm(MonthDay(2091, 5, 1))
        )
        qtbot.addWidget(dialog)
        row = find_item(dialog.quick, "entityAgeText")
        assert row.property("text") == ""
        assert row.property("visible") is False

    def test_save_result_never_carries_the_line(self, qtbot):
        # spec «Строка карточки не редактируется и не сохраняется»: the typed
        # result of a card that shows the line equals the result of the very
        # same card built without a «now» (no key, no value — nothing added).
        with_now = EntityCardDialog(
            None, "character", now_vm=_now_vm(MonthDay(2091, 5, 1))
        )
        qtbot.addWidget(with_now)
        plain = EntityCardDialog(None, "character")
        qtbot.addWidget(plain)
        for dialog in (with_now, plain):
            dialog.vm.name = "Герой"
            dialog.vm.set_dates(start=date(2088, 5, 1), end=date(2090, 5, 1))
        assert with_now.vm.ageText != "" and "Возраст" in with_now.vm.ageText
        result = with_now.build_result()
        assert result == plain.build_result()
        assert "Возраст" not in repr(result)

    def test_open_card_follows_now_and_unsubscribes_on_close(self, qtbot):
        now_vm = _now_vm(MonthDay(2091, 5, 1))
        dialog = EntityCardDialog(None, "character", now_vm=now_vm)
        qtbot.addWidget(dialog)
        dialog.vm.set_dates(start=date(2088, 5, 1))
        dialog.vm.set_no_end(True)
        assert dialog.vm.ageText == "Возраст: 3 года"

        # spec «Открытая карточка следит за „сейчас“» — no re-open needed
        with qtbot.waitSignal(dialog.vm.ageTextChanged):
            now_vm.applyNow(MonthDay(2093, 5, 1), False)
        assert dialog.vm.ageText == "Возраст: 5 лет"

        # «после закрытия карточки подписки нет»: the deferred release that
        # every close route runs also drops the nowChanged subscription
        dialog.show()
        dialog.close()
        qtbot.waitUntil(lambda: dialog._now_vm is None, timeout=2000)
        now_vm.applyNow(MonthDay(2099, 5, 1), False)
        assert dialog.vm.ageText == "Возраст: 5 лет"  # frozen, no receiver


# ── Task 4.4 — the event dialog's «С начала» line ─────────────────────────


class TestEventDialogSinceLine:
    def test_line_absent_while_no_now_is_mirrored(self, qtbot):
        dialog = EventDialog(None)
        qtbot.addWidget(dialog)
        assert dialog.vm.eventText == ""

    def test_open_event_counts_from_start_to_now(self, qtbot):
        # spec «Бессрочное событие»: 2 года 3 мес. от начала
        dialog = EventDialog(None, now_vm=_now_vm(MonthDay(2090, 5, 1)))
        qtbot.addWidget(dialog)
        dialog.vm.set_dates(start=date(2088, 2, 1))
        dialog.vm.set_no_end(True)
        assert dialog.vm.eventText == "С начала: 2 года 3 мес."

    def test_closed_event_counts_from_start_too(self, qtbot):
        # spec «Завершённое событие считается от начала»
        dialog = EventDialog(None, now_vm=_now_vm(MonthDay(2090, 5, 1)))
        qtbot.addWidget(dialog)
        dialog.vm.set_dates(start=date(2086, 5, 1), end=date(2089, 5, 1))
        assert dialog.vm.eventText == "С начала: 4 года"

    def test_future_start_reads_forward(self, qtbot):
        dialog = EventDialog(None, now_vm=_now_vm(MonthDay(2090, 5, 1)))
        qtbot.addWidget(dialog)
        dialog.vm.set_dates(start=date(2090, 5, 6))
        assert dialog.vm.eventText == "С начала: через 5 дней"

    def test_same_day_reads_segodnya(self, qtbot):
        dialog = EventDialog(None, now_vm=_now_vm(MonthDay(2090, 5, 1)))
        qtbot.addWidget(dialog)
        dialog.vm.set_dates(start=date(2090, 5, 1))
        assert dialog.vm.eventText == "С начала: сегодня"

    def test_start_edit_reevaluates_the_line(self, qtbot):
        dialog = EventDialog(None, now_vm=_now_vm(MonthDay(2090, 5, 1)))
        qtbot.addWidget(dialog)
        with qtbot.waitSignal(dialog.vm.eventTextChanged):
            dialog.vm.set_dates(start=date(2086, 5, 1))
        assert dialog.vm.eventText == "С начала: 4 года"

    def test_save_result_never_carries_the_line(self, qtbot):
        # the same result-purity pin as the card's (spec «…не входит в
        # результат сохранения»): with-«now» equals without-«now» byte for byte
        with_now = EventDialog(None, now_vm=_now_vm(MonthDay(2090, 5, 1)))
        qtbot.addWidget(with_now)
        plain = EventDialog(None)
        qtbot.addWidget(plain)
        for dialog in (with_now, plain):
            dialog.vm.name = "Битва"
            dialog.vm.set_dates(start=date(2088, 5, 1))
            dialog.vm.set_no_end(True)
        assert with_now.vm.eventText == "С начала: 2 года"
        result = with_now.build_result()
        assert result == plain.build_result()
        assert "С начала" not in repr(result)


class TestOffCalendarPairHidesTheRows:
    """Д1's seeded-today «now» (and the pre-6.1 today-default start) can carry
    numbers a custom calendar does not contain.  The derived rows are
    display-only: when the calendar refuses the pair they stay absent — the
    binding never raises into the scene (offscreen Qt turns exactly such
    property-lambda errors into a failed test)."""

    def _eight_month_calendar(self):
        set_current_calendar(
            CustomCalendar(
                CalendarSpec(
                    months=tuple(MonthSpec(f"Месяц-{n}", 21) for n in range(1, 9)),
                    week_names=tuple("АБВГДЕ"),
                )
            )
        )

    def test_card_age_row_hides_when_now_is_out_of_calendar(self, qtbot):
        self._eight_month_calendar()
        dialog = EntityCardDialog(
            None, "character", now_vm=_now_vm(MonthDay(2026, 9, 26))
        )
        qtbot.addWidget(dialog)
        dialog.vm.set_dates(start=date(2088, 2, 1), end=date(2088, 3, 1))
        assert dialog.vm.ageText == ""
        row = find_item(dialog.quick, "entityAgeText")
        assert row.property("text") == ""
        assert row.property("visible") is False

    def test_dialog_since_row_hides_when_now_is_out_of_calendar(self, qtbot):
        self._eight_month_calendar()
        dialog = EventDialog(None, now_vm=_now_vm(MonthDay(2026, 9, 26)))
        qtbot.addWidget(dialog)
        dialog.vm.set_dates(start=date(2088, 2, 1))
        assert dialog.vm.eventText == ""
        row = find_item(dialog.quick, "eventSinceText")
        assert row.property("text") == ""
        assert row.property("visible") is False


class TestEventDialogIslandRow:
    def test_since_row_is_plain_named_text_bound_to_the_vm(self, qtbot):
        dialog = EventDialog(None, now_vm=_now_vm(MonthDay(2090, 5, 1)))
        qtbot.addWidget(dialog)
        dialog.vm.set_dates(start=date(2086, 5, 1))
        row = find_item(dialog.quick, "eventSinceText")
        assert row.metaObject().className() == "QQuickText"  # text, never an input
        assert row.property("text") == "С начала: 4 года"
        assert row.property("text") == dialog.vm.eventText
        assert row.property("visible") is True

    def test_open_dialog_follows_now_and_unsubscribes_on_close(self, qtbot):
        now_vm = _now_vm(MonthDay(2090, 5, 1))
        dialog = EventDialog(None, now_vm=now_vm)
        qtbot.addWidget(dialog)
        dialog.vm.set_dates(start=date(2088, 5, 1))
        assert dialog.vm.eventText == "С начала: 2 года"

        # an open dialog re-reads the line on every «now» edit (task 4.4)
        with qtbot.waitSignal(dialog.vm.eventTextChanged):
            now_vm.applyNow(MonthDay(2092, 5, 1), False)
        assert dialog.vm.eventText == "С начала: 4 года"

        # «после закрытия подписки нет»
        dialog.show()
        dialog.close()
        qtbot.waitUntil(lambda: dialog._now_vm is None, timeout=2000)
        now_vm.applyNow(MonthDay(2099, 5, 1), False)
        assert dialog.vm.eventText == "С начала: 4 года"  # frozen, no receiver
