"""PR-020 — the «Выберите <тип>» picker rows answer the accessibility tree.

The binding picker (the «Привязать существующего» list of the event dialog and
the entity card) was a widgets ``QListWidget``: its rows are virtual cells of
QAccessibleTable, and the cocoa projection of that family never carries the
row the live audit can press (live-аудит 2026-10-03, PR-020: «Алиса» projected
nameless, no action reached the selection, OK always saw an empty choice —
the same item-view hole PR-022 pinned for the desk rows). The picker is the
library row now: every candidate is a ``RowItem`` — the component owns the
ListItem role and the single accessibility Press, the usage site supplies the
name (the entity's visible name, design D4) and the description of what the
press means here («Выбирает сущность», the fixed map).

The offscreen pattern is the row contract's own (test_rowitem_accessibility):
``QAccessible.queryAccessibleInterface`` on the addressed delegate, the Press
performed through ``actionInterface().doAction("Press")``. In this picker the
row's activation IS the choice: the press selects that candidate and accepts
the sheet (the preset picker's migrated-OK idiom, SheetPresetRoot) — the AT
user lands in the section with the entity linked, without ever needing the
coordinate channel H1 keeps silent.
"""
from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtGui import QAccessible

from app.presentation.views.event_dialog import EventDialog
from tests.presentation.qml_helpers import click_item, island_rows


def _open_picker(qtbot, *names: str):
    """The «Выберите персонажи» sheet the event dialog hands its stack.

    Both layers are shown (the connector's open_sheet show is offscreen
    ``show`` minus the native attach) so the visibility half of the press
    contract — the sheet leaves, the opener layer stays — is real.
    """
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    entities = [
        SimpleNamespace(id=index + 1, name=name) for index, name in enumerate(names)
    ]
    dialog.set_available_entities("characters", entities)
    emitted: list = []
    dialog.sheet_requested.connect(emitted.append)
    dialog._open_related_picker("characters", "Персонажи")
    assert len(emitted) == 1
    dialog.show()
    picker = emitted[0]
    qtbot.addWidget(picker)
    picker.show()
    return dialog, picker


def _press(row) -> None:
    actions = QAccessible.queryAccessibleInterface(row).actionInterface()
    assert "Press" in actions.actionNames()
    actions.doAction("Press")


def test_rows_carry_listitem_role_entity_name_and_choice_description(qtbot):
    """The defect of PR-020 was a row that answers nothing: no name, no
    action. Every candidate row is now a ListItem named by the entity's
    visible name, its press meaning spelled in the fixed description slot."""
    _dialog, picker = _open_picker(qtbot, "Алиса", "Борис")
    rows = island_rows(picker.quick, "relatedPickerRow")
    assert len(rows) == 2

    for row, name in zip(rows, ("Алиса", "Борис")):
        iface = QAccessible.queryAccessibleInterface(row)
        assert iface is not None
        assert iface.role() == QAccessible.Role.ListItem
        assert iface.text(QAccessible.Name) == name
        assert iface.text(QAccessible.Description) == "Выбирает сущность"


def test_press_on_a_row_performs_the_choice(qtbot):
    """The live half of PR-020: AX-выделение строки never reached the model.
    A Press now activates the row — that candidate joins the section, the
    sheet closes and the opener layer stays up."""
    dialog, picker = _open_picker(qtbot, "Алиса", "Борис")
    rows = island_rows(picker.quick, "relatedPickerRow")
    assert picker.isVisible()

    _press(rows[1])

    assert not picker.isVisible()
    assert dialog.vm.characters.get_current_ids() == [2]
    assert dialog.isVisible()


def test_press_commits_the_whole_selection_not_only_its_row(qtbot):
    """The picker is multi-selection: a press completes the choice the mouse
    has already accumulated, the committed order stays the candidates'."""
    dialog, picker = _open_picker(qtbot, "Алиса", "Борис")
    rows = island_rows(picker.quick, "relatedPickerRow")

    click_item(picker.quick, rows[0])  # the user ticked Алиса
    _press(rows[1])  # the AT press completes the choice

    assert dialog.vm.characters.get_current_ids() == [1, 2]


def test_single_click_toggles_selection_like_multiselection(qtbot):
    """Mouse parity with the retired MultiSelection list: a single click
    toggles only its own row (others stay ticked), the sheet stays open."""
    _dialog, picker = _open_picker(qtbot, "Алиса", "Борис")
    rows = island_rows(picker.quick, "relatedPickerRow")

    click_item(picker.quick, rows[0])
    click_item(picker.quick, rows[1])
    assert picker.vm.selectedIndex == [0, 1]

    click_item(picker.quick, rows[0])
    assert picker.vm.selectedIndex == [1]
    assert picker.isVisible()
