from datetime import date
from types import SimpleNamespace

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import QDialog, QListWidget, QMessageBox

from app.presentation.viewmodels.event_dialog_island_view_model import (
    EventDialogIslandViewModel,
)
from app.presentation.views.event_dialog import EventDialog
from tests.presentation.qml_helpers import find_item
from tests.ui.test_theme_grab import make_runtime


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
        "eventEndDateField",
        "eventNoEndCheck",
        "eventTypeCombo",
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
    assert entity.text() == "⏹"
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
