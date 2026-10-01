from datetime import date
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import QDialog, QListWidget, QMessageBox

from app.domain.game_calendar import (
    CalendarSpec,
    CustomCalendar,
    MonthSpec,
    as_game_coord,
    current_calendar,
    set_current_calendar,
)
from app.domain.time_of_day import TimeOfDay
from app.presentation.dialog_results import EventCreateResult, EventEditResult
from app.presentation.viewmodels.event_dialog_island_view_model import (
    EventDialogIslandViewModel,
)
from app.presentation.views.event_dialog import EventDialog
from tests.presentation.qml_helpers import find_item
from tests.ui.test_theme_grab import make_runtime


def test_save_and_related_section_buttons_carry_their_pass_glyphs(qtbot):
    """Lucide icon pass 2026-09-30: the dialog save chip and the related
    section's link/create/unlink trio gain their glyphs; the captions stay.
    «user-plus» is absent by decision — RelatedSectionState carries no entity
    type, so the component cannot tell a character section from the rest."""
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    assert find_item(dialog.quick, "eventSaveButton").property("iconName") == "save"
    for suffix, icon in (
        ("LinkButton", "link"),
        ("CreateButton", "plus"),
        ("UnlinkButton", "unlink"),
    ):
        button = find_item(dialog.quick, "charactersRelated" + suffix)
        assert button.property("iconName") == icon, suffix
        assert button.property("text") != "", suffix


def test_related_tabs_carry_the_one_map_glyphs(qtbot):
    """Lucide pass 2026-09-30: the four relation tabs gain the registry
    order's glyphs from the one type→icon map, index-aligned with the literal
    captions; the sheet (720 px measured) keeps every caption whole with the
    glyph, so unlike the narrow detail column this consumer wears them."""
    from app.domain import entity_registry
    from app.domain.enums.entity_type import EntityType
    from app.presentation.entity_icons import icon_for
    from tests.presentation.qml_helpers import walk_items

    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    expected = [
        (caption, icon_for(ref.entity_type))
        for caption, ref in zip(
            ("Организации", "Персонажи", "Предметы", "Локации"),
            entity_registry.related_refs(EntityType.EVENT),
        )
    ]
    tabs = sorted(
        (
            item
            for item in walk_items(find_item(dialog.quick, "eventRelatedTabs"))
            if item.metaObject().className().startswith("ThemeTabButton")
        ),
        key=lambda item: item.x(),
    )
    assert len(tabs) == 4
    for tab, (caption, glyph) in zip(tabs, expected):
        assert tab.property("text") == caption
        assert tab.property("iconName") == glyph
        glyph_items = [i for i in walk_items(tab) if i.objectName() == "themeTabIcon"]
        assert len(glyph_items) == 1 and glyph_items[0].property("visible") is True


def test_bc_era_facets_and_the_suffix_reach_the_qml_date_field(qtbot):
    """Task 4.1: the viewmodel exposes ready ``startBc``/``endBc`` facets and
    pre-built display strings — the island's ThemeDateField paints the
    «до н.э.» suffix without computing any era in QML."""
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    dialog.vm.set_dates(start=date(44, 3, 5), start_bc=True)
    assert dialog.vm.startBc is True
    assert dialog.vm.endBc is False
    assert dialog.vm.startDisplay.endswith("44 г. до н.э.")
    start_field = find_item(dialog.quick, "eventStartDateField")
    assert start_field.property("display") == dialog.vm.startDisplay
    assert start_field.property("display").endswith("44 г. до н.э.")
    assert start_field.property("isoDate") == "0044-03-05"
    # nri-0017 1.1: the VM's worst-form caption arrives as the field's
    # width floor (the field itself computes and enforces it from there).
    assert (
        start_field.property("worstCaseText") == dialog.vm.worstCaseDisplay
    )


