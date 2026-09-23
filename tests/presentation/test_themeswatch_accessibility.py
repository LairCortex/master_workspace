"""Accessibility contract of nri.components ThemeSwatch (change
nri-0012-qml-accessibility, task 1.2).

Role RadioButton, checked state, and Press == the very select behaviour the
mouse uses (checked=true + clicked()) live INSIDE the component (design D2);
the name defaults to «Цвет палитры №<effectiveColorIndex>» and is a plain
bindable property so an island renames its swatch by purpose at the usage
site (design D4). Offscreen pin follows design F6/D8
(``queryAccessibleInterface`` + ``doAction("Press")``); the no-bridge run
covers the theme/off-skin half of spec qml-components «Компонент доступен и
без темы».
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
from tests.presentation.qml_helpers import find_item

PROBE_SCENE = """
import QtQuick
import nri.components

Item {
    id: probeRoot
    objectName: "swatchProbe"
    implicitWidth: 200
    implicitHeight: 80

    // clicked() reaches the island's handler — the counter pins its emits
    // (QML-defined signals are not exposed on the Python wrapper).
    property int clicks: 0

    ThemeSwatch {
        objectName: "probeSwatch"
        colorIndex: 3
        x: 10; y: 10
        onClicked: probeRoot.clicks += 1
    }
    ThemeSwatch {
        // The usage-site override an island applies (e.g. the event-type
        // dialog names its swatch by purpose, design D4).
        objectName: "namedSwatch"
        colorIndex: 2
        accessibleName: "Цвет типа события"
        x: 60; y: 10
    }
    ThemeSwatch {
        // Unbound default on a moved index: pins that «№N» follows
        // effectiveColorIndex, not the declaration site.
        objectName: "lateSwatch"
        x: 110; y: 10
    }
}
"""


@pytest.fixture
def runtime(tmp_path):
    tokens_copy = tmp_path / "tokens.json"
    tokens_copy.write_text(tokens_file_path().read_text(encoding="utf-8"), encoding="utf-8")
    return ThemeRuntime(prefs=UiPrefsManager(tmp_path / "ui.json"), tokens_path=tokens_copy)


def load_swatch_probe(qtbot, qapp, runtime, tmp_path, palette=None):
    """The swatch probe on the shared shell engine; ``palette=None`` = off-skin
    (no islandPalette anywhere in the context chain)."""
    if QQuickStyle.name() != "Basic":
        QQuickStyle.setStyle("Basic")
    scene = tmp_path / "themeswatch_probe.qml"
    scene.write_text(PROBE_SCENE, encoding="utf-8")
    engine = setup_qml_shell(qapp, runtime)
    widget = QQuickWidget(engine, None)
    qtbot.addWidget(widget)
    widget.resize(200, 80)
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


def test_swatch_exposes_radio_role_default_and_overridden_names(qtbot, qapp, runtime, tmp_path):
    widget = load_swatch_probe(qtbot, qapp, runtime, tmp_path, QmlPalette(runtime))

    swatch = accessible_of(find_item(widget, "probeSwatch"))
    assert swatch.role() == QAccessible.Role.RadioButton
    # Default name = palette position (task 1.2: «Цвет палитры №
    # <effectiveColorIndex>»).
    assert swatch.text(QAccessible.Name) == "Цвет палитры №3"

    named = accessible_of(find_item(widget, "namedSwatch"))
    assert named.role() == QAccessible.Role.RadioButton
    # The usage-site accessibleName replaces the default entirely.
    assert named.text(QAccessible.Name) == "Цвет типа события"

    # Unbound default re-evaluates with the model-driven index (list delegates
    # move colorIndex per row).
    late = find_item(widget, "lateSwatch")
    assert accessible_of(late).text(QAccessible.Name) == "Цвет палитры №1"
    late.setProperty("colorIndex", 7)
    assert accessible_of(late).text(QAccessible.Name) == "Цвет палитры №7"
    assert widget.errors() == []


def test_checked_state_and_press_selects(qtbot, qapp, runtime, tmp_path):
    widget = load_swatch_probe(qtbot, qapp, runtime, tmp_path, QmlPalette(runtime))
    swatch_item = find_item(widget, "probeSwatch")
    swatch = accessible_of(swatch_item)
    assert bool(swatch.state().checked) is False

    actions = swatch.actionInterface()
    assert "Press" in actions.actionNames()
    actions.doAction("Press")

    # Press performs the existing select behaviour: checked=true + clicked()
    # (the component routes both the mouse and the a11y action through the
    # same function, so no second select path exists).
    assert swatch_item.property("checked") is True
    assert int(widget.rootObject().property("clicks")) == 1
    assert bool(accessible_of(swatch_item).state().checked) is True
    assert widget.errors() == []


def test_offskin_swatch_contract_is_identical(qtbot, qapp, runtime, tmp_path):
    widget = load_swatch_probe(qtbot, qapp, runtime, tmp_path)
    swatch_item = find_item(widget, "probeSwatch")

    swatch = accessible_of(swatch_item)
    assert swatch.role() == QAccessible.Role.RadioButton
    assert swatch.text(QAccessible.Name) == "Цвет палитры №3"
    assert bool(swatch.state().checked) is False

    actions = swatch.actionInterface()
    assert "Press" in actions.actionNames()
    actions.doAction("Press")
    assert swatch_item.property("checked") is True
    assert int(widget.rootObject().property("clicks")) == 1
    assert widget.errors() == []
