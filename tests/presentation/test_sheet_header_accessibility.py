"""Accessibility contract of nri.components ThemeSheetHeader (change
nri-0014-window-contract-and-docs, task 4.1).

The sheet title row is the library component of the island-sheet header
(spec qml-components «Компонент строки заголовка листа», design D3): role,
name and Press live INSIDE the component — the close glyph is icon-like, so
the tree name «Закрыть» is the component's annotation, not a usage-site one;
a single accessibility Press emits closeRequested() exactly once and the
component itself owns no closing behaviour. As in every other island suite
the action is pinned with ``queryAccessibleInterface`` + ``actionInterface().
doAction("Press")`` (design F6/D8), the emission is counted through a plain
QML property (QML-defined signals are not exposed on the Python wrapper),
and the no-bridge run covers the off-skin half of spec qml-components
«Компонент доступен и без темы». The same-tokens half of spec «Одна тема с
листом» is pinned by the title colour being exactly fg.primary of each
theme — the same token the sheet skin paints (a live toggle of one open
sheet is the pattern already pinned per-dialog in test_live_retheme_*).
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QAccessible, QColor
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQuickWidgets import QQuickWidget

from app.presentation.qml.engine import setup_qml_shell
from app.presentation.theme.compiler import load_tokens, tokens_file_path
from app.presentation.theme.qml_palette import QmlPalette
from tests.presentation.qml_helpers import find_item
from tests.ui.test_theme_grab import make_runtime

PROBE_SCENE = """
import QtQuick
import nri.components

Item {
    id: probeRoot
    objectName: "sheetHeaderProbe"
    implicitWidth: 360
    implicitHeight: 120

    // closeRequested() rides the component contract; the counter pins its
    // emits (QML-defined signals are not exposed on the Python wrapper).
    property int closes: 0

    ThemeSheetHeader {
        objectName: "probeHeader"
        title: "Новое событие"
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        onCloseRequested: probeRoot.closes += 1
    }
}
"""


def load_header_probe(qtbot, qapp, runtime, tmp_path, palette=None):
    """The header probe on the shared shell engine; ``palette=None`` = off-skin
    (no islandPalette anywhere in the context chain)."""
    if QQuickStyle.name() != "Basic":
        QQuickStyle.setStyle("Basic")
    scene = tmp_path / "sheet_header_probe.qml"
    scene.write_text(PROBE_SCENE, encoding="utf-8")
    engine = setup_qml_shell(qapp, runtime)
    widget = QQuickWidget(engine, None)
    qtbot.addWidget(widget)
    widget.resize(360, 120)
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


def test_close_button_carries_the_component_role_and_name(qtbot, qapp, tmp_path):
    runtime = make_runtime(tmp_path, "dark")
    widget = load_header_probe(qtbot, qapp, runtime, tmp_path, QmlPalette(runtime))

    close = accessible_of(find_item(widget, "sheetHeaderClose"))
    assert close.role() == QAccessible.Role.Button
    # The icon-like glyph leaves the tree name to its meaning: the component
    # annotates «Закрыть» itself (design D3), offscreen included.
    assert close.text(QAccessible.Name) == "Закрыть"

    # The title string reaches the visible text of the row.
    assert find_item(widget, "sheetHeaderTitle").property("text") == "Новое событие"
    assert widget.errors() == []


def test_press_emits_close_requested_exactly_once(qtbot, qapp, tmp_path):
    runtime = make_runtime(tmp_path, "dark")
    widget = load_header_probe(qtbot, qapp, runtime, tmp_path, QmlPalette(runtime))
    root = widget.rootObject()

    actions = accessible_of(find_item(widget, "sheetHeaderClose")).actionInterface()
    assert "Press" in actions.actionNames()
    actions.doAction("Press")
    assert int(root.property("closes")) == 1

    actions.doAction("Press")
    assert int(root.property("closes")) == 2
    assert widget.errors() == []


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_title_paints_the_same_token_as_the_sheet(qtbot, qapp, tmp_path, theme):
    runtime = make_runtime(tmp_path, theme)
    widget = load_header_probe(qtbot, qapp, runtime, tmp_path, QmlPalette(runtime))
    title = find_item(widget, "sheetHeaderTitle")

    tokens = load_tokens(tokens_file_path())
    assert QColor(title.property("color")) == QColor(tokens["color.fg.primary"][theme])
    assert widget.errors() == []


def test_offskin_header_contract_is_identical_and_does_not_crash(qtbot, qapp, tmp_path):
    runtime = make_runtime(tmp_path, "dark")
    widget = load_header_probe(qtbot, qapp, runtime, tmp_path)
    root = widget.rootObject()

    close = accessible_of(find_item(widget, "sheetHeaderClose"))
    assert close.role() == QAccessible.Role.Button
    assert close.text(QAccessible.Name) == "Закрыть"
    assert find_item(widget, "sheetHeaderTitle").property("text") == "Новое событие"

    actions = close.actionInterface()
    assert "Press" in actions.actionNames()
    actions.doAction("Press")
    assert int(root.property("closes")) == 1
    assert widget.errors() == []
