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
Д12, owner rework of the 2026-09-30 live audits): a usage that asks for
``ghost: true`` wears NO own face in ANY state — neither fill nor border at
rest, hovered or pressed, only the glyph. The first cut answered hover/press
with the compiler's derivations (color.accent.hover/pressed); being the
accent under an alpha they printed as a light rounded chip over the hovered
row's own wash and wherever the 32 px square overhangs a shorter band — the
same-day rework retired them, the background's ghost branch is the constant
"transparent" in every state. The interaction story is the row's (its wash,
its tooltip) and the state flip lives in the glyph tint: a ghost combined
with ``accentBackground`` (the chevron-over-selection pair) shares that
constant and hands the glyph to ``color.accent.fg``. Pixel-pinned in BOTH
themes over the same canvas the row's wash sits on; the gauge and the
accessibility are untouched. Sites that never asked for ghost keep the
previous face — pinned here as a property check and pixel-tested for the
whole library in the gallery.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QAccessible, QColor
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.presentation import qml as qml_shell
from app.presentation.qml.engine import setup_qml_shell
from app.presentation.theme.qml_palette import QmlPalette
from tests.presentation.qml_helpers import click_item, find_item, walk_items
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
    // background wears no face in any state, the glyph takes color.accent.fg.
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

    // ── stateful glyph face (the preview pin, user request 2026-10-03) ──────
    // The two seats the pin uses: the leaning rest angle (iconRotation) and
    // the accent-engaged tint (iconAccentTint). Ghost keeps the glyph the
    // only paint in the region — the centring pixel pin measures against.
    ThemeIconButton {
        id: rotRest
        objectName: "probeRotRest"
        x: 10; y: 70
        ghost: true
        iconName: "pin"
        iconRotation: 90
        iconAccentTint: true
        Accessible.name: "Закрепить карточку"
    }
    ThemeIconButton {
        id: rotUpright
        objectName: "probeRotUpright"
        x: 50; y: 70
        ghost: true
        iconName: "pin"
        iconAccentTint: true
        Accessible.name: "Открепить карточку"
    }
    // The tint chain's order of precedence: engaged → accent while enabled,
    // the mute still outranks the accent when the button is disabled.
    ThemeIconButton {
        id: tintAccent
        objectName: "probeTintAccent"
        x: 140; y: 10
        ghost: true
        iconName: "pin"
        iconAccentTint: true
    }
    ThemeIconButton {
        id: tintDisabled
        objectName: "probeTintDisabled"
        x: 180; y: 10
        ghost: true
        iconName: "pin"
        iconAccentTint: true
        enabled: false
    }

    // Face probes read off the controls' own background nodes: a drifted
    // ghost branch in ThemeButton trips these without any pixel luck.
    readonly property string ghostFace: ghost.background.color.toString()
    readonly property int ghostBorderW: ghost.background.border.width
    readonly property color ghostGlyph: ghost.iconTint
    readonly property string ghostAccentFace: ghostAccent.background.color.toString()
    readonly property color ghostAccentGlyph: ghostAccent.iconTint
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
    # face is the Lucide «sparkles» glyph (2026-09-30 icon pass — the mute
    # «✨» text glyph retired, the state contract did not), the observable
    # aiState contract stays the proxy/default.
    assert ai.property("iconName") == "sparkles"
    assert ai.property("text") == ""
    assert ai.property("aiState") == "disabled"

    # The generating state repaints the glyph to «…» without leaving the
    # square (scenario «AI-кнопка осталась собой»).
    ai.setProperty("isGenerating", True)
    widget.grab()
    assert ai.property("text") == "…"
    assert ai.property("iconName") == ""
    assert (ai.width(), ai.height()) == (SIDE, SIDE)

    # The stop half of a batch wave (A4, live fix 2026-09-30): while the wave
    # runs the press stops it and the face prints the Lucide «circle-stop»
    # instead of the «…» — the retired mute «⏹» text, in glyph form.
    ai.setProperty("isCancelling", True)
    widget.grab()
    assert ai.property("text") == ""
    assert ai.property("iconName") == "circle-stop"

    # Idle again: the sparkles face returns (third state of the pin).
    ai.setProperty("isGenerating", False)
    ai.setProperty("isCancelling", False)
    widget.grab()
    assert ai.property("text") == ""
    assert ai.property("iconName") == "sparkles"

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


