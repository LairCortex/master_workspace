"""Derived surfaces of the detail panel (NRI-0021 tasks 4.1/4.2).

Spec «Read-only отображение производных величин» + «Прошедшее время от начала
события» + «Смена даты пересчитывает всё»: the summary of a character/item row
carries the «Возраст: <формула>» line (locations and organizations never do),
the event date row gains the « · <формула> назад» / « · через N» /
« · сегодня» tail, and a «now» edit re-renders both without a re-open. All
numbers run through the single rules of tasks 1.2–1.4; here only their
placement and live refresh are pinned — including the spec screen scenario
(the panel row really shows «Возраст: 3 года 2 мес.» offscreen) and the
island-teardown unsubscribe of the now subscription.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

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
from app.presentation.viewmodels.detail_panel_view_model import (
    DetailPanelViewModel,
    build_detail_summary,
)
from app.presentation.viewmodels.now_date_view_model import NowDateViewModel
from app.presentation.views.detail_panel import DetailPanel
from tests.presentation.qml_helpers import island_rows, walk_items


@pytest.fixture(autouse=True)
def _standard_calendar():
    """The age arithmetic dispatches on the active calendar — pin the preset
    (the table of expected words below is Gregorian) and hand back whatever
    the previous test left active."""
    saved = current_calendar()
    reset_current_calendar()
    yield
    set_current_calendar(saved)


def _entity(entity_id=1, name="Герой", start=date(2088, 5, 1), end=None, **extra):
    entity = SimpleNamespace(
        id=entity_id,
        name=name,
        rating=12,
        description=SimpleNamespace(
            characteristics="Скрытная",
            backstory="Основан давно",
        ),
        personality=None,
        tasks=None,
        characters=[],
        organizations=[],
        items=[],
        locations=[],
        image_ref=None,
        start_date=start,
        end_date=end,
    )
    for key, value in extra.items():
        setattr(entity, key, value)
    return entity


def _event(**extra):
    event = SimpleNamespace(
        id=7,
        name="Битва",
        start_date=date(2090, 5, 1),
        end_date=None,
        organizations=[],
        characters=[],
        items=[],
        locations=[],
    )
    for key, value in extra.items():
        setattr(event, key, value)
    return event


class TestSummaryAgeLine:
    """Task 4.1 — «Возраст: <формула>» in build_detail_summary, all types."""

    def test_alive_character_ages_to_now_as_first_line(self):
        summary = build_detail_summary(
            _entity(start=date(2088, 5, 1)), "character", now=(MonthDay(2091, 7, 1), False)
        )
        assert summary.startswith("<b>Возраст:</b> 3 года 2 мес.")
        # the pre-existing lines keep their place below the new one
        assert "<b>Рейтинг:</b> 12/20" in summary
        assert "<b>Хар-ки:</b> Скрытная" in summary

    def test_closed_item_ages_to_its_end(self):
        # spec «Сущность с закрытым концом»: 2080 → 2090, «сейчас» 2095
        entity = _entity(start=date(2080, 5, 1), end=date(2090, 5, 1))
        summary = build_detail_summary(entity, "item", now=(MonthDay(2095, 1, 1), False))
        assert "<b>Возраст:</b> 10 лет" in summary

    def test_future_start_reads_forward(self):
        # spec «Ещё не начавшаяся сущность»
        summary = build_detail_summary(
            _entity(start=date(2091, 4, 1)), "character", now=(MonthDay(2091, 1, 1), False)
        )
        assert "<b>Возраст:</b> через 3 мес." in summary

    def test_days_only(self):
        summary = build_detail_summary(
            _entity(start=date(2091, 1, 1)), "character", now=(MonthDay(2091, 1, 13), False)
        )
        assert "<b>Возраст:</b> 12 дней" in summary

    @pytest.mark.parametrize("entity_type", ("location", "organization"))
    def test_age_free_types_never_carry_the_line(self, entity_type):
        summary = build_detail_summary(
            _entity(start=date(2088, 5, 1)), entity_type, now=(MonthDay(2091, 7, 1), False)
        )
        assert "Возраст" not in summary

    def test_without_now_the_summary_is_the_old_text(self):
        summary = build_detail_summary(_entity(), "character")
        assert "Возраст" not in summary
        assert "<b>Рейтинг:</b> 12/20" in summary

    def test_entity_without_a_start_date_skips_the_line(self):
        summary = build_detail_summary(
            _entity(start=None), "character", now=(MonthDay(2091, 7, 1), False)
        )
        assert "Возраст" not in summary

    def test_era_flags_are_carried_into_the_age_rule(self):
        # 31 дек. 1 г. до н.э. → 1 янв. 1 г. н.э. — граница эр без нулевого года
        entity = _entity(start=date(1, 12, 31), start_bc=True)
        summary = build_detail_summary(entity, "character", now=(MonthDay(1, 1, 1), False))
        assert "<b>Возраст:</b> 1 день" in summary

    def test_bc_now_and_bc_start_stay_in_the_same_era(self):
        entity = _entity(start=date(44, 3, 5), start_bc=True)
        summary = build_detail_summary(entity, "character", now=(MonthDay(44, 3, 6), True))
        assert "<b>Возраст:</b> 1 день" in summary


class TestDateRowSuffix:
    """Task 4.2 — the event-time tail of the panel's date row."""

    def _vm(self, now=MonthDay(2090, 5, 1), is_bc=False):
        return DetailPanelViewModel(
            now_vm=None if now is None else NowDateViewModel(now, is_bc)
        )

    def test_open_event_counts_from_start_to_now(self):
        # spec scenario: «01 Май 2088 — ∞ · 2 года 3 мес. назад» (shifted to
        # the numbers of this fixture: 01 Фев 2088 → 01 Май 2090 = 2 г. 3 мес.)
        vm = self._vm()
        vm.show_event(_event(start_date=date(2088, 2, 1)))
        assert vm.dateText == "01 Февраль 2088 — ∞ · 2 года 3 мес. назад"

    def test_closed_event_counts_from_start_not_from_end(self):
        # spec «Завершённое событие считается от начала»: started 4 years ago
        vm = self._vm()
        vm.show_event(
            _event(start_date=date(2086, 5, 1), end_date=date(2089, 5, 1))
        )
        assert vm.dateText == "01 Май 2086 — 01 Май 2089 · 4 года назад"

    def test_future_event_reads_through_the_ahead_prefix(self):
        vm = self._vm()
        vm.show_event(_event(start_date=date(2090, 5, 6)))
        assert vm.dateText == "06 Май 2090 — ∞ · через 5 дней"

    def test_today_event_reads_segodnya(self):
        vm = self._vm()
        vm.show_event(_event(start_date=date(2090, 5, 1)))
        assert vm.dateText == "01 Май 2090 — ∞ · сегодня"

    def test_bc_pair_suffix_stays_in_the_same_era(self):
        vm = self._vm(now=MonthDay(44, 3, 6), is_bc=True)
        vm.show_event(_event(start_date=date(44, 3, 1), start_bc=True))
        assert vm.dateText == "01 Март 44 г. до н.э. — ∞ · 5 дней назад"

    def test_panel_without_now_keeps_the_plain_date_row(self):
        vm = DetailPanelViewModel()
        vm.show_event(_event(start_date=date(2088, 2, 1)))
        assert vm.dateText == "01 Февраль 2088 — ∞"

    def test_event_without_a_start_date_gets_no_suffix(self):
        vm = self._vm()
        vm.show_event(_event(start_date=None))
        assert vm.dateText == "? — ∞"

    def test_rows_are_built_with_the_now_value(self):
        vm = self._vm()
        vm.show_event(_event(characters=[_entity(name="Герой")]))
        model = vm.characters
        summary = model.data(model.index(0, 0), type(model).SummaryRole)
        # 2088-05-01 → 2090-05-01 = ровно 2 года
        assert "<b>Возраст:</b> 2 года" in summary