def test_island_vm_validity_and_save_request(qtbot):
    vm = EventDialogIslandViewModel()
    vm.name = "Event"
    vm.characteristicsHost.storage = " text "
    vm.set_dates(date(1200, 2, 1), date(1200, 1, 1))
    assert not vm.valid
    vm.set_no_end(True)
    assert vm.valid
    vm.set_save_locked(True)
    assert not vm.valid
    vm.set_save_locked(False)
    with qtbot.waitSignal(vm.saveRequested):
        vm.requestSave()


def test_mention_and_ai_proxies_keep_storage_contract(qtbot):
    vm = EventDialogIslandViewModel()
    marker = "@[Hero](character:7)"
    vm.characteristicsHost.storage = marker
    assert vm.characteristicsEdit.getContent() == marker
    assert vm.characteristicsAi.current_text == marker
    vm.characteristicsAi.update_llm_state("ready", True)
    with qtbot.waitSignal(vm.characteristicsAi.generate_requested) as signal:
        vm.characteristicsAi.requestGenerate()
    assert signal.args == ["event", "characteristics", "Характеристики", marker]
    vm.characteristicsAi.set_result_text("new")
    assert vm.characteristicsHost.storage == "new"


def test_related_state_unlinks_selected_and_requests_actions(qtbot):
    vm = EventDialogIslandViewModel()
    section = vm.organizations
    section.set_entities([SimpleNamespace(id=1, name="Guild")])
    with qtbot.waitSignal(section.createRequested):
        section.requestCreate()
    with qtbot.waitSignal(section.linkRequested):
        section.requestLink()
    section.select(0)
    section.unlinkSelected()
    assert section.rows == []


def test_event_root_object_contract_and_qml_type_path(qtbot):
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    assert dialog.minimumWidth() >= 700
    assert dialog.minimumHeight() >= 620
    for name in (
        "eventNameField",
        "eventStartDateField",
        "eventStartHourCombo",
        "eventStartMinuteCombo",
        "eventEndDateField",
        "eventNoEndCheck",
        "eventTypeCombo",
        "eventParentCombo",
        "eventTypeSwatch",
        "eventCharacteristicsField",
        "eventBackstoryField",
        "organizationsRelatedSection",
        "charactersRelatedSection",
        "itemsRelatedSection",
        "locationsRelatedSection",
        "eventNameAiButton",
        "eventCharacteristicsAiButton",
        "eventBackstoryAiButton",
        "eventEntityAiButton",
        "eventSaveButton",
        "eventCancelButton",
    ):
        assert find_item(dialog.quick, name) is not None
    assert dialog._root.property("typeSelectorMode") == "qml"
    assert dialog._root.property("defaultButton") is not None


def test_save_finishes_only_after_wiring_result(qtbot):
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    dialog.vm.name = "Event"
    dialog.vm.characteristicsHost.storage = "Description"
    dialog.show()
    with qtbot.waitSignal(dialog.saved):
        dialog.vm.requestSave()
    assert dialog.isVisible()
    assert dialog._saving
    dialog.finish_saving(False)
    assert dialog.isVisible()
    dialog.vm.requestSave()
    dialog.finish_saving(True)
    assert not dialog.isVisible()


def test_saving_blocks_escape_close_and_cancel(qtbot):
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._saving = True
    dialog.vm.set_saving(True)
    dialog.keyPressEvent(
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    )
    dialog.closeEvent(QCloseEvent())
    dialog._on_cancel_clicked()
    assert dialog.isVisible()


def test_related_picker_is_native_multiselect_and_empty_is_noop(qtbot, monkeypatch):
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    first = SimpleNamespace(id=1, name="One")
    second = SimpleNamespace(id=2, name="Two")
    dialog.set_available_entities("characters", [first, second])
    calls = []

    def accept_all(picker):
        calls.append(picker)
        items = picker.findChild(QListWidget)
        assert items.selectionMode() == QListWidget.SelectionMode.MultiSelection
        items.selectAll()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", accept_all)
    dialog._open_related_picker("characters", "Персонажи")
    assert dialog.vm.characters.get_current_ids() == [1, 2]
    dialog._open_related_picker("characters", "Персонажи")
    assert len(calls) == 1


