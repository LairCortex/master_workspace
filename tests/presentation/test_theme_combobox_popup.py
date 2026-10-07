"""ThemeComboBox popup geometry contract (NRI-0023 group 12, design Д14.1/
Д14.2/Д14.4, spec qml-components «Раскрытый список комбобокса полон и
прокручиваем»).

The live audit (docs/qa/2026-09-29-now-hour-chip-design.md, blocker A1) found
a 25-value model where exactly two rows were realized and clickable: the
popup sized itself to the lazy ListView's own implicitHeight. Offscreen the
same defect could not be seen by the accessibility tree (the popup is a
separate window live, limit ③) — so this file pins the repaired geometry with
pytest-qt over the real QQuickPopupItem inside the widget's overlay:

* the 25-row popup is capped at maxRows rows of the explicit rowHeight while
  the list content stays complete and scrollable;
* the last value is reachable by wheel and activatable by mouse, and by
  keyboard navigation (End/Enter) — each lands exactly on its row;
* opening with a deep currentIndex scrolls the highlighted row into view;
* the states that A6 found indistinguishable now differ: the arrow flips
  only while the popup is open, focus keeps it down, hover paints the
  compiler's accent.hover wash;
* the indicator pocket and the worstCaseText width floor from Д14.2/Д14.3;
* the hairline dividers of A8 (last row carries none).
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QColor, QWheelEvent
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtTest import QTest

from app.infrastructure.ui_prefs.config import UiPrefsManager
from app.presentation.qml.engine import setup_qml_shell
from app.presentation.theme.compiler import tokens_file_path
from app.presentation.theme.qml_palette import QmlPalette
from app.presentation.theme.runtime import ThemeRuntime
from tests.presentation.qml_helpers import click_item, walk_items

SCENE = """
import QtQuick
import QtQuick.Layouts
import nri.components

Item {{
    id: sceneRoot
    implicitWidth: 500
    implicitHeight: 760
{combos}
}}
"""

COMBO_25 = """    ThemeComboBox {
        objectName: "probeCombo"
        model: { var a = ["—"]; for (var i = 0; i < 24; ++i) a.push(String(i)); return a }
        x: 10; y: 10
    }
"""

COMBO_WIDE = """    ThemeComboBox {
        objectName: "probeCombo"
        model: ["—", "1", "очень широкое значение списка для замера ширины попапа"]
        x: 10; y: 10; width: 60
    }
"""

# Both combos sit inside a RowLayout narrower than either of them — a layout
# may not shrink a control below its Layout.minimumWidth, so the laid-out
# width IS the floor the component states (attached Layout properties are not
# addressable from the harness; the effective geometry is the honest read).
WORST_PAIR = """    RowLayout {
        objectName: "worstRow"
        x: 10; y: 10; width: 40; height: 30
        ThemeComboBox {
            objectName: "worstCombo"
            model: ["—", "0", "23"]
            worstCaseText: "Час: 23"
        }
    }
    RowLayout {
        objectName: "plainRow"
        x: 10; y: 60; width: 40; height: 30
        ThemeComboBox {
            objectName: "plainCombo"
            model: ["—", "0", "23"]
        }
    }
    // The island's exact posture (SearchBarRoot's nowHourCombo): a labelled
    // display text whose current value IS the worst option the floor was set
    // by — the legibility case of the 2026-09-29 live re-audit.
    ThemeComboBox {
        objectName: "worstDisplayCombo"
        model: ["—", "0", "23"]
        worstCaseText: "Час: 23"
        displayText: "Час: 23"
        valueIsPlaceholder: false
        x: 10; y: 110
    }