class TestLiveRecompute:
    """Spec «Смена даты пересчитывает всё» for the panel."""

    def test_now_edit_re_renders_date_row_and_summaries(self):
        now_vm = NowDateViewModel(MonthDay(2090, 5, 1))
        vm = DetailPanelViewModel(now_vm=now_vm)
        vm.show_event(
            _event(
                start_date=date(2088, 5, 1),
                characters=[_entity(start=date(2088, 5, 1))],
            )
        )
        assert vm.dateText.endswith("· 2 года назад")
        model = vm.characters
        assert "<b>Возраст:</b> 2 года" in model.data(
            model.index(0, 0), type(model).SummaryRole
        )

        now_vm.applyNow(MonthDay(2091, 5, 1), False)

        assert vm.dateText == "01 Май 2088 — ∞ · 3 года назад"
        assert "<b>Возраст:</b> 3 года" in model.data(
            model.index(0, 0), type(model).SummaryRole
        )

    def test_hour_only_edit_leaves_age_and_duration_as_they_were(self):
        """NRI-0023 task 9.1 (spec «Час меняет только подпись»): the same
        day with the «now» hour set keeps the duration suffix («сегодня»)
        and the entity «Возраст» summary word for word — both are computed
        from the coordinate alone, and an hour-only edit does not even move
        the ``nowChanged`` broadcast that would re-render them."""
        now_vm = NowDateViewModel(MonthDay(2090, 5, 1))
        vm = DetailPanelViewModel(now_vm=now_vm)
        vm.show_event(
            _event(
                start_date=date(2090, 5, 1),  # starts «сегодня»
                characters=[_entity(start=date(2088, 5, 1))],
            )
        )
        date_text = vm.dateText
        model = vm.characters
        summary_role = type(model).SummaryRole
        summary = model.data(model.index(0, 0), summary_role)
        assert date_text.endswith("· сегодня")
        assert "<b>Возраст:</b> 2 года" in summary

        now_vm.applyNow(MonthDay(2090, 5, 1), False, 20)  # только час

        assert vm.dateText == date_text
        assert model.data(model.index(0, 0), summary_role) == summary

    def test_now_edit_after_clear_is_a_noop(self):
        now_vm = NowDateViewModel(MonthDay(2090, 5, 1))
        vm = DetailPanelViewModel(now_vm=now_vm)
        vm.show_event(_event())
        vm.clear()

        now_vm.applyNow(MonthDay(2095, 5, 1), False)  # must not raise or repaint

        assert vm.dateText == ""
        assert [model.rowCount() for model in vm.models] == [0, 0, 0, 0]

    def test_detach_stops_the_subscription_and_is_idempotent(self):
        now_vm = NowDateViewModel(MonthDay(2090, 5, 1))
        vm = DetailPanelViewModel(now_vm=now_vm)
        vm.show_event(_event(start_date=date(2088, 5, 1)))
        vm.detach_now_listener()
        vm.detach_now_listener()  # idempotent teardown

        now_vm.applyNow(MonthDay(2095, 5, 1), False)

        assert vm.dateText == "01 Май 2088 — ∞ · 2 года назад"  # frozen
        assert vm._now_vm is None

    def test_panel_built_without_now_detaches_without_a_vm(self):
        vm = DetailPanelViewModel()
        vm.detach_now_listener()  # the None branch of the same teardown