def test_live_retheme_keeps_input_and_selected_type(qtbot, tmp_path):
    runtime = make_runtime(tmp_path, "dark")
    dialog = EventDialog(None, theme=runtime)
    qtbot.addWidget(dialog)
    event_type = SimpleNamespace(id=7, name="Слух", color_index=3)
    dialog.set_event_types([event_type], current_type_id=7)
    dialog.vm.name = "Не терять"
    dialog.vm.characteristicsHost.storage = "Текст"
    root = dialog.quick.rootObject()
    assert runtime.toggle()
    assert root is dialog.quick.rootObject()
    assert dialog.vm.name == "Не терять"
    assert dialog.vm.characteristicsHost.storage == "Текст"
    assert dialog.vm.selected_type_id == 7


def test_proxy_guard_branches_and_vm_request_slots(qtbot, monkeypatch):
    vm = EventDialogIslandViewModel()
    messages = []
    monkeypatch.setattr(
        QMessageBox, "information",
        lambda *args: messages.append(args) or QMessageBox.StandardButton.Ok,
    )
    vm.characteristicsEdit.show_mention_results([])
    ai = vm.nameAi
    ai.set_generating(True)
    ai.requestGenerate()
    ai.set_generating(False)
    ai.click()
    ai.update_llm_state("ready", False)
    ai.requestGenerate()
    assert len(messages) == 2
    assert ai.isEnabled()

    entity = vm.entityAi
    entity.click()
    entity.update_llm_state("ready", False)
    entity.requestGenerate()
    entity.set_single_in_flight(True)
    entity.requestGenerate()
    entity.set_single_in_flight(False)
    entity.update_llm_state("ready", True)
    with qtbot.waitSignal(entity.batch_requested):
        entity.requestGenerate()
    entity.set_wave_running(True)
    assert entity.isCancelling is True  # A4: the QML face prints «circle-stop»
    assert ai.isCancelling is False     # a field proxy never answers the stop face
    with qtbot.waitSignal(entity.batch_cancel_requested):
        entity.click()

    with qtbot.waitSignal(vm.datePopupRequested):
        vm.requestDatePopup("start", 1, 2, 3, 4)
    with qtbot.waitSignal(vm.cancelRequested):
        vm.requestCancel()
    vm.setNoEnd(True)
    vm.set_save_locked(False)
    vm.set_saving(False)


def test_facade_compatibility_ducks_and_date_routes(qtbot, monkeypatch):
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    event_type = SimpleNamespace(id=3, name="Слух", color_index=3)
    dialog.set_event_types([event_type])
    assert dialog.type_combo.itemData(1, Qt.ItemDataRole.DecorationRole)
    assert dialog.type_combo.findData(None) == 0
    assert dialog.type_combo.findData(3) == 1
    assert dialog.type_combo.findData(99) == -1
    assert dialog.type_combo.findText("missing") == -1

    # The coordinate round trip rides the ViewModel directly (piece C3b).
    dialog.vm.set_dates(start=dialog.vm._start_date, end=dialog.vm._end_date)
    assert dialog.start_date_input.isVisible()
    assert not dialog.start_date_input.isHidden()
    dialog.no_end_date_cb.setChecked(True)
    assert dialog.no_end_date_cb.isChecked()

    entity = SimpleNamespace(id=8, name="Eight")
    dialog.char_tab.set_available([entity])
    dialog.char_tab.set_entities([entity])
    assert dialog.char_tab.list_widget.count() == 1
    item = dialog.char_tab.list_widget.item(0)
    assert item.text() == "Eight"
    assert item.data(0) is None
    dialog.char_tab.list_widget.setCurrentRow(0)
    assert dialog.char_tab.list_widget.currentRow() == 0
    dialog.char_tab.add_entity(entity)
    assert dialog.char_tab.get_current_ids() == [8]
    assert not dialog.tabs.isHidden()

    opened = []
    monkeypatch.setattr(
        dialog.date_popup, "open_at",
        lambda anchor, current: opened.append((anchor, current)),
    )
    dialog._open_date_popup("start", 1, 2, 3, 4)
    dialog._open_date_popup("end", 1, 2, 3, 4)
    assert len(opened) == 2
    dialog._date_target = "start"
    dialog._set_selected_date(date(1201, 1, 1))
    dialog._date_target = "end"
    dialog._set_selected_date(date(1201, 2, 1))
    dialog._update_validity()
    dialog._restyle_type_icons()
    dialog._saving = True
    dialog._on_save()
    dialog._saving = False
    dialog._release_island()


