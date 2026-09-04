"""SheetListViewModel unit tests (port-sheet-list-preset-dialogs-qml-q3a, 1.1).

Pure Python state: two row models (roles ``id``/``label``), the current tab,
per-tab selection ids and the ``canOpen/canRename/canDelete/
presetButtonVisible`` flags. The flags must replicate the widgets dialog's
``_sync_actions_enabled`` rules exactly:
- templates tab: open/rename need a selection; delete is additionally blocked
  for the sheet open in the editor (``set_open_sheet_id``) and for templates
  that still have sheets (the count comes from the rows fed by Python);
- sheets tab: open/rename need a selection; delete is additionally blocked for
  the open instance (``set_open_instance_id``) and seated instances
  (``set_seated_ids``);
- «Создать из пресета…» is an action of the templates tab only.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.presentation.viewmodels.sheet_list_view_model import (
    TAB_INSTANCES,
    TAB_TEMPLATES,
    SheetListViewModel,
)


def tpl(sheet_id: int, name: str) -> SimpleNamespace:
    """Stand-in for CharacterSheetModel (the VM only reads .id/.name)."""
    return SimpleNamespace(id=sheet_id, name=name)


def inst(instance_id: int, name: str, template_id: int) -> SimpleNamespace:
    """Stand-in for CharacterSheetInstanceModel (.id/.name/.template_id)."""
    return SimpleNamespace(id=instance_id, name=name, template_id=template_id)


TPL = tpl(10, "Fate Core")
INST_A = inst(100, "Гром", 10)
INST_B = inst(101, "Ведьма", 20)  # template 20 not in templates

DASH = "—"


# --- row models / Python-side labels -----------------------------------------


def test_empty_vm_defaults():
    vm = SheetListViewModel()
    assert vm.templateList == []
    assert vm.instanceList == []
    assert vm.currentTab == TAB_TEMPLATES
    assert vm.selected_template_id is None
    assert vm.selected_instance_id is None
    # no selection anywhere: nothing actionable, presets only on templates tab
    assert (vm.canOpen, vm.canRename, vm.canDelete) == (False, False, False)
    assert vm.presetButtonVisible is True


def test_template_rows_have_id_and_plain_label():
    vm = SheetListViewModel()
    vm.set_rows([TPL, tpl(20, "Mörk Borg")], [])
    assert vm.templateList == [
        {"id": 10, "label": "Fate Core"},
        {"id": 20, "label": "Mörk Borg"},
    ]


def test_instance_label_is_composed_in_python():
    """«лист — шаблон»: Python composes the label, QML never concatenates."""
    vm = SheetListViewModel()
    vm.set_rows([TPL], [INST_A])
    assert vm.instanceList == [
        {"id": 100, "label": f"Гром {DASH} Fate Core"},
    ]


def test_instance_label_without_known_template_is_plain_name():
    # Mirrors the widgets dialog: the label falls back to just the name when
    # the instance's template is missing from the templates feed.
    vm = SheetListViewModel()
    vm.set_rows([TPL], [INST_B])
    assert vm.instanceList == [{"id": 101, "label": "Ведьма"}]


def test_refresh_keeps_selection_by_id_and_drops_it_when_row_vanishes():
    vm = SheetListViewModel()
    vm.set_rows([TPL, tpl(20, "Mörk Borg")], [INST_A, INST_B])
    vm.selectTemplate(1)
    vm.selectInstance(0)

    # Re-order the templates: selection follows the id, not the position.
    vm.set_rows([tpl(20, "Mörk Borg"), TPL], [INST_A, INST_B])
    assert vm.selected_template_id == 20
    assert vm.selected_instance_id == 100

    # The selected ids vanish with their rows: selection clears (the widgets
    # list did the same when its current item was removed on clear()).
    vm.set_rows([TPL], [INST_B])
    assert vm.selected_template_id is None
    assert vm.selected_instance_id is None
    # Surviving ids are re-selected by position of the same id.
    vm.select_template_by_id(10)
    vm.select_instance_by_id(101)
    vm.set_rows([TPL], [INST_B, INST_A])
    assert vm.selected_template_id == 10
    assert vm.selected_instance_id == 101


def test_select_by_id_helpers_move_selection(qtbot):
    vm = SheetListViewModel()
    vm.set_rows([TPL, tpl(20, "Mörk Borg")], [INST_A, INST_B])
    with qtbot.waitSignal(vm.selectionChanged, timeout=1000):
        vm.select_template_by_id(20)
    assert vm.selected_template_id == 20
    with qtbot.waitSignal(vm.selectionChanged, timeout=1000):
        vm.select_instance_by_id(101)
    assert vm.selected_instance_id == 101

    # Unknown id: no-op (same as the widgets dialog scanning rows).
    vm.select_template_by_id(999)
    assert vm.selected_template_id == 20


def test_selection_out_of_range_clears_like_the_launcher_vm():
    vm = SheetListViewModel()
    vm.set_rows([TPL], [INST_A])
    vm.selectTemplate(0)
    vm.selectTemplate(5)  # outside the list -> "no selection"
    assert vm.selected_template_id is None
    vm.selectInstance(0)
    vm.selectInstance(-3)
    assert vm.selected_instance_id is None


def test_selected_names_are_the_plain_names_not_labels():
    """Rename prefills must use the stored name («Ведьма»), never the label."""
    vm = SheetListViewModel()
    vm.set_rows([TPL], [INST_A, INST_B])
    vm.selectTemplate(0)
    assert vm.selected_template_name == "Fate Core"
    vm.selectInstance(1)
    assert vm.selected_instance_name == "Ведьма"
    vm.selectTemplate(-1)
    vm.selectInstance(-1)
    assert vm.selected_template_name is None
    assert vm.selected_instance_name is None


# --- tab / presetButtonVisible ------------------------------------------------


def test_tab_switch_emits_and_flips_preset_button(qtbot):
    vm = SheetListViewModel()
    assert vm.presetButtonVisible is True
    with qtbot.waitSignal(vm.tabChanged, timeout=1000):
        vm.setCurrentTab(TAB_INSTANCES)
    assert vm.currentTab == TAB_INSTANCES
    assert vm.presetButtonVisible is False
    vm.setCurrentTab(TAB_TEMPLATES)
    assert vm.presetButtonVisible is True


def test_invalid_tab_index_is_ignored():
    vm = SheetListViewModel()
    vm.setCurrentTab(7)
    assert vm.currentTab == TAB_TEMPLATES


# --- flags: templates tab, all lock combinations ------------------------------

# (selected, open_sheet_id, has_instances, expected canDelete) — open/rename
# depend on the selection only.
TEMPLATES_DELETE_MATRIX = [
    (None, None, False, False),  # no selection -> nothing deletable
    (10, None, False, True),  # clean selection -> deletable
    (10, 10, False, False),  # the template open in the editor
    (10, None, True, False),  # template that already has sheets
    (10, 20, False, True),  # editor holds another template -> still deletable
    (10, 20, True, False),  # sheets beat every other lock
]


@pytest.mark.parametrize(
    "selected_id, open_id, with_instance, expected", TEMPLATES_DELETE_MATRIX
)
def test_templates_tab_flags(selected_id, open_id, with_instance, expected):
    vm = SheetListViewModel()
    instances = [INST_A] if with_instance and selected_id == 10 else []
    vm.set_rows([TPL, tpl(20, "Mörk Borg")], instances)
    vm.set_open_sheet_id(open_id)
    if selected_id is not None:
        vm.select_template_by_id(selected_id)
    assert vm.canOpen is (selected_id is not None)
    assert vm.canRename is (selected_id is not None)
    assert vm.canDelete is expected
    # «Создать из пресета…» never depends on the selection or locks.
    assert vm.presetButtonVisible is True


# --- flags: sheets tab, all lock combinations ---------------------------------

INSTANCES_DELETE_MATRIX = [
    (None, None, frozenset(), False),  # no selection
    (100, None, frozenset(), True),  # clean selection
    (100, 100, frozenset(), False),  # the sheet open in the Fill dialog
    (100, None, frozenset({100}), False),  # seated on the wall
    (100, 101, frozenset(), True),  # editor holds another sheet
    (100, 101, frozenset({101}), True),  # other sheet is seated/open, not ours
]


@pytest.mark.parametrize(
    "selected_id, open_id, seated, expected", INSTANCES_DELETE_MATRIX
)
def test_sheets_tab_flags(selected_id, open_id, seated, expected):
    vm = SheetListViewModel()
    vm.set_rows([TPL], [INST_A, inst(101, "Ведьма", 10)])
    vm.set_open_instance_id(open_id)
    vm.set_seated_ids(set(seated))
    vm.setCurrentTab(TAB_INSTANCES)
    if selected_id is not None:
        vm.select_instance_by_id(selected_id)
    assert vm.canOpen is (selected_id is not None)
    assert vm.canRename is (selected_id is not None)
    assert vm.canDelete is expected
    assert vm.presetButtonVisible is False


def test_locks_only_apply_to_their_own_tab():
    """The templates locks must not disable the sheets-tab delete, and vice versa."""
    vm = SheetListViewModel()
    vm.set_rows([TPL], [INST_A])
    vm.set_open_sheet_id(10)  # the template is locked...
    vm.setCurrentTab(TAB_INSTANCES)
    vm.select_instance_by_id(100)
    assert vm.canDelete is True  # ...but the sheet delete is independent
    vm.setCurrentTab(TAB_TEMPLATES)
    vm.select_instance_by_id(100)  # sheet stays selected per tab
    vm.select_template_by_id(10)
    assert vm.canDelete is False  # open template lock now bites


def test_lock_changes_recompute_flags_and_emit(qtbot):
    vm = SheetListViewModel()
    vm.set_rows([TPL], [])
    vm.select_template_by_id(10)
    assert vm.canDelete is True
    with qtbot.waitSignal(vm.flagsChanged, timeout=1000):
        vm.set_open_sheet_id(10)
    assert vm.canDelete is False
    with qtbot.waitSignal(vm.flagsChanged, timeout=1000):
        vm.set_open_sheet_id(None)
    assert vm.canDelete is True


def test_setting_a_lock_to_the_same_value_emits_nothing(qtbot):
    vm = SheetListViewModel()
    vm.set_open_sheet_id(10)
    vm.set_seated_ids({100})
    recorder = []
    vm.flagsChanged.connect(lambda: recorder.append(1))
    vm.set_open_sheet_id(10)
    vm.set_open_instance_id(None)
    vm.set_seated_ids(None)
    vm.set_seated_ids({100})
    assert recorder == []


def test_set_seated_ids_none_clears_the_set(qtbot):
    vm = SheetListViewModel()
    vm.set_rows([TPL], [INST_A])
    vm.setCurrentTab(TAB_INSTANCES)
    vm.set_seated_ids({100})
    vm.select_instance_by_id(100)
    assert vm.canDelete is False
    vm.set_seated_ids(None)
    assert vm.canDelete is True


def test_set_rows_emits_rows_changed(qtbot):
    vm = SheetListViewModel()
    with qtbot.waitSignal(vm.rowsChanged, timeout=1000):
        vm.set_rows([TPL], [INST_A])