# ── the flat (ghost) set (NRI-0023 task 11.2, design Д12, owner rework
#    of the 2026-09-30 live audits: no own face in ANY state) ─────────────────


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
def test_ghost_button_wears_no_face_in_any_state(qtbot, qapp,
                                                 tmp_path, theme):
    """Spec «Плоская (ghost) гарнитура кнопки библиотеки» (owner rework of
    the 2026-09-30 live audits), pixel-pinned in both themes: the ghost
    wears NO own face in ANY state. At rest the face property is transparent
    with border width 0 and the corner of the 32×32 hit square answers the
    canvas verbatim; the PRESSED state (synthetic mouse events do reach
    Controls offscreen) changes NOTHING — the same transparent property and
    the same canvas pixel, where the retired first cut answered the
    compiler's ``color.accent.pressed`` as a composite chip; releasing keeps
    the plain canvas. Hover is the same constant branch one step shallower —
    hover events never reach embedded Controls offscreen, the source half of
    that state is pinned by the ghost-branch guards below, the live half in
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

    # pressed: the state lands on the control, yet the face does not move —
    # the constant branch wears nothing (the retired chip was exactly the
    # ``color.accent.pressed`` composite at this very corner).
    center = ghost.mapToScene(QPointF(ghost.width() / 2, ghost.height() / 2))
    pos = QPoint(int(center.x()), int(center.y()))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, pos)
    QTest.qWait(10)
    QApplication.processEvents()
    assert ghost.property("pressed") is True, theme  # the state landed
    assert QColor(str(root.property("ghostFace"))).alpha() == 0, theme
    assert _scene_pixel(widget, ghost, 3, 3) == canvas_col, theme
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, pos)
    QTest.qWait(10)
    QApplication.processEvents()

    # released: still nothing of its own — the press never painted and the
    # hit square stayed put.
    _assert_icon_square(ghost)
    assert QColor(str(root.property("ghostFace"))).alpha() == 0, theme
    assert int(root.property("ghostBorderW")) == 0, theme
    assert _scene_pixel(widget, ghost, 3, 3) == canvas_col, theme

    # Scenario «Привычные кнопки не задеты»: the non-ghost sibling still
    # paints its canvas face with the hairline frame.
    assert QColor(str(root.property("solidFace"))) == canvas_col, theme
    assert int(root.property("solidBorderW")) == 1, theme
    assert widget.errors() == []


def test_the_ghost_branch_answers_the_transparent_literal_only():
    """Source-level contract of the ghost face after the owner rework of the
    2026-09-30 live audits (the grep idiom of the a11y convention guards):
    the ghost branch in ThemeButton's background is a CONSTANT — its single
    answer is the transparent literal, in every state. The retired first
    cut's derivation reads (``accentHover``/``accentPressed``) and the
    ``pressed``/``hovered`` states they rode must stay out of the branch —
    re-adding them would reprint the accent-under-alpha chip over the
    row's own wash; no color math and no other literal may appear."""
    source = (COMPONENTS_DIR / "ThemeButton.qml").read_text(encoding="utf-8")
    branch = source.split("if (control.ghost)", 1)[1].split("if (!control.enabled)", 1)[0]
    assert branch.count("return") == 1, branch
    assert 'return "transparent";' in branch, branch
    # the retired hover/pressed face must not creep back into the branch
    assert "control.accentPressed(" not in branch
    assert "control.accentHover(" not in branch
    assert "control.pressed" not in branch
    assert "control.hovered" not in branch
    # …and the border line: a ghost wears no border.
    border_line = [ln for ln in source.splitlines() if "border.width:" in ln][0]
    assert "control.ghost ? 0" in border_line