# ── NRI-0023 task 6.1 — the «Создать подсобытие» prefill ─────────────────────


def _parent_event(**overrides):
    parent = SimpleNamespace(id=7, name="Поход", start_date=date(1200, 9, 12),
                             start_bc=False)
    return SimpleNamespace(**{**vars(parent), **overrides})


def test_prefill_parent_lands_parent_and_start_date(qtbot):
    """Spec «Родитель и дата подставлены»: the parent id rides the island
    ViewModel (the one slot task 7.1's combo will bind to), the start date is
    the parent's one; the start TIME stays empty — nothing else is touched."""
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    before_end = dialog.vm._end_date

    dialog.prefill_parent(_parent_event())

    assert dialog.vm.parent_id == 7
    assert dialog.vm._start_date == as_game_coord(date(1200, 9, 12))
    assert dialog.vm.startBc is False
    assert dialog.vm._end_date == before_end  # the create default stays put


def test_prefill_parent_carries_the_era_of_the_parents_start(qtbot):
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)

    dialog.prefill_parent(_parent_event(start_date=date(44, 3, 15), start_bc=True))

    assert dialog.vm._start_date == as_game_coord(date(44, 3, 15))
    assert dialog.vm.startBc is True


def test_prefilled_parent_rides_the_create_result(qtbot):
    """The frozen save contract carries the link to the connector (which
    feeds it to the service guard); a plain create stays parentless."""
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    dialog.prefill_parent(_parent_event())
    dialog.vm.name = "Разведка"
    dialog.vm.characteristicsHost.storage = "Вышли на рассвете"

    result = dialog.build_result()

    assert isinstance(result, EventCreateResult)
    assert result.parent_id == 7
    assert result.start_date == as_game_coord(date(1200, 9, 12))

    plain = EventDialog(None)
    qtbot.addWidget(plain)
    plain.vm.name = "Само по себе"
    plain.vm.characteristicsHost.storage = "Без родителя"
    assert plain.build_result().parent_id is None


def test_edit_result_carries_the_stored_parent(qtbot):
    """Task 7.1 retired the task-6.1 placeholder: populate now prefills the
    «Родительское событие» field from the stored link, so an untouched edit
    re-writes the parent it loaded (the combo is the connector's source)."""
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    stored = SimpleNamespace(
        id=9, name="Поход", parent_id=7,
        start_date=date(1200, 9, 12), end_date=None,
        start_bc=False, end_bc=False, event_type=None, description=None,
        organizations=[], characters=[], items=[], locations=[],
    )

    dialog.populate(stored)
    dialog.vm.name = "Правка"
    result = dialog.build_result()

    assert isinstance(result, EventEditResult)
    assert result.event_id == 9
    assert result.parent_id == 7


def test_island_view_model_parent_slot_is_stateful(qtbot):
    """The VM slot itself: writes re-broadcast stateChanged, a rewrite of the
    same id (and the None-clear round trip) stay honest."""
    vm = EventDialogIslandViewModel()
    assert vm.parent_id is None
    with qtbot.waitSignal(vm.stateChanged):
        vm.parent_id = 7
    assert vm.parent_id == 7
    vm.parent_id = 7  # same value — no second emit required by the contract
    vm.parent_id = None
    assert vm.parent_id is None


# ── NRI-0023 task 7.1 — the «Родительское событие» field ────────────────────


def _row(event_id: int, name: str, parent_id: int | None = None):
    return SimpleNamespace(id=event_id, name=name, parent_id=parent_id)


