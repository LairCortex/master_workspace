"""EventTypesViewModel — the thin sync mirror of the types island (R3 pack 2).

Tasks 2.3/2.4: rows, selection, the name text and the availability flags with
no ``EventService``, no injected ``_run`` and no QML around. Every user action
leaves the VM as a *synchronous request signal* — the facade answers it, so
the VM here is driven and observed exactly as the island drives it.
"""
from __future__ import annotations

import inspect
from types import SimpleNamespace

from app.presentation.theme.compiler import CHART_TOKEN_KEYS
from app.presentation.viewmodels.event_types_view_model import EventTypesViewModel
from tests.presentation.qml_helpers import track


def _types(*specs) -> list:
    """Service-shaped type rows (id, name, color_index, sort_order)."""
    return [
        SimpleNamespace(id=type_id, name=name, color_index=color, sort_order=order)
        for order, (type_id, name, color) in enumerate(specs)
    ]


SEEDED = ((11, "Сюжет", 1), (12, "Побочное", 2), (13, "Слух", 3))


def test_empty_vm_has_no_rows_selection_or_actions():
    vm = EventTypesViewModel()
    assert vm.rows == []
    assert vm.selectedId is None
    assert vm.selectedColorIndex == 0
    assert vm.nameText == ""
    assert vm.hasSelection is False
    assert vm.canRemove is False
    assert vm.canMoveUp is False
    assert vm.canMoveDown is False
    # The palette size is published, never re-declared in QML (D5).
    assert vm.paletteSize == len(CHART_TOKEN_KEYS) == 8


def test_set_rows_publishes_id_name_and_color_roles_in_order():
    vm = EventTypesViewModel()
    changed = track(vm.rowsChanged)
    vm.set_rows(_types(*SEEDED))
    assert changed
    assert vm.rows == [
        {"id": 11, "name": "Сюжет", "colorIndex": 1},
        {"id": 12, "name": "Побочное", "colorIndex": 2},
        {"id": 13, "name": "Слух", "colorIndex": 3},
    ]
    assert vm.selectedId is None  # a refresh selects nothing by itself


def test_select_mirrors_name_color_and_move_flags():
    vm = EventTypesViewModel()
    vm.set_rows(_types(*SEEDED))

    vm.select(0)
    assert vm.selectedId == 11
    assert vm.selectedColorIndex == 1
    assert vm.nameText == "Сюжет"
    assert vm.hasSelection is True
    assert vm.canRemove is True
    assert vm.canMoveUp is False  # first row: nowhere to rise
    assert vm.canMoveDown is True

    vm.select(2)
    assert vm.selectedId == 13
    assert vm.nameText == "Слух"
    assert vm.canMoveUp is True
    assert vm.canMoveDown is False  # last row: nowhere to fall

    vm.select(9)  # outside the list == no selection
    assert vm.selectedId is None
    assert vm.nameText == ""
    assert vm.canRemove is False


def test_selection_survives_a_refresh_by_id_and_drops_with_the_row():
    vm = EventTypesViewModel()
    vm.set_rows(_types(*SEEDED))
    vm.select(2)

    # Reordered + renamed by the service: the id keeps the selection, the
    # name text follows the new name (the facade's post-write reload).
    vm.set_rows(_types((13, "Примета", 3), (11, "Сюжет", 1), (12, "Побочное", 2)))
    assert vm.selectedId == 13
    assert vm.selected_row == 0
    assert vm.nameText == "Примета"

    vm.set_rows(_types((11, "Сюжет", 1)))  # the selected row is gone
    assert vm.selectedId is None
    assert vm.nameText == ""


def test_select_by_id_moves_the_selection_and_ignores_unknown_ids():
    vm = EventTypesViewModel()
    vm.set_rows(_types(*SEEDED))
    vm.select_by_id(12)
    assert vm.selectedId == 12
    vm.select_by_id(999)
    assert vm.selectedId == 12  # unknown id: the selection stays put


def test_name_text_notifies_only_on_change():
    vm = EventTypesViewModel()
    notified = track(vm.nameTextChanged)
    vm.setNameText("Слух")
    vm.setNameText("Слух")
    assert len(notified) == 1
    assert vm.nameText == "Слух"


def test_add_request_carries_the_name_text():
    vm = EventTypesViewModel()
    added = track(vm.addRequested)
    vm.setNameText("  Находка  ")
    vm.requestAdd()
    assert added == [("Находка",)]
    # No name: the request still leaves (the facade names the new type).
    vm.setNameText("")
    vm.requestAdd()
    assert added[-1] == ("",)


def test_rename_request_needs_a_selection_and_a_new_non_empty_name():
    vm = EventTypesViewModel()
    vm.set_rows(_types(*SEEDED))
    renamed = track(vm.renameRequested)

    vm.setNameText("Примета")
    vm.requestRename()
    assert renamed == []  # nothing selected

    vm.select(2)
    vm.setNameText("   ")
    vm.requestRename()
    vm.setNameText("Слух")
    vm.requestRename()
    assert renamed == []  # blank and unchanged names are not requests

    vm.setNameText("Примета")
    vm.requestRename()
    assert renamed == [(13, "Примета")]


def test_recolor_request_only_for_another_palette_index():
    vm = EventTypesViewModel()
    vm.set_rows(_types(*SEEDED))
    recolored = track(vm.recolorRequested)

    vm.requestRecolor(7)
    assert recolored == []  # nothing selected

    vm.select(0)
    vm.requestRecolor(1)  # already worn
    vm.requestRecolor(0)  # outside the closed palette
    vm.requestRecolor(len(CHART_TOKEN_KEYS) + 1)
    assert recolored == []

    vm.requestRecolor(7)
    assert recolored == [(11, 7)]


def test_move_request_stops_at_the_ladder_edges():
    vm = EventTypesViewModel()
    vm.set_rows(_types(*SEEDED))
    moved = track(vm.moveRequested)

    vm.requestMove(1)
    assert moved == []  # nothing selected

    vm.select(0)
    vm.requestMove(-1)
    assert moved == []
    vm.requestMove(1)
    assert moved == [(11, 1)]

    vm.select(2)
    vm.requestMove(1)
    assert moved == [(11, 1)]  # last row: no further request


def test_remove_and_close_requests():
    vm = EventTypesViewModel()
    vm.set_rows(_types(*SEEDED))
    removed = track(vm.removeRequested)
    closed = track(vm.closeRequested)

    vm.requestRemove()
    assert removed == []  # nothing selected

    vm.select(1)
    vm.requestRemove()
    assert removed == [(12,)]

    vm.requestClose()
    assert closed == [()]


def test_flags_notify_only_when_availability_moves():
    vm = EventTypesViewModel()
    vm.set_rows(_types(*SEEDED))
    flagged = track(vm.flagsChanged)
    vm.select(1)
    first = len(flagged)
    assert first >= 1
    vm.select(1)  # same row again
    assert len(flagged) == first


def test_vm_needs_no_service_and_exposes_sync_entrances_only():
    """Spec qml-shell «VM не знает про QML» / «Sync-вход достаточен»."""
    vm = EventTypesViewModel()  # no event service, no `_run`
    for name, member in inspect.getmembers(type(vm)):
        if name.startswith("_") or not inspect.isfunction(member):
            continue
        assert not inspect.iscoroutinefunction(member), name