def test_the_ghost_pair_on_an_accent_fill_shares_the_constant():
    """Source contract of the live fix 2026-09-30 (the light chip the user
    saw around the ladder chevron on the selected row): the derivations are
    the accent under an alpha — over the solid selection band the 32 px
    square overhangs they printed as a rounded chip. The pair therefore
    shares the plain ghost's constant: the ghost answer never consults
    ``accentBackground`` (no pair branch, no short-circuit guard of its own
    — the constant IS the suppression), and it stands in the color binding
    before any state or accent-derivation branch is reached. The pixel half
    is pinned by ``test_ghost_with_accent_background_hands_the_glyph_to_accent_fg``;
    sites that never asked for ghost keep their derivation pair
    word-for-word."""
    source = (COMPONENTS_DIR / "ThemeButton.qml").read_text(encoding="utf-8")
    branch = source.split("if (control.ghost)", 1)[1].split("if (!control.enabled)", 1)[0]
    assert "control.accentBackground" not in branch, branch
    # the constant is returned before the binding ever reads a state or an
    # accent branch — nothing can repaint the pair over the selection band.
    constant = source.index('return "transparent";')
    assert constant < source.index("if (control.accentBackground)")
    assert constant < source.index("control.pressed")
    # the non-ghost half keeps its derivation pair (scenario «Привычные
    # кнопки не задеты» at the source level).
    assert "control.accentPressed(control.accentColor)" in source
    assert "control.accentHover(control.accentColor)" in source


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_ghost_with_accent_background_hands_the_glyph_to_accent_fg(
    qtbot, qapp, tmp_path, theme
):
    """The pair the ladder chevron rides over the selection wash (design Д12):
    ghost wins the BACKGROUND, accentBackground wins the GLYPH
    (``color.accent.fg``) — so the glyph reads over the accent without
    punching a canvas hole in it. The live fix 2026-09-30 tightened the
    background half from «transparent at rest» to «no face in ANY state»:
    the synthetic press (which DOES reach Controls offscreen — the plain-ghost
    test rides it) must leave the face transparent and the corner pixel the
    canvas verbatim, where the retired behavior answered the pressed
    derivation as a composite (the reported chip). Hover is the same branch
    one step shallower — unreachable to synthetic mouse events offscreen, its
    suppression is source-pinned by the guard above and the live half by
    the 2026-09-30 re-audit."""
    runtime = make_runtime(tmp_path, theme)
    palette = QmlPalette(runtime)
    widget = load_probe(qtbot, qapp, runtime, tmp_path, palette)
    tokens = palette.tokens
    canvas_col = QColor(tokens["color.bg.canvas"])
    find_item(widget, "probeCanvas").setProperty("color", canvas_col)

    root = widget.rootObject()
    accent = find_item(widget, "probeGhostAccent")
    _assert_icon_square(accent)
    # at rest: no face, only the flipped glyph stands on the band
    assert QColor(str(root.property("ghostAccentFace"))).alpha() == 0, theme
    assert root.property("ghostAccentGlyph") == QColor(tokens["color.accent.fg"]), theme
    # the plain ghost keeps the primary glyph rank — only the accent pair flips
    assert root.property("ghostGlyph") == QColor(tokens["color.fg.primary"]), theme

    # pressed: the face stays transparent and the pixel stays the canvas —
    # the pair wears no face in ANY state (the retired chip was exactly this
    # paint: accent under an alpha printed around the glyph, composite
    # ``_composite(canvas_col, pressed)`` at this very corner).
    center = accent.mapToScene(QPointF(accent.width() / 2, accent.height() / 2))
    pos = QPoint(int(center.x()), int(center.y()))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, pos)
    QTest.qWait(10)
    QApplication.processEvents()
    assert accent.property("pressed") is True, theme  # the state landed
    assert QColor(str(root.property("ghostAccentFace"))).alpha() == 0, theme
    assert _scene_pixel(widget, accent, 3, 3) == canvas_col, theme
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, pos)
    QTest.qWait(10)
    QApplication.processEvents()
    assert QColor(str(root.property("ghostAccentFace"))).alpha() == 0, theme
    assert widget.errors() == []


# ── stateful glyph face (the preview pin, user request 2026-10-03) ───────────