def _stored_child(**overrides):
    stored = dict(
        id=2, name="Совет", parent_id=1,
        start_date=date(1200, 8, 1), end_date=None,
        start_bc=False, end_bc=False, event_type=None, description=None,
        organizations=[], characters=[], items=[], locations=[],
    )
    return SimpleNamespace(**{**stored, **overrides})


def test_parent_list_offers_dash_and_mains_without_children_or_self(qtbot):
    """Spec «Чужих детей в списке нет» + design Д8: «—», then every main
    event; sub-events never qualify, and the edited event excludes itself."""
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    dialog.populate(_stored_child())
    dialog.set_parent_options([
        _row(1, "Поход"),            # main — offered
        _row(2, "Совет", parent_id=1),  # the edited event — excluded
        _row(3, "Засада", parent_id=1),  # a sub-event — never a parent
        _row(4, "Пир"),              # main — offered
    ])
    assert dialog.vm.parentNames == ["—", "Поход", "Пир"]


def test_parent_combo_selection_relinks_and_dash_promotes(qtbot):
    """Смена значения при сохранении: an index re-reads the chosen main id,
    «—» (index 0) lifts to main, an out-of-range index changes nothing."""
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    dialog.populate(_stored_child())
    dialog.set_parent_options([_row(1, "Поход"), _row(4, "Пир")])
    # populate prefilled the stored link, so the combo starts on «Поход».
    assert dialog.vm.parent_id == 1
    assert dialog.vm.selectedParentIndex == 1

    dialog.vm.selectParent(2)  # «Пир» — перецепка
    assert dialog.vm.parent_id == 4
    assert dialog.vm.selectedParentIndex == 2

    dialog.vm.selectParent(0)  # «—» — подъём в основные
    assert dialog.vm.parent_id is None
    assert dialog.vm.selectedParentIndex == 0

    dialog.vm.selectParent(9)  # beyond the list — ignored
    assert dialog.vm.parent_id is None


def test_edit_result_rewrites_parent_from_the_combo(qtbot):
    """The save contract carries the card's choice: the untouched edit keeps
    the loaded link, a «—» save explicitly promotes to main."""
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    dialog.populate(_stored_child())
    dialog.set_parent_options([_row(1, "Поход"), _row(4, "Пир")])

    assert dialog.build_result().parent_id == 1
    dialog.vm.selectParent(2)
    assert dialog.build_result().parent_id == 4
    dialog.vm.selectParent(0)
    assert dialog.build_result().parent_id is None


def test_parent_slot_before_candidates_is_honest(qtbot):
    """The «Создать подсобытие» prefill sets the id before the async load:
    with no candidates the index reads 0 (nothing to highlight), the value —
    and therefore the save — still carries the parent."""
    vm = EventDialogIslandViewModel()
    vm.parent_id = 7
    assert vm.selectedParentIndex == 0
    vm.set_parent_options([_row(7, "Поход", parent_id=None)])
    assert vm.selectedParentIndex == 1


def test_qml_combos_mirror_the_view_model(qtbot):
    """The island's three new dropdowns are pure mirrors: model and index
    come from the VM, the minute list is enabled only while an hour stands."""
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    dialog.populate(_stored_child())
    dialog.set_parent_options([_row(1, "Поход"), _row(4, "Пир")])

    parent_combo = find_item(dialog.quick, "eventParentCombo")
    assert list(parent_combo.property("model")) == ["—", "Поход", "Пир"]
    assert parent_combo.property("currentIndex") == 1  # «Поход» (prefilled)

    hour_combo = find_item(dialog.quick, "eventStartHourCombo")
    minute_combo = find_item(dialog.quick, "eventStartMinuteCombo")
    assert list(hour_combo.property("model")) == ["—"] + [str(h) for h in range(24)]
    assert hour_combo.property("currentIndex") == 0  # «—» (empty time)
    assert minute_combo.property("enabled") is False

    dialog.vm.selectHour(10)  # 9-й час
    assert hour_combo.property("currentIndex") == 10
    assert minute_combo.property("enabled") is True

    dialog.vm.selectHour(0)  # «—» — and the minute list goes mute again
    assert minute_combo.property("enabled") is False


