"""The sheet-header action slot and the wave button seated in it (change
nri-0018-grid-alignment-and-card, task group 3; specs qml-components
«Компонент строки заголовка листа» («Действие стоит за заголовком»),
qml-shell «Шапка карточки сущности названа по-русски и несёт полную
генерацию» and entity-generation «Кнопка стоит у заголовка»).

Component half (task 3.2): ThemeSheetHeader's default property is an action
slot hung off the title text — the usage site's action lands as a visual
child of the slot host, at a fixed space.sm from the title box, vertically
centered on the title line; the close stays glued to the opposite edge so
the order «заголовок → действие → … → закрытие» is structural (pure anchors,
no theme dependency) and the title keeps its natural, un-clipped width.

Usage half (task 3.1 pins, tasks 3.3/3.4 move): the card's whole-entity ✨
(``entityGenerateButton``) and the event's (``eventEntityAiButton``) left
the «Название» row for this slot — objectName, accessible name
(«Сгенерировать: <цель>»), the aiState string and the gate facet (clickable
while disabled) are re-pinned here UNCHANGED; only their parent moved. The
name rows therefore carry exactly the single name-generation button.

The ✨ buttons are never clicked here: generation would reach the real LLM
endpoint — the contract pinned is placement, name and state only.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPointF, QUrl
from PySide6.QtGui import QAccessible
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQuickWidgets import QQuickWidget

from app.presentation.qml.engine import setup_qml_shell
from app.presentation.theme.qml_palette import QmlPalette
from app.presentation.views.entity_card_dialog import EntityCardDialog
from app.presentation.views.event_dialog import EventDialog
from tests.presentation.qml_helpers import find_item, walk_items
from tests.ui.test_theme_grab import make_runtime

# The отступ contract: space.sm is "8px" in both themes and its pinned QML
# fallback is the same 8 — the gap therefore measures 8.0 skinned or off-skin.
SPACE_SM = 8.0
# space.md, the header's own horizontal inset (close-button edge margin).
SPACE_MD = 16.0

ACTIONS_SCENE = """
import QtQuick
import nri.components

