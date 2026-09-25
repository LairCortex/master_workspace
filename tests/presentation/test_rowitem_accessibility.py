"""Accessibility contract of nri.components RowItem (change
nri-0012-qml-accessibility, task 1.1).

The row is the library's list-row primitive every island list delegates to,
so the tree contract lives INSIDE the component (design D2): role ListItem,
name = the row's own text (D4), and a single accessibility Press runs the
activate path — accessibility has no double press, the press handler mirrors
the double-click semantics, never the selection one (D3). The offscreen
pattern matches design F6/D8: ``QAccessible.queryAccessibleInterface`` on the
addressed item, ``actionInterface().doAction("Press")`` driving the QML
handler; the mouse paths re-verified here prove the component's existing
single-click-selects / double-click-activates contract stayed intact
(spec qml-components «Строка доступна, поведение мыши не изменилось»), and
the no-bridge run pins the theme/off-skin half of that requirement.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QAccessible
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQuickWidgets import QQuickWidget

from app.infrastructure.ui_prefs.config import UiPrefsManager
from app.presentation.qml.engine import setup_qml_shell
from app.presentation.theme.compiler import tokens_file_path
from app.presentation.theme.qml_palette import QmlPalette
from app.presentation.theme.runtime import ThemeRuntime
from tests.presentation.qml_helpers import click_item, find_item

ROW_TEXT = "Игровка (01.01)"
ROW_DESCRIPTION = "Открывает игру"

PROBE_SCENE = """
import QtQuick
import nri.components

Item {
    id: probeRoot
    objectName: "rowItemProbe"
    implicitWidth: 320
    implicitHeight: 120

    // QML-side signal counters — the component's signals reach the island's
    // handlers, so the handlers pin the emit counts (test_qml_components
    // idiom: QML-defined signals are not exposed on the Python wrapper).
    property int taps: 0
    property int activations: 0

    RowItem {
        objectName: "probeRow"
        text: "Игровка (01.01)"
        x: 10; y: 10
        width: 260
        height: implicitHeight
        onSelectedRequested: probeRoot.taps += 1
        onActivateRequested: probeRoot.activations += 1
    }

    // NRI-0017 task 4.1 (FI-3): the usage-site description slot — the island
    // spells the hidden meaning of the row's activation here («Открывает
    // игру» at the launcher), the component only passes it through.
    RowItem {
        objectName: "probeRowDescribed"
        text: "Погоня (02.01)"
        accessibleDescription: "Открывает игру"
        x: 10; y: 60
        width: 260
        height: implicitHeight
    }
}
"""


@pytest.fixture
def runtime(tmp_path):
    tokens_copy = tmp_path / "tokens.json"
    tokens_copy.write_text(tokens_file_path().read_text(encoding="utf-8"), encoding="utf-8")
    return ThemeRuntime(prefs=UiPrefsManager(tmp_path / "ui.json"), tokens_path=tokens_copy)


def load_row_probe(qtbot, qapp, runtime, palette: "QmlPalette | None", tmp_path):
    """The row probe on the shared shell engine (production import path).

    ``palette=None`` is the off-skin run: no ``islandPalette`` anywhere in the
    context chain (conftest's isolated_qml_shell guarantees inheritance is
    impossible).
    """
    if QQuickStyle.name() != "Basic":
        QQuickStyle.setStyle("Basic")
    scene = tmp_path / "rowitem_probe.qml"
    scene.write_text(PROBE_SCENE, encoding="utf-8")
    engine = setup_qml_shell(qapp, runtime)
    widget = QQuickWidget(engine, None)
    qtbot.addWidget(widget)
    widget.resize(320, 120)
    if palette is not None:
        palette.setParent(widget)
        widget.rootContext().setContextProperty("islandPalette", palette)
    widget.setSource(QUrl.fromLocalFile(str(scene)))
    assert widget.status() == QQuickWidget.Status.Ready, widget.errors()
    widget.grab()
    return widget


def accessible_of(item):
    iface = QAccessible.queryAccessibleInterface(item)
    assert iface is not None, f"no accessibility interface on {item.objectName()!r}"
    return iface


def counters(widget) -> tuple[int, int]:
    root = widget.rootObject()
    return int(root.property("taps")), int(root.property("activations"))


def press(item) -> None:
    actions = accessible_of(item).actionInterface()
    assert "Press" in actions.actionNames()
    actions.doAction("Press")


def test_row_exposes_list_item_role_and_row_text_name(qtbot, qapp, runtime, tmp_path):
    widget = load_row_probe(qtbot, qapp, runtime, QmlPalette(runtime), tmp_path)
    row = find_item(widget, "probeRow")

    iface = accessible_of(row)
    assert iface.role() == QAccessible.Role.ListItem
    assert iface.text(QAccessible.Name) == ROW_TEXT
    # The name follows the row text (design D4: the default binding is the
    # row's own text — an island list renames every row through it).
    row.setProperty("text", "Багир")
    assert accessible_of(row).text(QAccessible.Name) == "Багир"
    assert widget.errors() == []


def test_description_property_slots_to_the_description_slot(qtbot, qapp, runtime, tmp_path):
    """NRI-0017 task 4.1 (FI-3): the row carries a passing-through description
    slot — the usage-site fills the hidden meaning of the activation (the
    launcher spells «Открывает игру»), the component only relays it into
    ``Accessible.description``. Rows without the property keep the slot empty
    (design NRI-0012 D5: only where the name doesn't spell the action)."""
    widget = load_row_probe(qtbot, qapp, runtime, QmlPalette(runtime), tmp_path)
    described = find_item(widget, "probeRowDescribed")

    assert accessible_of(described).text(QAccessible.Description) == ROW_DESCRIPTION

    # The slot follows the property (a binding, not a one-shot copy).
    described.setProperty("accessibleDescription", "Открывает карточку")
    assert accessible_of(described).text(QAccessible.Description) == "Открывает карточку"

    # The unannotated row: empty slot — no fabricated description.
    assert accessible_of(find_item(widget, "probeRow")).text(
        QAccessible.Description) == ""
    assert widget.errors() == []


def test_press_action_activates_exactly_once(qtbot, qapp, runtime, tmp_path):
    widget = load_row_probe(qtbot, qapp, runtime, QmlPalette(runtime), tmp_path)
    row = find_item(widget, "probeRow")
    assert counters(widget) == (0, 0)

    press(row)

    # Exactly one activate, zero selections: a11y Press == the row's open
    # action (design D3), not a selection.
    assert counters(widget) == (0, 1)
    assert widget.errors() == []


def test_single_mouse_click_still_only_selects(qtbot, qapp, runtime, tmp_path):
    widget = load_row_probe(qtbot, qapp, runtime, QmlPalette(runtime), tmp_path)
    row = find_item(widget, "probeRow")

    click_item(widget, row)
    assert counters(widget) == (1, 0)

    click_item(widget, row, double=True)
    assert counters(widget) == (1, 1)
    assert widget.errors() == []


def test_offskin_row_contract_is_identical(qtbot, qapp, runtime, tmp_path):
    widget = load_row_probe(qtbot, qapp, runtime, None, tmp_path)
    row = find_item(widget, "probeRow")

    iface = accessible_of(row)
    assert iface.role() == QAccessible.Role.ListItem
    assert iface.text(QAccessible.Name) == ROW_TEXT

    press(row)
    assert counters(widget) == (0, 1)
    assert widget.errors() == []
