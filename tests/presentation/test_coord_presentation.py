"""Piece C3a task group 5 + C3b popup migration: coordinates in the presentation layer.

Covers the coordinate-aware caption (spec date-eras «Отображение эры», both
scenarios), the ``Iso`` string contract (design D5), the dialog/snapshot
round-trip with an intercalary day under a substituted calendar, the
coordinate pre-fill of the date popups (piece C3b, design D3 — the grid paints
the real coordinate, the record is never rewritten) and the mixed-era window
still judging bounds through the single chronological key. Since C3b the
popups own ``GameCalendarGrid``s, not the old Gregorian ``QCalendarWidget``s.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QRect

from app.domain.entities.description import Description
from app.domain.entities.event import Event
from app.domain.game_calendar import (
    CalendarSpec,
    CustomCalendar,
    IntercalaryDay,
    IntercalarySpec,
    MonthDay,
    MonthSpec,
    current_calendar,
    reset_current_calendar,
    set_current_calendar,
)
from app.infrastructure.calendar_storage import (
    encode_coord,
)
from app.presentation.utils.date_utils import (
    format_game_date,
    iso_or_coord,
)
from app.presentation.viewmodels.detail_panel_view_model import (
    DetailPanelViewModel,
)
from app.presentation.viewmodels.entity_card_island_view_model import (
    EntityCardIslandViewModel,
)
from app.presentation.viewmodels.event_dialog_island_view_model import (
    EventDialogIslandViewModel,
)
from app.presentation.viewmodels.search_viewmodel import SearchViewModel
from app.presentation.viewmodels.world_snapshot_view_model import (
    WorldSnapshotViewModel,
)
from app.presentation.views.calendar_grid import (
    GameCalendarGrid,
    GameCalendarIntercalaryChip,
)
from app.presentation.views.timeline_date_popup import (
    _DateWindowPopup,
    window_chip_text,
)
from app.presentation.views.theme_date_popup import ThemeDatePopup
from app.presentation.views.timeline_rows import build_rows


# ── the substituted custom calendar (same spec the storage tests use) ──────

CUSTOM_SPEC = CalendarSpec(
    months=(
        MonthSpec("Первомес", 30),
        MonthSpec("Второмес", 40),
        MonthSpec("Третьемес", 28),
    ),
    week_names=("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"),
    intercalary=(IntercalarySpec("День Маски", 1),),
)


@pytest.fixture(autouse=True)
def _standard_calendar_around_each_test():
    saved = current_calendar()
    reset_current_calendar()
    yield
    set_current_calendar(saved)


def _custom():
    calendar = CustomCalendar(CUSTOM_SPEC)
    set_current_calendar(calendar)
    return calendar


class _NoSpecCalendar:
    """Protocol implementer without the structural ``spec`` view: exercises
    the defensive caption paths the real calendars never hit."""

    def __init__(self) -> None:
        self._month_names = {1: "Первомес", 2: "Второмес"}

    @property
    def month_names(self):
        return self._month_names

    def month_length(self, year: int, month: int) -> int:
        if month not in (1, 2):
            from app.domain.game_calendar import InvalidGameDateError

            raise InvalidGameDateError(f"month {month} does not exist")
        return 30

    def is_valid(self, coord) -> bool:
        return isinstance(coord, IntercalaryDay) and 0 <= coord.index < 2


# ── 5.1: format_game_date under coordinates ────────────────────────────────


class TestFormatGameDateUnderCoordinates:
    def test_month_day_caption_is_bit_identical(self):
        # Обычный формат и суффикс эры — побитово прежние.
        assert format_game_date(MonthDay(2026, 3, 15)) == "15 Март 2026"
        assert format_game_date(MonthDay(44, 3, 5), is_bc=True) == (
            "05 Март 44 г. до н.э."
        )
        assert format_game_date(date(2026, 3, 15)) == format_game_date(
            MonthDay(2026, 3, 15)
        )

    def test_intercalary_day_caption_has_no_day_number(self):
        _custom()
        assert format_game_date(IntercalaryDay(44, 0)) == "День Маски 44"
        assert format_game_date(IntercalaryDay(44, 0), is_bc=True) == (
            "День Маски 44 г. до н.э."
        )

    def test_open_end_mark_never_carries_an_era(self):
        assert format_game_date(None, "∞", is_bc=True) == "∞"
        assert format_game_date(None, "∞", is_bc=False) == "∞"

    def test_intercalary_without_a_named_rule_captures_as_index(self):
        # Defensive caption, same stance as month_name's numeric fallback.
        _custom()
        assert format_game_date(IntercalaryDay(44, 5)) == "5 44"

    def test_intercalary_under_calendar_without_spec_view(self):
        set_current_calendar(_NoSpecCalendar())
        assert format_game_date(IntercalaryDay(44, 1)) == "1 44"

    def test_custom_month_names_reach_month_day_caption(self):
        _custom()
        assert format_game_date(MonthDay(50, 2, 9), is_bc=True) == (
            "09 Второмес 50 г. до н.э."
        )


class TestIsoOrCoord:
    def test_representable_day_stays_iso(self):
        # Побитово прежняя ISO-строка QML.
        assert iso_or_coord(date(1200, 3, 4)) == "1200-03-04"
        assert iso_or_coord(MonthDay(1200, 3, 4)) == "1200-03-04"

    def test_intercalary_day_becomes_the_codec_string(self):
        assert iso_or_coord(IntercalaryDay(44, 0)) == encode_coord(
            IntercalaryDay(44, 0)
        ) == "I:44:0"

    def test_day_no_real_month_has_becomes_the_codec_string(self):
        # Второмес длиннее любого григорианского месяца — ISO невозможна.
        assert iso_or_coord(MonthDay(50, 2, 40)) == "M:50:2:40"

    def test_year_outside_the_date_range_becomes_the_codec_string(self):
        assert iso_or_coord(MonthDay(0, 1, 1)) == "M:0:1:1"


# ── 5.1: every caption carrier accepts coordinates ─────────────────────────


def _row_event(event_id=1, start=None, end=None, name="Событие", bc=False):
    return SimpleNamespace(
        id=event_id,
        start_date=start,
        end_date=end,
        name=name,
        start_bc=1 if bc else 0,
        end_bc=1 if bc else 0,
    )


class TestCaptionCarriers:
    def test_timeline_row_caption_prints_the_intercalary_name(self):
        _custom()
        rows = build_rows(
            [
                _row_event(
                    start=IntercalaryDay(44, 0),
                    end=MonthDay(40, 2, 10),
                    name="Заговор",
                    bc=True,
                )
            ]
        )
        assert rows[0].caption == (
            "День Маски 44 г. до н.э. — 10 Второмес 40 г. до н.э. · Заговор"
        )

    def test_detail_panel_header_prints_the_intercalary_name(self):
        _custom()
        vm = DetailPanelViewModel()
        vm.show_event(
            _row_event(start=IntercalaryDay(44, 0), end=None, name="Заговор")
        )
        assert vm.dateText == "День Маски 44 — ∞"

    def test_search_row_date_text_prints_the_intercalary_name(self):
        _custom()
        vm = SearchViewModel(search_service=None)
        entity = SimpleNamespace(
            id=3, name="Меч", start_date=IntercalaryDay(44, 0), start_bc=1
        )
        vm.results = {"items": [entity]}
        vm._publish_results()
        result_rows = [r for r in vm._rows if r["kind"] == "result"]
        assert result_rows[0]["dateText"] == "День Маски 44 г. до н.э."

    def test_world_snapshot_rows_and_stats_print_the_intercalary_name(self, qapp):
        _custom()
        vm = WorldSnapshotViewModel()
        event = _row_event(
            start=IntercalaryDay(44, 0), end=MonthDay(44, 2, 1), name="Заговор"
        )
        vm.populate([event], (IntercalaryDay(44, 0), True))
        event_row = vm._sections["events"][0]
        assert "День Маски 44 — 01 Второмес 44  |  Заговор" in event_row[
            "displayText"
        ]
        assert vm.statsText.startswith("Дата: День Маски 44 г. до н.э.")


# ── 5.2: view models carry (GameCoord, is_bc) pairs and Iso strings ────────


class TestDialogViewModelsCarryCoordinates:
    def test_event_dialog_island_round_trip_with_intercalary_day(self, qtbot):
        _custom()
        vm = EventDialogIslandViewModel()
        vm.name = "Заговор"
        vm.characteristicsHost.storage = "Тень"
        vm.set_dates(
            start=IntercalaryDay(44, 0),
            end=MonthDay(44, 2, 1),
            start_bc=True,
            end_bc=True,
        )
        assert vm.startDisplay == "День Маски 44 г. до н.э."
        assert vm.endDisplay == "01 Второмес 44 г. до н.э."
        assert vm.startIso == "I:44:0"
        # 44 г. н.э. 1 Второмес — обычный день, представимый датой: ISO.
        assert vm.endIso == "0044-02-01"
        # «end ≥ start» stays on the single key across the intercalary slot.
        assert vm.valid

    def test_event_dialog_payload_builds_the_domain_event(self, qtbot):
        _custom()
        vm = EventDialogIslandViewModel()
        vm.name = "Заговор Цезаря"
        vm.characteristicsHost.storage = "Иды"
        vm.set_dates(
            start=IntercalaryDay(44, 0),
            end=MonthDay(44, 2, 15),
            start_bc=True,
            end_bc=False,
        )
        # The payload rides the dialog keys verbatim (service **kwargs contract).
        payload = {
            "name": vm.name.strip(),
            "characteristics": vm.characteristicsHost.storage.strip(),
            "backstory": vm.backstoryHost.storage.strip(),
            "start_date": vm._start_date,
            "end_date": vm._end_date,
            "start_bc": vm._start_bc,
            "end_bc": vm._end_bc,
        }
        event = Event(
            name=payload["name"],
            description=Description(
                characteristics=payload["characteristics"],
                backstory=payload["backstory"],
            ),
            start_date=payload["start_date"],
            end_date=payload["end_date"],
            start_bc=payload["start_bc"],
            end_bc=payload["end_bc"],
        )
        assert event.start_date == IntercalaryDay(44, 0)
        assert event.end_date == MonthDay(44, 2, 15)
        assert (event.start_bc, event.end_bc) == (True, False)

    async def test_payload_round_trips_through_the_real_event_service(
        self, async_session, qtbot
    ):
        # Task 5.2 round trip: the dialog's payload dict (verbatim service
        # **kwargs contract) drives the real EventService under a substituted
        # custom calendar — the intercalary start lands in the coordinate
        # storage and reads back as the same coordinate with its era.
        from app.application.services.entity_service import EntityService
        from app.application.services.event_service import EventService
        from app.domain.game_calendar import DateField
        from app.infrastructure.db.models import DescriptionModel
        from app.infrastructure.repositories.base_repository import BaseRepository
        from app.infrastructure.repositories.character_repository import (
            CharacterRepository,
        )
        from app.infrastructure.repositories.event_repository import EventRepository
        from app.infrastructure.repositories.event_type_repository import (
            EventTypeRepository,
        )
        from app.infrastructure.repositories.item_repository import ItemRepository
        from app.infrastructure.repositories.location_repository import (
            LocationRepository,
        )
        from app.infrastructure.repositories.organization_repository import (
            OrganizationRepository,
        )

        _custom()
        vm = EventDialogIslandViewModel()
        vm.name = "Заговор Цезаря"
        vm.characteristicsHost.storage = "Иды"
        vm.set_dates(
            start=IntercalaryDay(44, 0),
            end=MonthDay(44, 2, 15),
            start_bc=True,
            end_bc=False,
        )
        payload = {
            "name": vm.name.strip(),
            "characteristics": vm.characteristicsHost.storage.strip(),
            "backstory": vm.backstoryHost.storage.strip(),
            "start_date": vm._start_date,
            "end_date": vm._end_date,
            "start_bc": vm._start_bc,
            "end_bc": vm._end_bc,
        }
        desc_repo = BaseRepository(async_session, DescriptionModel)
        event_repo = EventRepository(async_session)
        service = EventService(
            event_repo=event_repo,
            description_repo=desc_repo,
            organization_service=EntityService(
                OrganizationRepository(async_session), desc_repo
            ),
            character_service=EntityService(
                CharacterRepository(async_session), desc_repo
            ),
            item_service=EntityService(ItemRepository(async_session), desc_repo),
            location_service=EntityService(
                LocationRepository(async_session), desc_repo
            ),
            event_type_repo=EventTypeRepository(async_session),
        )
        created = await service.create_event(**payload)
        reloaded = await service.get_event(created.id)
        assert event_repo.resolve_coord(reloaded, DateField.START) == (
            IntercalaryDay(44, 0)
        )
        assert event_repo.resolve_coord(reloaded, DateField.END) == MonthDay(
            44, 2, 15
        )
        assert (reloaded.start_bc, reloaded.end_bc) == (True, False)
        # The custom route wrote coordinates, not legacy dates.
        assert reloaded.start_coord == encode_coord(IntercalaryDay(44, 0))

    def test_set_dates_coerces_a_plain_date(self, qtbot):
        vm = EventDialogIslandViewModel()
        vm.set_dates(start=date(1200, 6, 1), end=date(1200, 6, 9))
        assert vm._start_date == MonthDay(1200, 6, 1)
        assert vm._end_date == MonthDay(1200, 6, 9)
        # Iso stays the previous ISO string for standard days (bit-exact).
        assert vm.startIso == "1200-06-01"

    def test_entity_card_island_intercalary_iso_and_display(self, qtbot):
        _custom()
        vm = EntityCardIslandViewModel(
            entity_type="item", field_specs=[], related_configs=[]
        )
        vm.set_dates(start=IntercalaryDay(44, 0), start_bc=True)
        assert vm._start_date == IntercalaryDay(44, 0)
        assert vm.startIso == "I:44:0"
        assert vm.startDisplay == "День Маски 44 г. до н.э."


class TestWorldSnapshotViewModelCarriesCoordinates:
    def test_set_date_accepts_coordinates_and_the_bridge_emits_the_pair(self, qapp):
        calendar = _custom()
        vm = WorldSnapshotViewModel()
        vm.set_date((IntercalaryDay(44, 0), True))
        assert vm._date == IntercalaryDay(44, 0)
        assert vm._date_bc is True
        assert vm.dateIso == "I:44:0"
        assert vm.dateDisplay == "День Маски 44 г. до н.э."
        emitted = []
        vm.snapshotRequested.connect(emitted.append)
        vm.requestShow()
        assert emitted == [(IntercalaryDay(44, 0), True)]
        assert calendar is not None

    def test_set_date_coerces_a_plain_date_to_the_month_day(self, qapp):
        vm = WorldSnapshotViewModel()
        vm.set_date(date(1200, 3, 4))
        assert vm._date == MonthDay(1200, 3, 4)
        assert vm.dateIso == "1200-03-04"  # bit-for-bit the previous string

    def test_delete_of_the_fictional_iso_slot_is_total(self, qapp):
        vm = WorldSnapshotViewModel()
        assert not hasattr(vm, "setDateIso")


# ── 5.2: pre-fill is the grid's own coordinate picture (no substitution) ─────


class TestDateWindowPopupCoordinatePrefill:
    """Since piece C3b (design D3) the range popover seeds its grids with the
    window's real coordinates — an intercalary bound shows its host page with
    the chip marked, an out-of-calendar coordinate (a year outside 1…9999, a
    day the active month does not have) simply leaves its grid un-prefilled,
    and no bound of the stored window is ever rewritten."""

    def test_open_at_paints_intercalary_and_invalid_bounds_without_touching_them(
        self, qtbot
    ):
        _custom()
        popup = _DateWindowPopup()
        qtbot.addWidget(popup)
        current = (
            (IntercalaryDay(44, 0), True),
            (MonthDay(47, 1, 31), False),  # Первомес is 30 days — unpaintable
        )
        popup.open_at(QRect(0, 0, 10, 10), current)
        # The intercalary bound shows its own chip on the host month page…
        assert popup.start_calendar.selection() == IntercalaryDay(44, 0)
        chips = popup.start_calendar.findChildren(GameCalendarIntercalaryChip)
        assert chips[0].selected
        # …the era check boxes mirror the seeded bounds independently…
        assert popup.start_calendar.is_bc() is True
        assert popup.end_calendar.is_bc() is False
        # …and the out-of-calendar bound leaves its grid un-prefilled rather
        # than clamping a number into the picture (spec «Сетка говорит
        # координатами»).
        assert popup.end_calendar.selection() is None
        # …the window itself (the «запись» of the bounds) is unchanged.
        assert current == ((IntercalaryDay(44, 0), True), (MonthDay(47, 1, 31), False))
        assert popup._pending_start is None

    def test_open_at_keeps_plain_date_bounds_and_eras(self, qtbot):
        popup = _DateWindowPopup()
        qtbot.addWidget(popup)
        popup.open_at(
            QRect(0, 0, 10, 10),
            ((MonthDay(500, 1, 1), True), (date(100, 12, 31), False)),
        )
        assert popup.start_calendar.selection() == MonthDay(500, 1, 1)
        assert popup.start_calendar.is_bc() is True
        # A bare date arrives as its equal month-day coordinate.
        assert popup.end_calendar.selection() == MonthDay(100, 12, 31)
        assert popup.end_calendar.is_bc() is False

    def test_open_at_partial_window_pictures_one_bound_only(self, qtbot):
        popup = _DateWindowPopup()
        qtbot.addWidget(popup)
        popup.open_at(QRect(0, 0, 10, 10), (None, (MonthDay(100, 6, 1), True)))
        # An absent bound leaves its grid un-prefilled with the era reset…
        assert popup.start_calendar.selection() is None
        assert popup.start_calendar.is_bc() is False
        # …while the other grid paints its coordinate and era.
        assert popup.end_calendar.selection() == MonthDay(100, 6, 1)
        assert popup.end_calendar.is_bc() is True


class TestDialogPopupCoordinatePrefill:
    """The dialogs hand the popup the coordinate pair they hold; the grid
    paints it, so there is no picture-only clamp and the stored coordinate
    survives the open byte-for-byte."""

    def test_event_dialog_opens_the_popup_at_the_coordinate_pair(self, qtbot, monkeypatch):
        from unittest.mock import MagicMock

        from app.presentation.views.event_dialog import EventDialog

        _custom()
        dialog = EventDialog(MagicMock())
        qtbot.addWidget(dialog)
        dialog.vm.set_dates(start=IntercalaryDay(44, 0), start_bc=True)
        opened: list = []
        monkeypatch.setattr(
            dialog.date_popup,
            "open_at",
            lambda anchor, current: opened.append(current),
        )
        dialog._open_date_popup("start", 1, 2, 3, 4)
        # The pair reaches the popup verbatim — the coordinate, not a picture.
        assert opened == [(IntercalaryDay(44, 0), True)]
        assert dialog.vm._start_date == IntercalaryDay(44, 0)

    def test_entity_card_opens_the_popup_at_the_coordinate_pair(self, qtbot, monkeypatch):
        from unittest.mock import MagicMock

        from app.presentation.views.entity_card_dialog import EntityCardDialog

        _custom()
        dialog = EntityCardDialog(MagicMock(), entity_type="item")
        qtbot.addWidget(dialog)
        dialog.vm.set_dates(end=IntercalaryDay(44, 0), end_bc=True)
        opened: list = []
        monkeypatch.setattr(
            dialog.date_popup,
            "open_at",
            lambda anchor, current: opened.append(current),
        )
        dialog._open_date_popup("end", 1, 2, 3, 4)
        assert opened == [(IntercalaryDay(44, 0), True)]
        assert dialog.vm._end_date == IntercalaryDay(44, 0)

    def test_world_snapshot_opens_the_popup_at_the_coordinate_pair(
        self, qtbot, monkeypatch
    ):
        from app.presentation.views.world_snapshot_widget import WorldSnapshotWidget

        _custom()
        widget = WorldSnapshotWidget()
        qtbot.addWidget(widget)
        widget.vm.set_date((IntercalaryDay(44, 0), True))
        opened: list = []
        monkeypatch.setattr(
            widget.date_popup,
            "open_at",
            lambda anchor, current: opened.append(current),
        )
        widget.vm.requestDatePopup(1, 2, 3, 4)
        # The snapshot's own coordinate reaches the grid un-substituted.
        assert opened == [(IntercalaryDay(44, 0), True)]
        assert widget.vm._date == IntercalaryDay(44, 0)


# ── 5.2: the mixed-era window still rides the single chronological key ─────


class TestMixedEraWindowOnTheSingleKey:
    def test_window_from_an_intercalary_bc_start_to_a_ce_end_filters_and_sorts(self):
        _custom()
        crossing = _row_event(
            event_id=1,
            start=IntercalaryDay(500, 0),
            end=MonthDay(100, 1, 15),
            name="Via BC",
        )
        # era flags per slot: crossing starts BC, ends CE
        crossing.start_bc, crossing.end_bc = 1, 0
        later_ce = _row_event(
            event_id=2, start=MonthDay(200, 1, 1), end=None, name="CE"
        )
        earlier_bc = _row_event(
            event_id=3, start=IntercalaryDay(900, 0), name="Early BC", bc=True
        )
        window = ((IntercalaryDay(500, 0), True), (MonthDay(100, 2, 10), False))
        rows = build_rows([earlier_bc, crossing, later_ce], window)
        # The order is the single chronological key: 900 г. до н.э. (открытое,
        # началось до окна — остается видимым) раньше пересекателя границы эр,
        # а 200 г. н.э. уже за правым краем окна.
        assert [row.event_id for row in rows] == [3, 1]

    def test_window_bounds_are_compared_by_the_shared_key_not_the_numbers(self):
        _custom()
        rows = build_rows(
            [
                _row_event(
                    event_id=1,
                    start=MonthDay(44, 1, 15),
                    end=MonthDay(44, 1, 20),
                    name="Внутри",
                )
            ],
            ((MonthDay(44, 1, 10), False), (MonthDay(44, 1, 18), False)),
        )
        assert [row.event_id for row in rows] == [1]

    def test_chip_caption_prints_intercalary_and_era_bounds(self):
        _custom()
        chip = window_chip_text(
            (IntercalaryDay(500, 0), True), (MonthDay(100, 2, 10), False)
        )
        assert chip == "День Маски 500 г. до н.э. — 10 Второмес 100 ▾"


class TestPopupWidgetsUseTheGameCalendarGrid:
    def test_both_popups_own_game_calendar_grids(self, qtbot):
        """Since piece C3b (design D3) the popups draw game-calendar grids —
        their year spin now spans the whole 1…9999 scale of BOTH eras."""
        single = ThemeDatePopup()
        qtbot.addWidget(single)
        window = _DateWindowPopup()
        qtbot.addWidget(window)
        assert isinstance(single.calendar, GameCalendarGrid)
        assert isinstance(window.start_calendar, GameCalendarGrid)
        assert isinstance(window.end_calendar, GameCalendarGrid)
        assert (
            single.calendar._year_spin.minimum(),
            single.calendar._year_spin.maximum(),
        ) == (1, 9999)