# ── NRI-0023 task 7.2 — «Час»/«Минута» next to the start date ───────────────


@pytest.fixture
def active_calendar():
    """Save/restore around the process-wide calendar global (D3) — the same
    isolation pattern the timeline accessibility tests use."""
    saved = current_calendar()
    yield
    set_current_calendar(saved)


def _custom(day_hours: int, minutes_per_hour: int) -> CustomCalendar:
    return CustomCalendar(CalendarSpec(
        months=(MonthSpec(name="Кратень", length=15),),
        week_names=("Восход", "Закат"),
        day_hours=day_hours,
        minutes_per_hour=minutes_per_hour,
    ))


@pytest.mark.parametrize(
    ("day_hours", "minutes_per_hour", "expected_minutes"),
    [
        # «…на 60-минутные сутки»: the earthly hour → the clean five ladder.
        (24, 60, list(range(0, 60, 5))),
        # «…на 50-минутные сутки»: 50 % 5 == 0 too, so the designed rule
        # (design Д8) keeps the ladder — 0, 5, …, 45.
        (24, 50, list(range(0, 50, 5))),
        # «…на 100-минутные сутки» with a 10-hour day: calendar-wizard spec
        # «Сутки задают списки времени» pins hours 0…9 and 0, 5, …, 95.
        (10, 100, list(range(0, 100, 5))),
        # The branch the three divisible days cannot reach on their own.
        (12, 47, list(range(0, 47))),
    ],
)
def test_time_lists_take_their_bounds_from_the_active_calendar(
    qtbot, active_calendar, day_hours, minutes_per_hour, expected_minutes
):
    """Spec «Кастомные сутки сужают список» + «Списки часов и минут…»: no
    hardcoded 24/60 — both models are the active calendar's numbers, each
    headed by the empty «—»."""
    set_current_calendar(_custom(day_hours, minutes_per_hour))
    vm = EventDialogIslandViewModel()
    assert list(vm.hourOptions) == ["—"] + [str(h) for h in range(day_hours)]
    assert list(vm.minuteOptions) == ["—"] + [str(m) for m in expected_minutes]


def test_empty_time_stays_empty_and_hour_without_minute_saves_zero(qtbot, active_calendar):
    """Spec «Время не задано — не выдумано» and «Час без минут»: the default
    pair is «—»/«—» = None (never 00:00); a chosen hour with the minutes left
    empty stores minute 0; clearing the hour wipes any minute behind it."""
    vm = EventDialogIslandViewModel()
    assert vm.start_time is None
    assert vm.selectedHourIndex == 0
    assert vm.selectedMinuteIndex == 0
    assert vm.minuteEnabled is False

    vm.selectHour(1)  # час 0 с «—» минут
    assert vm.start_time == TimeOfDay(0, 0)

    vm.selectHour(10)  # 9-й час, минуты по-прежнему «—»
    assert vm.start_time == TimeOfDay(9, 0)
    vm.selectMinute(7)  # 30-я минута ровной лестницы
    assert vm.start_time == TimeOfDay(9, 30)
    assert vm.selectedHourIndex == 10
    assert vm.selectedMinuteIndex == 7

    vm.selectMinute(0)  # «—» назад — это снова 0 минут
    assert vm.start_time == TimeOfDay(9, 0)

    vm.selectHour(0)  # час cleared — время entirely пустое, минута не пережила
    assert vm.start_time is None
    assert vm.selectedMinuteIndex == 0


def test_selection_slots_guard_out_of_range_indices(qtbot, active_calendar):
    vm = EventDialogIslandViewModel()
    vm.selectHour(25)  # day has 24 hours: index 0…24 only
    assert vm.selectedHourIndex == 0
    vm.selectHour(0)  # already empty — no-op, still None
    assert vm.start_time is None
    vm.selectHour(10)
    vm.selectMinute(61)  # 60 ladder entries + the dash head
    assert vm.start_time == TimeOfDay(9, 0)
    vm.selectMinute(0)
    assert vm.start_time == TimeOfDay(9, 0)