class TestOffCalendarNow:
    """The Д1 seeded-today «now» on a custom-calendar game can sit outside
    that calendar (the real today coerces numbers the calendar does not
    name).  A duration the calendar refuses never breaks the derived display:
    the age line and the date-row suffix simply stay absent (the same absence
    posture as Д1's damaged-value rule)."""

    def _eight_month_calendar(self):
        # eight months of 21 days: month 9 does not exist here, so the
        # seeded MonthDay(2026, 9, 26) is the out-of-calendar «now» of a
        # custom game (the shape the Д1 seed produces on wizard acceptance)
        set_current_calendar(
            CustomCalendar(
                CalendarSpec(
                    months=tuple(
                        MonthSpec(f"Месяц-{n}", 21) for n in range(1, 9)
                    ),
                    week_names=tuple("АБВГДЕ"),
                )
            )
        )

    def test_summary_hides_the_age_line_but_keeps_the_rest(self):
        self._eight_month_calendar()
        summary = build_detail_summary(
            _entity(start=date(2088, 2, 1)), "character",
            now=(MonthDay(2026, 9, 26), False),
        )
        assert "Возраст" not in summary
        assert "<b>Рейтинг:</b> 12/20" in summary

    def test_date_row_stays_the_plain_range(self):
        self._eight_month_calendar()
        vm = DetailPanelViewModel(
            now_vm=NowDateViewModel(MonthDay(2026, 9, 26), False)
        )
        vm.show_event(_event(start_date=date(2088, 2, 1)))
        assert vm.dateText == "01 Месяц-2 2088 — ∞"

    def test_rows_build_without_the_age_line(self):
        self._eight_month_calendar()
        vm = DetailPanelViewModel(
            now_vm=NowDateViewModel(MonthDay(2026, 9, 26), False)
        )
        vm.show_event(
            _event(
                start_date=date(2088, 2, 1),
                characters=[_entity(start=date(2088, 2, 1))],
            )
        )
        model = vm.characters
        summary = model.data(model.index(0, 0), type(model).SummaryRole)
        assert "Возраст" not in summary