"""


def _load(qtbot, qapp, tmp_path, combo_qml: str) -> tuple[QQuickWidget, dict]:
    if QQuickStyle.name() != "Basic":  # design D4 — set once, never re-set
        QQuickStyle.setStyle("Basic")
    runtime = ThemeRuntime(
        prefs=UiPrefsManager(tmp_path / "ui.json"), tokens_path=tokens_file_path()
    )
    engine = setup_qml_shell(qapp, runtime)
    widget = QQuickWidget(engine, None)
    qtbot.addWidget(widget)
    palette = QmlPalette(runtime)
    palette.setParent(widget)
    widget.rootContext().setContextProperty("islandPalette", palette)
    scene = tmp_path / "combo_popup_scene.qml"
    scene.write_text(SCENE.format(combos=combo_qml), encoding="utf-8")
    widget.resize(500, 760)
    widget.setSource(QUrl.fromLocalFile(str(scene)))
    assert widget.status() == QQuickWidget.Status.Ready, widget.errors()
    widget.show()
    qtbot.waitExposed(widget)
    return widget, palette.tokens


# ── scene readers (the popup item lives in the window overlay, a visual
#    sibling of the island root — qml_helpers' widget-root walk would miss it) ──


def _items(widget: QQuickWidget):
    root = widget.rootObject()
    base = root.parentItem() if root.parentItem() is not None else root
    return list(walk_items(base))


def _item(widget: QQuickWidget, object_name: str):
    found = [i for i in _items(widget) if i.objectName() == object_name]
    assert len(found) == 1, f"expected one {object_name!r}, got {len(found)}"
    return found[0]


def _rows(widget) -> list:
    rows = [
        i for i in _items(widget)
        if i.metaObject().className().startswith("ItemDelegate")
    ]
    rows.sort(key=lambda r: r.mapToScene(QPointF(0, 0)).y())
    return rows


def _row_text(row):
    texts = [i for i in walk_items(row) if i.metaObject().className() == "QQuickText"]
    return texts[0].property("text") if texts else None


def _row_by_text(widget, text):
    for row in _rows(widget):
        if _row_text(row) == text:
            return row
    return None


def _list(widget):
    return _item(widget, "themeComboPopupList")


def _popup_item(widget):
    item = _list(widget).parentItem()
    while item is not None and item.metaObject().className() != "QQuickPopupItem":
        item = item.parentItem()
    assert item is not None
    return item


def _open(widget, combo) -> None:
    click_item(widget, combo)
    widget.grab()
    qtbot_wait = QTest.qWait(60)  # noqa: F841 — one event-loop beat


def _row_in_viewport(widget, row) -> bool:
    lst = _list(widget)
    top = lst.mapToScene(QPointF(0, 0)).y()
    y = row.mapToScene(QPointF(0, 0)).y()
    return top - 0.5 <= y and y + row.property("height") <= top + lst.property("height") + 0.5


def _wait_visible_row(qtbot, widget, text: str, wheel: bool):
    """Scroll (optionally with the wheel) until `text`'s row sits inside the
    popup viewport; returns the row."""
    state = {"t": 0}

    def wheel_tick():
        state["t"] += 1
        if not wheel or state["t"] > 40:
            raise AssertionError(f"row {text!r} never scrolled into the viewport")
        lst = _list(widget)
        pos = lst.mapToScene(QPointF(10, 20))
        point = QPoint(int(pos.x()), int(pos.y()))
        from PySide6.QtWidgets import QApplication
        event = QWheelEvent(
            QPointF(point), widget.mapToGlobal(point), QPoint(0, 0), QPoint(0, -240),
            Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False,
        )
        QApplication.sendEvent(widget, event)
        QTest.qWait(20)

    def settled():
        widget.grab()
        row = _row_by_text(widget, text)
        return row is not None and _row_in_viewport(widget, row) and row

    found: list = []

    def probe():
        widget.grab()
        row = _row_by_text(widget, text)
        if row is not None and _row_in_viewport(widget, row):
            found.append(row)
            return True
        wheel_tick()
        return False

    qtbot.waitUntil(probe, timeout=10000)
    return found[0]


def _rgb(color) -> tuple:
    q = QColor(color)
    return q.red(), q.green(), q.blue()


# ── Д14.1 — the list is complete, capped and scrollable ──────────────────────


def test_25_value_popup_is_capped_and_the_last_hour_reachable_by_wheel_and_mouse(
    qtbot, qapp, tmp_path
):
    widget, tokens = _load(qtbot, qapp, tmp_path, COMBO_25)
    combo = _item(widget, "probeCombo")
    click_item(widget, combo)

    qtbot.waitUntil(lambda: len(_rows(widget)) >= 8, timeout=5000)
    row_height = _rows(widget)[0].property("height")
    lst = _list(widget)
    # capped: eight rows, not the 25 the model holds and not the two A1 had
    assert lst.property("height") == pytest.approx(8 * row_height, abs=1.5)
    assert lst.property("contentHeight") == pytest.approx(25 * row_height, abs=1.5)
    assert lst.property("contentHeight") > lst.property("height")
    assert _popup_item(widget).property("width") >= combo.width()

    # wheel to the last value, then the mouse clicks exactly it
    row = _wait_visible_row(qtbot, widget, "23", wheel=True)
    assert lst.property("contentY") > 0
    assert combo.property("currentIndex") == 0
    click_item(widget, row)
    qtbot.waitUntil(
        lambda: int(combo.property("currentIndex")) == 24, timeout=5000
    )
    assert widget.errors() == []


def test_open_scrolls_to_the_highlighted_hour_and_keeps_it_highlighted(
    qtbot, qapp, tmp_path
):
    """A2: with hour ≥ 1 picked, opening must show the highlighted row —
    without this pin the fixed height would merely crop the list elsewhere."""
    widget, tokens = _load(qtbot, qapp, tmp_path, COMBO_25)
    combo = _item(widget, "probeCombo")
    combo.setProperty("currentIndex", 24)  # hour 23
    click_item(widget, combo)

    def settled():
        widget.grab()
        row = _row_by_text(widget, "23")
        return row is not None and _row_in_viewport(widget, row)

    qtbot.waitUntil(settled, timeout=5000)
    assert _list(widget).property("contentY") > 0
    row = _row_by_text(widget, "23")
    assert bool(row.property("highlighted")) is True
    assert widget.errors() == []


def test_keyboard_navigation_reaches_and_picks_the_last_hour(qtbot, qapp, tmp_path):
    widget, tokens = _load(qtbot, qapp, tmp_path, COMBO_25)
    combo = _item(widget, "probeCombo")
    click_item(widget, combo)  # open
    qtbot.waitUntil(lambda: len(_rows(widget)) >= 8, timeout=5000)
    combo.forceActiveFocus(Qt.OtherFocusReason)

    for _ in range(3):
        QTest.keyClick(widget, Qt.Key_Down)
        QTest.qWait(30)
    assert int(combo.property("highlightedIndex")) == 3
    QTest.keyClick(widget, Qt.Key_End)
    qtbot.waitUntil(
        lambda: int(combo.property("highlightedIndex")) == 24, timeout=5000
    )

    def highlighted_visible():
        widget.grab()
        row = _row_by_text(widget, "23")
        return row is not None and _row_in_viewport(widget, row)

    # the keyboard highlight cannot hide below the viewport either (A1 twin)
    qtbot.waitUntil(highlighted_visible, timeout=5000)
    QTest.keyClick(widget, Qt.Key_Return)
    qtbot.waitUntil(
        lambda: int(combo.property("currentIndex")) == 24, timeout=5000
    )
    assert widget.errors() == []


def test_rows_carry_hairline_dividers_and_the_last_row_omits_it(
    qtbot, qapp, tmp_path
):
    widget, tokens = _load(qtbot, qapp, tmp_path, COMBO_25)
    combo = _item(widget, "probeCombo")
    click_item(widget, combo)
    qtbot.waitUntil(lambda: len(_rows(widget)) >= 8, timeout=5000)
    border = _rgb(tokens["color.border"])
    for row in _rows(widget):
        dividers = [
            i for i in walk_items(row) if i.objectName() == "themeComboPopupDivider"
        ]
        assert len(dividers) == 1
        assert _rgb(dividers[0].property("color")) == border
        if _row_text(row) != "23":
            assert bool(dividers[0].property("visible")) is True
    # scroll the last row in: its under-edge needs no hairline
    last = _wait_visible_row(qtbot, widget, "23", wheel=True)
    divider = [i for i in walk_items(last) if i.objectName() == "themeComboPopupDivider"]
    assert bool(divider[0].property("visible")) is False
    assert widget.errors() == []


def test_popup_never_narrows_below_the_widest_row(qtbot, qapp, tmp_path):
    widget, tokens = _load(qtbot, qapp, tmp_path, COMBO_WIDE)
    combo = _item(widget, "probeCombo")
    combo.setProperty("currentIndex", 2)
    assert combo.width() == 60  # deliberately narrower than the widest value
    click_item(widget, combo)

    def settled():
        widget.grab()
        row = _row_by_text(widget, "очень широкое значение списка для замера ширины попапа")
        return row is not None

    qtbot.waitUntil(settled, timeout=5000)
    row = _row_by_text(widget, "очень широкое значение списка для замера ширины попапа")
    text = [i for i in walk_items(row) if i.metaObject().className() == "QQuickText"][0]
    assert row.property("width") >= text.property("implicitWidth")
    assert _popup_item(widget).property("width") >= combo.width()
    assert _popup_item(widget).property("width") >= row.property("width")
    assert widget.errors() == []


# ── Д14.4 — the states read differently ──────────────────────────────────────


def test_open_flips_the_arrow_while_focus_does_not(qtbot, qapp, tmp_path):
    widget, tokens = _load(qtbot, qapp, tmp_path, COMBO_25)
    combo = _item(widget, "probeCombo")
    arrow = _item(widget, "themeComboArrow")
    background = _item(widget, "themeComboBackground")
    border = _rgb(tokens["color.border"])
    accent = _rgb(tokens["color.accent"])

    # at rest: plain frame, arrow down
    assert _rgb(background.property("frameColor")) == border
    assert float(arrow.property("rotation")) == 0.0

    # focus alone must not fake the open state (A6: one frame for both)
    combo.forceActiveFocus(Qt.OtherFocusReason)
    widget.grab()
    assert _rgb(background.property("frameColor")) == accent
    assert float(arrow.property("rotation")) == 0.0

    # open: accent frame AND the flipped indicator
    click_item(widget, combo)
    qtbot.waitUntil(
        lambda: float(_item(widget, "themeComboArrow").property("rotation")) == 180.0,
        timeout=5000,
    )
    arrow = _item(widget, "themeComboArrow")
    background = _item(widget, "themeComboBackground")
    assert _rgb(background.property("frameColor")) == accent
    # close again: the flip belongs to the popup, not to the click
    click_item(widget, combo)
    qtbot.waitUntil(
        lambda: float(_item(widget, "themeComboArrow").property("rotation")) == 0.0,
        timeout=5000,
    )
    assert widget.errors() == []


def test_hover_paints_the_accent_hover_wash(qtbot, qapp, tmp_path):
    widget, tokens = _load(qtbot, qapp, tmp_path, COMBO_25)
    combo = _item(widget, "probeCombo")
    canvas = _rgb(tokens["color.bg.canvas"])
    hover = _rgb(tokens["color.accent.hover"])
    QTest.mouseMove(widget, QPoint(250, 700))
    widget.grab()
    assert _rgb(_item(widget, "themeComboBackground").property("color")) == canvas
    center = combo.mapToScene(QPointF(combo.property("width") / 2, combo.property("height") / 2))
    QTest.mouseMove(widget, QPoint(int(center.x()), int(center.y())))

    def washed():
        widget.grab()
        return (
            _rgb(_item(widget, "themeComboBackground").property("color")) == hover
        )

    qtbot.waitUntil(washed, timeout=5000)
    QTest.mouseMove(widget, QPoint(250, 700))
    qtbot.waitUntil(
        lambda: _rgb(_item(widget, "themeComboBackground").property("color")) == canvas,
        timeout=5000,
    )
    assert widget.errors() == []


# ── Д14.2/Д14.3 — pocket, ranks, fixed width ─────────────────────────────────


def test_indicator_pocket_never_crosses_the_value(qtbot, qapp, tmp_path):
    widget, tokens = _load(qtbot, qapp, tmp_path, COMBO_25)
    combo = _item(widget, "probeCombo")
    display = _item(widget, "themeComboDisplay")
    arrow = _item(widget, "themeComboArrow")
    space_xs = float(str(tokens["space.xs"]).removesuffix("px"))

    # the reserved band is exactly the arrow plus one space.xs (gallery pin
    # test_combo_indicator... keeps the same formula pixel-checked)
    assert float(combo.property("rightPadding")) == pytest.approx(
        float(combo.property("arrowSize")) + space_xs, abs=0.01
    )
    # the value box and the indicator occupy disjoint x-ranges — the A4
    # overlap (digit x 1413–1419 under arrow x 1410–1418.5) is geometrically
    # impossible now: content ends where the pocket starts
    for index in (0, 1, 24):  # «—», a narrow digit, the widest hour
        combo.setProperty("currentIndex", index)
        widget.grab()
        value_right = display.mapToScene(QPointF(display.property("width"), 0)).x()
        arrow_left = arrow.mapToScene(QPointF(0, 0)).x()
        assert value_right <= arrow_left + 0.01, index
    assert widget.errors() == []


def test_placeholder_value_prints_at_the_muted_rank(qtbot, qapp, tmp_path):
    widget, tokens = _load(qtbot, qapp, tmp_path, COMBO_25)
    combo = _item(widget, "probeCombo")
    display = lambda: _item(widget, "themeComboDisplay")  # noqa: E731
    muted = _rgb(tokens["color.fg.muted"])
    primary = _rgb(tokens["color.fg.primary"])

    assert bool(combo.property("valueIsPlaceholder")) is False
    assert _rgb(display().property("color")) == primary
    combo.setProperty("valueIsPlaceholder", True)
    assert _rgb(display().property("color")) == muted
    combo.setProperty("valueIsPlaceholder", False)
    assert _rgb(display().property("color")) == primary
    assert widget.errors() == []


def test_worst_case_text_pins_the_control_width(qtbot, qapp, tmp_path):
    """Д14.3 (A5): the hour selector's width is set by the calendar's worst
    option, not by the digit currently shown."""
    widget, tokens = _load(qtbot, qapp, tmp_path, WORST_PAIR)
    worst = _item(widget, "worstCombo")
    plain = _item(widget, "plainCombo")

    widths = []
    laid = []
    plain_widths = []
    for index in (0, 1, 2):  # «—», «0», «23»
        worst.setProperty("currentIndex", index)
        plain.setProperty("currentIndex", index)
        widget.grab()
        widths.append(float(worst.property("implicitWidth")))
        laid.append(float(worst.width()))
        plain_widths.append(float(plain.property("implicitWidth")))
    assert len(set(widths)) == 1  # the floor holds for every value
    # …and a parent layout really keeps it: every laid-out width equals the
    # worst-option floor, so selecting a narrower hour cannot move the pair
    # (QQuickLayout rounds geometry to device pixels — one point of slack).
    assert len(set(laid)) == 1
    assert laid[0] == pytest.approx(widths[0], abs=1.0)
    assert len(set(plain_widths)) > 1  # without the hint the old jitter lives
    assert widths[0] >= max(plain_widths)  # the worst option is really widest
    assert widget.errors() == []


def test_the_worst_value_prints_at_the_floor_without_eliding(qtbot, qapp, tmp_path):
    """Д14.3 live half (2026-09-29 re-audit): when the current value IS the
    worst one, its layout ran a hair wider than the TextMetrics the floor was
    measured from and device-pixel rounding squeezed the text slot — the live
    selector printed «Час: …» for 23, i.e. the floor elided the very glyph
    that set it. The band in implicitWidth keeps the value legible: the row
    shows the number, not the ellipsis (truncated stays False at the floor)."""
    widget, tokens = _load(qtbot, qapp, tmp_path, WORST_PAIR)
    worst = _item(widget, "worstDisplayCombo")
    widget.grab()

    displays = [i for i in walk_items(worst) if i.objectName() == "themeComboDisplay"]
    assert len(displays) == 1
    display = displays[0]
    assert str(display.property("text")) == "Час: 23"
    assert bool(display.property("truncated")) is False
    assert widget.errors() == []