def test_icon_rotation_and_accent_tint_are_the_component_seats(qtbot, qapp, tmp_path):
    """The pin's two face knobs live in the component (the usage site never
    reaches into the icon node): ``iconRotation`` turns BOTH glyph slots and
    lands on the ThemeIcon's ``glyphRotation``; ``iconAccentTint`` hands the
    enabled glyph to ``color.accent`` while the one chain keeps its order —
    a disabled glyph stays muted (the duplicate/limit pins), an accent-filled
    face keeps its own foreground. Defaults (0 / false) answer the previous
    face word-for-word — pinned by the untouched tests above."""
    runtime = make_runtime(tmp_path, "dark")
    palette = QmlPalette(runtime)
    widget = load_probe(qtbot, qapp, runtime, tmp_path, palette)
    tokens = palette.tokens

    lean = find_item(widget, "probeRotRest")
    upright = find_item(widget, "probeRotUpright")
    assert float(lean.property("iconRotation")) == 90.0
    assert float(upright.property("iconRotation")) == 0.0
    for button, angle in ((lean, 90.0), (upright, 0.0)):
        glyphs = [
            i for i in walk_items(button)
            if i.objectName() in ("themeButtonIcon", "themeButtonTrailingIcon")
            and bool(i.property("visible"))
        ]
        # The trailing mirror node exists but stays hidden without a name —
        # the visible glyph alone must carry the seat's angle.
        assert len(glyphs) == 1, button.objectName()
        assert float(glyphs[0].property("glyphRotation")) == angle

    tint = find_item(widget, "probeTintAccent")
    accent = QColor(tokens["color.accent"])
    assert tint.property("iconTint") == accent
    assert find_item(widget, "probeRotUpright").property("iconAccentTint") is True
    disabled = find_item(widget, "probeTintDisabled")
    assert disabled.property("iconTint") == QColor(tokens["color.fg.muted"])
    # The flag alone never re-tints a non-ghost plain button…
    plain = find_item(widget, "probeGlyph")
    assert plain.property("iconAccentTint") is False
    # …and the accent-filled face keeps its foreground precedence.
    ghost_accent = find_item(widget, "probeGhostAccent")
    assert ghost_accent.property("iconTint") == QColor(tokens["color.accent.fg"])
    assert widget.errors() == []


def test_a_leaning_glyph_turns_in_place(qtbot, qapp, tmp_path):
    """Pixel half of the rotation seat: the lean is the pin's REST face, so
    it must not walk the glyph off its seat — the spin pivots on the glyph's
    own centre (the transform list scales the Lucide grid onto the item box
    first, then rotates around that box's centre). Same ghost button, same
    spot, two angles: the painted bounding boxes share their centre."""
    runtime = make_runtime(tmp_path, "dark")
    palette = QmlPalette(runtime)
    widget = load_probe(qtbot, qapp, runtime, tmp_path, palette)
    find_item(widget, "probeCanvas")  # load-time contract holds for this scene

    upright = find_item(widget, "probeRotUpright")
    lean = find_item(widget, "probeRotRest")
    # The buttons sit 40 px apart; the glyph centres must keep exactly that
    # distance — a pivot error would shift the rotated glyph.
    image = widget.grab().toImage()
    scale = image.width() / max(widget.width(), 1)

    def _painted_center(item) -> tuple[float, float]:
        origin = item.mapToScene(QPointF(0, 0))
        x0 = int(origin.x() * scale)
        y0 = int(origin.y() * scale)
        w = int(item.width() * scale)
        h = int(item.height() * scale)
        ref = _scene_pixel(widget, item, 1, 1)  # the corner pixel = bare seat
        xs, ys = [], []
        for py in range(y0, y0 + h):
            for px in range(x0, x0 + w):
                col = QColor(image.pixelColor(px, py))
                if (
                    abs(col.red() - ref.red())
                    + abs(col.green() - ref.green())
                    + abs(col.blue() - ref.blue())
                ) > 90:
                    xs.append(px)
                    ys.append(py)
        assert xs, f"{item.objectName()}: the ghost glyph painted nothing"
        return (
            (min(xs) + max(xs)) / 2 / scale,
            (min(ys) + max(ys)) / 2 / scale,
        )

    ux, uy = _painted_center(upright)
    lx, ly = _painted_center(lean)
    # The seats are 40 px apart (lean LEFT of upright in the scene) — the
    # 90° turn must not move either glyph off its seat.
    assert abs(abs(lx - ux) - 40.0) <= 1.5, (ux, uy, lx, ly)
    assert abs(ly - uy) <= 1.5, (ux, uy, lx, ly)