class TestPanelScreenScenario:
    """Spec scenario «Возраст в сводке» offscreen: the character row really
    paints the line, and the island teardown unsubscribes the now listener."""

    def _panel(self, qtbot):
        now_vm = NowDateViewModel(MonthDay(2091, 7, 1))
        panel = DetailPanel(SimpleNamespace(), now_date_vm=now_vm)
        qtbot.addWidget(panel)
        panel.show_event(
            _event(
                start_date=date(2088, 5, 1),
                characters=[_entity(name="Герой", start=date(2088, 5, 1))],
            )
        )
        panel.resize(500, 500)
        # «Персонажи» is tab 1; the switch rides BEFORE the first render pass
        # (delegates materialize on the render of the visible tab only —
        # the island_rows convention).
        panel.quick.rootObject().setProperty("currentTab", 1)
        panel.show()
        qtbot.wait(20)
        return panel, now_vm

    def test_character_row_shows_age_line_and_date_row_shows_suffix(self, qtbot):
        panel, _ = self._panel(qtbot)
        rows = island_rows(panel.quick, "detailEntityRow")
        assert len(rows) == 1
        summaries = [
            item.property("text")
            for item in walk_items(rows[0])
            if item.objectName() == "detailEntitySummary"
        ]
        assert len(summaries) == 1
        assert "Возраст:" in summaries[0]
        assert "3 года 2 мес." in summaries[0]
        # the date row of the header paints the same suffix live (spec
        # «Суффикс строки дат панели» lives in this scenario too)
        date_row = [
            item
            for item in walk_items(panel.quick.rootObject())
            if item.objectName() == "detailDate"
        ][0]
        assert date_row.property("text").endswith("· 3 года 2 мес. назад")

    def test_release_island_unsubscribes_the_now_vm(self, qtbot):
        panel, now_vm = self._panel(qtbot)
        assert panel.vm._now_vm is now_vm

        panel.close()
        qtbot.waitUntil(lambda: panel.vm._now_vm is None, timeout=2000)

        # after the deferred release a «now» edit must not touch the panel
        now_vm.applyNow(MonthDay(2095, 7, 1), False)
        assert panel.vm.dateText.endswith("· 3 года 2 мес. назад")