def test_saved_out_of_bounds_time_reads_empty_until_repicked(qtbot, active_calendar):
    """Spec «Смена размера суток…»: the narrowed day makes the stored hour
    unavailable; the card opens empty and the stale value never re-participates
    until the user chooses a valid hour."""
    vm = EventDialogIslandViewModel()
    vm.set_start_time(TimeOfDay(23, 45))
    assert vm.start_time == TimeOfDay(23, 45)  # earthly day: shows as stored

    set_current_calendar(_custom(day_hours=10, minutes_per_hour=100))
    vm.set_start_time(TimeOfDay(23, 45))  # hour 23 outside the 10-hour day
    assert vm.selectedHourIndex == 0
    assert vm.selectedMinuteIndex == 0
    assert vm.start_time is None

    # A minute the new five-ladder cannot offer reads empty too, the valid
    # hour stays; the 100-minute ladder shows 5, 10, …, 95.
    vm.set_start_time(TimeOfDay(9, 47))
    assert vm.selectedHourIndex == 10
    assert vm.selectedMinuteIndex == 0
    vm.set_start_time(TimeOfDay(9, 95))
    assert vm.selectedMinuteIndex == 20  # index of 95 in 0,5,…,95 plus the dash


def test_minute_orphaned_by_a_later_calendar_swap_reads_dash(qtbot, active_calendar):
    """The one way past the load/selection sanitisation (the comment above
    ``_selected_minute_index``): a minute chosen on the old ladder, THEN the
    calendar is swapped — the new ladder cannot show it, the list opens on
    the «—» head while the still-fitting hour keeps its selection."""
    vm = EventDialogIslandViewModel()
    vm.selectHour(10)  # earthly 9-й час…
    vm.selectMinute(7)  # …with the 30-я минута of the five ladder
    assert vm.selectedMinuteIndex == 7

    set_current_calendar(_custom(day_hours=10, minutes_per_hour=7))
    # The 7-minute hour enumerates 0…6 in full — the chosen 30 is orphaned.
    assert vm.selectedMinuteIndex == 0
    assert vm.selectedHourIndex == 10  # hour 9 still fits the 10-hour day


def test_populate_and_result_round_trip_the_wall_clock(qtbot, active_calendar):
    """Scenario «Время задано»: the edit dialog reopens with the stored hour
    and minute selected, and an untouched save re-writes the same pair; a
    cleared hour saves None — «пустое», не «0:00»."""
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    dialog.populate(_stored_child(start_time=TimeOfDay(14, 30)))
    assert dialog.vm.selectedHourIndex == 15  # index 14+1 in «—»,0,1,…
    assert dialog.vm.selectedMinuteIndex == 7  # 30 in the five ladder
    assert dialog.build_result().start_time == TimeOfDay(14, 30)

    dialog.vm.selectHour(0)
    assert dialog.build_result().start_time is None


def test_start_display_carries_the_time_after_the_date(qtbot, active_calendar):
    # NRI-0023 task 8.1 (spec event-time «Время на поверхностях события»):
    # the card's read-only start line is the shared surface helper — the
    # chosen time rides the date as «, HH:MM» (the empty-time half is pinned
    # by the startDisplay caption assertions above and the helper's own pin).
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    dialog.populate(_stored_child(start_time=TimeOfDay(9, 5)))
    assert dialog.vm.startDisplay.endswith(", 09:05")


def test_old_events_without_the_field_populate_empty(qtbot, active_calendar):
    """A stored event object without a start_time attribute (the getattr
    default) opens with both lists empty — the dialog invents no time."""
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    dialog.populate(_stored_child())
    assert dialog.vm.selectedHourIndex == 0
    assert dialog.vm.selectedMinuteIndex == 0
    assert dialog.build_result().start_time is None
