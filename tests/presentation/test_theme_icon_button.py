"""nri.components ThemeIconButton — the library's square glyph button (change
nri-0018-grid-alignment-and-card, tasks 1.1–1.2; NRI-0023 task 11.2 for the
flat (ghost) set).

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

Spec qml-components «Плоская (ghost) гарнитура кнопки библиотеки» (NRI-0023
Д12): a usage that asks for ``ghost: true`` gets no face at all at rest —
neither fill nor border, only the glyph — and the compiler's derivations as
the hover/pressed wash, pixel-pinned in BOTH themes over the same canvas the
row's wash sits on; the gauge and the accessibility are untouched; and a
ghost combined with ``accentBackground`` hands the glyph to ``color.accent.fg``
while the background stays transparent (the chevron-over-selection pair).
Sites that never asked for ghost keep the previous face — pinned here as a
property check and pixel-tested for the whole library in the gallery.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QAccessible, QColor
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

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

    // ── ghost set (NRI-0023 task 11.2) ──────────────────────────────────────
    // The audit's setting: a glyph action standing ON the plain canvas of a
    // row. The canvas token is pushed from Python — the probe must not know
    // the palette in QML (the library reads tokens, the test only compares).
    Rectangle {
        id: canvas
        objectName: "probeCanvas"
        x: 100; y: 60; width: 120; height: 80
    }
    ThemeIconButton {
        id: ghost
        objectName: "probeGhost"
        parent: canvas
        x: 10; y: 24
        text: "▸"
        ghost: true
        Accessible.name: "Развернуть подсобытия"
        onClicked: probeRoot.clicks += 1
    }
    // The chevron-over-selection pair: ghost + accentBackground — the
    // background stays transparent, the glyph takes color.accent.fg.
    ThemeIconButton {
        id: ghostAccent
        objectName: "probeGhostAccent"
        parent: canvas
        x: 60; y: 24
        text: "▾"
        ghost: true
        accentBackground: true
        Accessible.name: "Свернуть подсобытия"
    }

    // Face probes read off the controls' own background nodes: a drifted
    // ghost branch in ThemeButton trips these without any pixel luck.
    readonly property string ghostFace: ghost.background.color.toString()
    readonly property int ghostBorderW: ghost.background.border.width
    readonly property color ghostGlyph: ghost.contentItem.color
    readonly property string ghostAccentFace: ghostAccent.background.color.toString()
    readonly property color ghostAccentGlyph: ghostAccent.contentItem.color
    readonly property string solidFace: glyph.background.color.toString()
    readonly property int solidBorderW: glyph.background.border.width
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


# ── the flat (ghost) set (NRI-0023 task 11.2, design Д12) ─────────────────────


def _composite(base: QColor, over: QColor) -> QColor:
    """The raster composite of ``over`` (its own alpha) on ``base`` — the
    same analytic form the timeline wash pins use; comparisons keep ±2."""
    a = over.alphaF()
    return QColor(
        round(over.red() * a + base.red() * (1 - a)),
        round(over.green() * a + base.green() * (1 - a)),
        round(over.blue() * a + base.blue() * (1 - a)),
    )


def _is_close(actual: QColor, wanted: QColor) -> bool:
    return (abs(actual.red() - wanted.red()) <= 2
            and abs(actual.green() - wanted.green()) <= 2
            and abs(actual.blue() - wanted.blue()) <= 2)


def _scene_pixel(widget: QQuickWidget, item: QQuickItem,
                 lx: float, ly: float) -> QColor:
    """The grabbed pixel at a LOCAL point of the button on the canvas."""
    image = widget.grab().toImage()
    scene = item.mapToScene(QPointF(lx, ly))
    scale = image.width() / max(widget.width(), 1)
    return image.pixelColor(
        min(max(int(scene.x() * scale), 0), image.width() - 1),
        min(max(int(scene.y() * scale), 0), image.height() - 1),
    )


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_ghost_button_is_invisible_until_the_pointer_arrives(qtbot, qapp,
                                                             tmp_path, theme):
    """Spec «Плоская (ghost) гарнитура кнопки библиотеки», scenario
    «Призрачная кнопка невидима до наведения» + the library's pixel rule for
    both themes: at rest neither fill nor border is painted — the corner of
    the 32×32 hit square answers the canvas verbatim, the face property is
    transparent and its border width 0; the PRESSED state (synthetic mouse
    events do reach Controls offscreen) paints the compiler's
    ``color.accent.pressed`` derivation as an exact composite over the same
    canvas, and releasing returns the plain canvas. The hover half of the
    wash is the same ghost branch one step shallower (``accentHover``, the
    accessors themselves are token-probe-pinned by ``test_qml_components``);
    hover events never reach embedded Controls offscreen — the live-audit
    half of the state, pinned live in
    ``docs/qa/2026-09-29-timeline-tree-design-fixes.md``. Neighbours never
    move (nothing geometry-wise changes) and the ghost keeps the штатный
    32×32 gauge."""
    runtime = make_runtime(tmp_path, theme)
    palette = QmlPalette(runtime)
    widget = load_probe(qtbot, qapp, runtime, tmp_path, palette)
    tokens = palette.tokens
    canvas_col = QColor(tokens["color.bg.canvas"])

    canvas = find_item(widget, "probeCanvas")
    canvas.setProperty("color", canvas_col)
    ghost = find_item(widget, "probeGhost")
    root = widget.rootObject()

    # the gauge is untouched by the new face (task 11.2 «калибр прежний»)
    _assert_icon_square(ghost)
    assert ghost.property("ghost") is True

    # at rest: no fill, no border — property AND pixel say «only the glyph»
    assert QColor(str(root.property("ghostFace"))).alpha() == 0, theme
    assert int(root.property("ghostBorderW")) == 0, theme
    assert _scene_pixel(widget, ghost, 3, 3) == canvas_col, theme

    # pressed: the deeper derivation as an exact composite (held pixel).
    center = ghost.mapToScene(QPointF(ghost.width() / 2, ghost.height() / 2))
    pos = QPoint(int(center.x()), int(center.y()))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, pos)
    QTest.qWait(10)
    QApplication.processEvents()
    qtbot.waitUntil(
        lambda: QColor(str(root.property("ghostFace")))
        == QColor(tokens["color.accent.pressed"]),
        timeout=5000,
    )
    pressed_px = _scene_pixel(widget, ghost, 3, 3)
    assert _is_close(
        pressed_px, _composite(canvas_col, QColor(tokens["color.accent.pressed"]))
    ), (theme, pressed_px.name())
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, pos)
    QTest.qWait(10)
    QApplication.processEvents()

    # released: the face is transparent again — the pressed flash was the
    # background node's paint only, the hit square stayed put.
    _assert_icon_square(ghost)
    assert QColor(str(root.property("ghostFace"))).alpha() == 0, theme
    assert _scene_pixel(widget, ghost, 3, 3) == canvas_col, theme

    # Scenario «Привычные кнопки не задеты»: the non-ghost sibling still
    # paints its canvas face with the hairline frame.
    assert QColor(str(root.property("solidFace"))) == canvas_col, theme
    assert int(root.property("solidBorderW")) == 1, theme
    assert widget.errors() == []


def test_the_ghost_branch_reads_the_compiler_derivations_only():
    """Source-level contract of the ghost face (the grep idiom of the a11y
    convention guards — and the library rule: hover/pressed are exactly the
    compiler's ``accentHover``/``accentPressed`` derivations, no color math,
    no literals): the ghost branch in ThemeButton's background answers the
    accessors, and its rest color is the transparent literal."""
    source = (COMPONENTS_DIR / "ThemeButton.qml").read_text(encoding="utf-8")
    branch = source.split("if (control.ghost)", 1)[1].split("if (!control.enabled)", 1)[0]
    assert "control.accentPressed(" in branch
    assert "control.accentHover(" in branch
    assert '"transparent"' in branch
    # …and the border line: a ghost wears no border.
    border_line = [ln for ln in source.splitlines() if "border.width:" in ln][0]
    assert "control.ghost ? 0" in border_line


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_ghost_with_accent_background_hands_the_glyph_to_accent_fg(
    qtbot, qapp, tmp_path, theme
):
    """The pair the ladder chevron rides over the selection wash (design Д12):
    ghost wins the BACKGROUND (transparent at rest — the wash chip never
    returns), accentBackground wins the GLYPH (``color.accent.fg``) — so the
    glyph reads over the accent without punching a canvas hole in it."""
    runtime = make_runtime(tmp_path, theme)
    palette = QmlPalette(runtime)
    widget = load_probe(qtbot, qapp, runtime, tmp_path, palette)
    tokens = palette.tokens
    find_item(widget, "probeCanvas").setProperty(
        "color", QColor(tokens["color.bg.canvas"])
    )

    root = widget.rootObject()
    accent = find_item(widget, "probeGhostAccent")
    _assert_icon_square(accent)
    assert QColor(str(root.property("ghostAccentFace"))).alpha() == 0, theme
    assert root.property("ghostAccentGlyph") == QColor(tokens["color.accent.fg"]), theme
    # the plain ghost keeps the primary glyph rank — only the accent pair flips
    assert root.property("ghostGlyph") == QColor(tokens["color.fg.primary"]), theme
    assert widget.errors() == []