Item {
    id: probeRoot
    objectName: "sheetHeaderActionProbe"
    implicitWidth: 360
    implicitHeight: 120

    property int closes: 0

    ThemeSheetHeader {
        objectName: "probeHeader"
        title: "Карточка: Персонаж"
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        onCloseRequested: probeRoot.closes += 1

        ThemeIconButton {
            objectName: "probeAction"
            text: "✨"
            Accessible.name: "Сгенерировать: Персонаж"
        }
    }
}
"""


def load_actions_probe(qtbot, qapp, tmp_path, palette=None):
    """The header-with-action probe on the shared shell engine; ``palette=None``
    is the off-skin run (no islandPalette in the context chain)."""
    if QQuickStyle.name() != "Basic":
        QQuickStyle.setStyle("Basic")
    scene = tmp_path / "sheet_header_actions.qml"
    scene.write_text(ACTIONS_SCENE, encoding="utf-8")
    runtime = make_runtime(tmp_path, "dark")
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


def _scene_rect(item):
    top_left = item.mapToScene(QPointF(0, 0))
    return top_left.x(), top_left.y(), item.width(), item.height()


def _ancestor_names(item) -> list[str]:
    names: list[str] = []
    while item is not None:
        if item.objectName():
            names.append(item.objectName())
        item = item.parentItem()
    return names


def _assert_seated_in_slot(widget, button_name: str, header_name: str) -> None:
    """The order pin for one island: заголовок → действие (space.sm off the
    title box, one center with it) → свободный разрыв → закрытие у края."""
    title = find_item(widget, "sheetHeaderTitle")
    action = find_item(widget, button_name)
    close = find_item(widget, "sheetHeaderClose")

    # The slot host owns the action as a visual child (the tree walk and the
    # accessibility address see it there), inside the island's own header.
    assert action.parentItem().objectName() == "sheetHeaderAction"
    assert header_name in _ancestor_names(action)
    assert header_name in _ancestor_names(title)

    tx, ty, tw, th = _scene_rect(title)
    ax, ay, aw, ah = _scene_rect(action)
    cx, cy, cw, ch = _scene_rect(close)

    # Fixed offset straight after the title text, on the title's line.
    assert ax - (tx + tw) == pytest.approx(SPACE_SM, abs=0.5)
    assert abs((ay + ah / 2) - (ty + th / 2)) <= 1.0
    # The title keeps its natural, un-clipped width (nothing squeezed it).
    assert tw == pytest.approx(title.property("implicitWidth"), abs=0.5)
    # заголовок → действие → … → закрытие: the close sits right of the action,
    # and the free slack of the row lies between them.
    assert tx < ax
    assert cx > ax + aw
    # The close stayed glued to the opposite edge of the row.
    assert (widget.width() - (cx + cw)) == pytest.approx(SPACE_MD, abs=0.5)


def _accessible(widget, object_name: str):
    iface = QAccessible.queryAccessibleInterface(find_item(widget, object_name))
    assert iface is not None, f"no accessibility interface on {object_name!r}"
    return iface


# ── 3.2: the component's slot ─────────────────────────────────────────────────


def test_slot_places_the_action_after_the_title_before_the_close(
    qtbot, qapp, tmp_path
):
    widget = load_actions_probe(
        qtbot, qapp, tmp_path, QmlPalette(make_runtime(tmp_path, "dark"))
    )
    assert widget.errors() == []
    _assert_seated_in_slot(widget, "probeAction", "probeHeader")


def test_slot_close_press_contract_survives_the_action(qtbot, qapp, tmp_path):
    """The slot turned the header into a host with the close signal untouched
    (design Д3): one accessibility Press still emits closeRequested once."""
    widget = load_actions_probe(
        qtbot, qapp, tmp_path, QmlPalette(make_runtime(tmp_path, "dark"))
    )
    root = widget.rootObject()

    actions = _accessible(widget, "sheetHeaderClose").actionInterface()
    assert "Press" in actions.actionNames()
    actions.doAction("Press")
    assert int(root.property("closes")) == 1


@pytest.mark.parametrize("mode", ["skinned", "offskin"])
def test_order_holds_with_and_without_the_theme(qtbot, qapp, tmp_path, mode):
    widget = load_actions_probe(
        qtbot, qapp, tmp_path,
        QmlPalette(make_runtime(tmp_path, "dark")) if mode == "skinned" else None,
    )
    assert widget.errors() == []
    _assert_seated_in_slot(widget, "probeAction", "probeHeader")


# ── 3.1 (usage pins) + 3.3 (the move): the two islands ────────────────────────


def test_card_wave_button_stands_in_the_header_slot(qtbot):
    dialog = EntityCardDialog(None, "character")
    qtbot.addWidget(dialog)
    dialog.show()

    # The localized title first (NRI-0018 Д4): the slot hangs off «Персонаж».
    assert dialog.windowTitle() == "Карточка: Персонаж"
    _assert_seated_in_slot(dialog.quick, "entityGenerateButton", "entitySheetHeader")

    # The unchanged button contract rides the new host (task 3.1): objectName
    # addressed fine above, role/name and the proxy-backed state facet intact.
    iface = _accessible(dialog.quick, "entityGenerateButton")
    assert iface.role() == QAccessible.Role.Button
    assert iface.text(QAccessible.Name) == "Сгенерировать: Персонаж"
    button = find_item(dialog.quick, "entityGenerateButton")
    assert button.property("fieldLabel") == "Персонаж"
    assert button.property("aiState") == "disabled"  # off: assistant unconfigured
    assert bool(button.property("enabled")) is True  # gate facet: click shows hint


def test_event_wave_button_stands_in_the_header_slot(qtbot):
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    dialog.show()

    _assert_seated_in_slot(dialog.quick, "eventEntityAiButton", "eventSheetHeader")

    iface = _accessible(dialog.quick, "eventEntityAiButton")
    assert iface.role() == QAccessible.Role.Button
    assert iface.text(QAccessible.Name) == "Сгенерировать: Событие"
    button = find_item(dialog.quick, "eventEntityAiButton")
    assert button.property("fieldLabel") == "Событие"
    assert button.property("aiState") == "disabled"
    assert bool(button.property("enabled")) is True


def _ai_buttons_on_the_row(widget, field_name: str) -> set[str]:
    """Names of the visible ✨ AI buttons whose row is the field's row:
    shared vertical centre and a start right of the field's right edge."""
    field = find_item(widget, field_name)
    fx, fy, fw, fh = _scene_rect(field)
    found: set[str] = set()
    for item in walk_items(widget.rootObject()):
        if item.property("aiState") is None or item.property("text") != "✨":
            continue
        if not item.property("visible"):
            continue
        bx, by, bw, bh = _scene_rect(item)
        if bx >= fx + fw - 1 and abs((by + bh / 2) - (fy + fh / 2)) <= 2:
            found.add(item.objectName())
    return found


def test_card_name_row_carries_only_the_name_generation(qtbot):
    dialog = EntityCardDialog(None, "character")
    qtbot.addWidget(dialog)
    dialog.show()

    # The whole-entity wave left the row for the header (qml-shell «Строка
    # названия разгружена»); only the field's own ✨ stayed in it.
    assert _ai_buttons_on_the_row(dialog.quick, "entityNameField") == {
        "entityNameAiButton"
    }


def test_event_name_row_carries_only_the_name_generation(qtbot):
    dialog = EventDialog(None)
    qtbot.addWidget(dialog)
    dialog.show()

    assert _ai_buttons_on_the_row(dialog.quick, "eventNameField") == {
        "eventNameAiButton"
    }
