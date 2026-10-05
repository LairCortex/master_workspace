"""RelatedPickerViewModel — the state half of the «Выберите <тип>» sheet.

PR-020 moved the binding picker's MultiSelection from the (unprojectable)
QListWidget onto this VM: row loading keeps the retired QListWidgetItem duck
(name falls back to ``str``, id to ``None``), a toggle flips exactly its own
row, the accessibility select ticks for good, and the commit walk stays in
the candidates' order — the retired dialog's apply_selection, verbatim.
"""
from __future__ import annotations

from types import SimpleNamespace

from app.presentation.viewmodels.related_picker_view_model import (
    RelatedPickerViewModel,
)


def _vm(*entities):
    vm = RelatedPickerViewModel()
    vm.load(list(entities))
    return vm


def test_load_maps_rows_to_label_id_and_empties_the_selection():
    vm = _vm(SimpleNamespace(id=1, name="Алиса"), SimpleNamespace(id=None, name="Борис"))
    assert vm.rows == [{"id": 1, "label": "Алиса"}, {"id": None, "label": "Борис"}]
    assert vm.selectedIndex == []


def test_load_falls_back_like_the_retired_list_item():
    class _NoName:
        id = 7

        def __str__(self) -> str:
            return "безымянный"

    vm = _vm(_NoName())
    assert vm.rows == [{"id": 7, "label": "безымянный"}]


def test_toggle_flips_only_its_own_row():
    vm = _vm(SimpleNamespace(id=1, name="a"), SimpleNamespace(id=2, name="b"))
    vm.toggleRow(0)
    vm.toggleRow(1)
    assert vm.selectedIndex == [0, 1]
    vm.toggleRow(0)
    assert vm.selectedIndex == [1]


def test_toggle_out_of_range_is_a_noop():
    vm = _vm(SimpleNamespace(id=1, name="a"))
    vm.toggleRow(-1)
    vm.toggleRow(5)
    assert vm.selectedIndex == []


def test_select_ticks_for_good_and_ignores_repeats_and_ranks():
    vm = _vm(SimpleNamespace(id=1, name="a"), SimpleNamespace(id=2, name="b"))
    vm.selectRow(0)
    vm.selectRow(0)  # already ticked — silent (no double emit churn)
    vm.selectRow(-1)
    vm.selectRow(9)
    assert vm.selectedIndex == [0]


def test_selected_entities_walks_the_candidates_in_order():
    entities = [SimpleNamespace(id=10, name="a"), SimpleNamespace(id=20, name="b")]
    vm = _vm(*entities)
    assert vm.selected_entities(entities) == []
    vm.toggleRow(1)
    vm.selectRow(0)
    assert vm.selected_entities(entities) == [entities[0], entities[1]]
    # A candidate that left the available list is simply not in the walk.
    assert vm.selected_entities([entities[1]]) == [entities[1]]
