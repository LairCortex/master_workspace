"""nri.components ThemeIconButton — the library's square glyph button (change
nri-0018-grid-alignment-and-card, tasks 1.1–1.2).

Spec qml-components «Квадратная мелкая кнопка действия библиотеки»: the
component is the ONE carrier of the small-action geometry — a fixed 32×32
square (design Д1: a component constant, not a token, so no usage site can
ever pick its own side), skins from the very same ThemeButton derivation it
inherits, and keeps the штатный accessibility contract: the stock Button role
comes with the control, the NAME is the usage site's (glyph buttons are named
by the action, nri-0012 map) and a single accessibility Press is a single
activation. The AI button (``ThemeAiButton``) accepts the same square without
losing its look or its states (scenario «AI-кнопка осталась собой»): «✨» /
«…», observable ``aiState`` — all as before, and the square side is pinned
identical in both component sources so the gauge can never drift apart.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QAccessible
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQuickWidgets import QQuickWidget

from app.presentation import qml as qml_shell
from app.presentation.qml.engine import setup_qml_shell
from app.presentation.theme.qml_palette import QmlPalette
from tests.presentation.qml_helpers import click_item, find_item
from tests.ui.test_theme_grab import make_runtime

COMPONENTS_DIR = (
    Path(qml_shell.__file__).resolve().parent / "nri" / "components"
)

# The single gauge every small glyph action in the app measures (spec
# «фиксированный квадрат единого калибра (32×32)»).
SIDE = 32

PROBE_SCENE = """
import QtQuick
import nri.components

Item {
    id: probeRoot
    objectName: "iconButtonProbe"
    implicitWidth: 240
    implicitHeight: 120

    // QML-side click counter: pins that the component's activation is the
    // stock Button.clicked the Press action also rides (one behaviour,
    // two entry points — the ThemeSheetHeader pattern).
    property int clicks: 0

    ThemeIconButton {
        id: glyph
        objectName: "probeGlyph"
        x: 10; y: 10
        text: "✕"
        // Glyph-only: the usage-site names it by the action (nri-0012 map).
        Accessible.name: "Тестовое действие"
        onClicked: probeRoot.clicks += 1
    }

    ThemeAiButton {
        id: ai
        objectName: "probeAi"
        x: 60; y: 10
        Accessible.name: "Сгенерировать: Поле"
    }
}
"""


def load_probe(qtbot, qapp, runtime, tmp_path, palette=None) -> QQuickWidget:
    """The probe on the shared shell engine; ``palette=None`` = off-skin."""
    if QQuickStyle.name() != "Basic":
        QQuickStyle.setStyle("Basic")
    scene = tmp_path / "icon_button_probe.qml"
    scene.write_text(PROBE_SCENE, encoding="utf-8")
    engine = setup_qml_shell(qapp, runtime)
    widget = QQuickWidget(engine, None)
    qtbot.addWidget(widget)
    widget.resize(240, 120)
    if palette is not None:
        palette.setParent(widget)
        widget.rootContext().setContextProperty("islandPalette", palette)
    widget.setSource(QUrl.fromLocalFile(str(scene)))
    assert widget.status() == QQuickWidget.Status.Ready, widget.errors()
    widget.grab()
    return widget


def _assert_icon_square(item) -> None:
    assert float(item.property("side")) == SIDE
    assert (item.width(), item.height()) == (SIDE, SIDE)
    assert (item.implicitWidth(), item.implicitHeight()) == (SIDE, SIDE)


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_icon_button_is_the_fixed_square_themed(qtbot, qapp, tmp_path, theme):
    """Scenario «Все мелкие действия — один квадрат»: the component alone owns
    the 32×32 geometry (spec: 32×32 in both themes, no theme dependency)."""
    runtime = make_runtime(tmp_path, theme)
    widget = load_probe(qtbot, qapp, runtime, tmp_path, QmlPalette(runtime))
    _assert_icon_square(find_item(widget, "probeGlyph"))
    assert widget.rootObject().property("clicks") == 0
    assert widget.errors() == []


def test_icon_button_keeps_the_square_offskin(qtbot, qapp, tmp_path):
    # Own test, own isolated engine: the themed bridge of the variant above
    # can never leak into the no-bridge run (the load_probe_scene convention).
    off_skin = load_probe(qtbot, qapp, make_runtime(tmp_path, "dark"), tmp_path)
    _assert_icon_square(find_item(off_skin, "probeGlyph"))
    # Off-skin the inherited ThemeButton face degrades to the plain Basic
    # button (design D7) but the geometry is the component's own — it stays.
    assert find_item(off_skin, "probeGlyph").property("skinned") is False
    assert off_skin.errors() == []


def test_icon_button_carries_role_name_and_press(qtbot, qapp, tmp_path):
    runtime = make_runtime(tmp_path, "dark")
    widget = load_probe(qtbot, qapp, runtime, tmp_path, QmlPalette(runtime))

    glyph = find_item(widget, "probeGlyph")
    iface = QAccessible.queryAccessibleInterface(glyph)
    assert iface is not None
    assert iface.role() == QAccessible.Role.Button
    assert iface.text(QAccessible.Name) == "Тестовое действие"

    actions = iface.actionInterface()
    assert "Press" in actions.actionNames()
    actions.doAction("Press")
    assert int(widget.rootObject().property("clicks")) == 1

    # The mouse path rides the same clicked() — no second behaviour.
    click_item(widget, glyph)
    click_item(widget, glyph)
    assert int(widget.rootObject().property("clicks")) == 3
    assert widget.errors() == []


def test_ai_button_takes_the_square_and_keeps_its_states(qtbot, qapp, tmp_path):
    runtime = make_runtime(tmp_path, "dark")
    widget = load_probe(qtbot, qapp, runtime, tmp_path, QmlPalette(runtime))

    ai = find_item(widget, "probeAi")
    assert (ai.width(), ai.height()) == (SIDE, SIDE)
    assert (ai.implicitWidth(), ai.implicitHeight()) == (SIDE, SIDE)
    # Look and states untouched (spec «AI-кнопка осталась собой»): the idle
    # glyph is «✨», the observable aiState contract stays the proxy/default.
    assert ai.property("text") == "✨"
    assert ai.property("aiState") == "disabled"

    # The generating state repaints the glyph to «…» without leaving the
    # square (scenario «AI-кнопка осталась собой»).
    ai.setProperty("isGenerating", True)
    widget.grab()
    assert ai.property("text") == "…"
    assert (ai.width(), ai.height()) == (SIDE, SIDE)

    iface = QAccessible.queryAccessibleInterface(ai)
    assert iface.role() == QAccessible.Role.Button
    assert iface.text(QAccessible.Name) == "Сгенерировать: Поле"
    assert widget.errors() == []


@pytest.mark.parametrize("component", ("ThemeIconButton", "ThemeAiButton"))
def test_the_square_side_is_one_component_constant(component):
    """Design Д1's «одно знание — одно место» for the gauge itself: the side
    is declared as the same named constant inside the library components — no
    token, no usage-site size (a silent re-gauge trips this pin)."""
    source = (COMPONENTS_DIR / f"{component}.qml").read_text(encoding="utf-8")
    assert re.search(rf"readonly property int side:\s*{SIDE}\b", source), component
    assert re.search(r"\bwidth:\s*side\b", source), component
    assert re.search(r"\bheight:\s*side\b", source), component
    assert re.search(r"\bimplicitWidth:\s*side\b", source), component
    assert re.search(r"\bimplicitHeight:\s*side\b", source), component
