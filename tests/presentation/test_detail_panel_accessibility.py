"""Accessibility contract of the detail-panel island (change
nri-0012-qml-accessibility, task 2.2; the selection posture of the row comes
from change nri-0022-entity-preview, tasks 3.1/3.3).

The card row and its picture carry the design-map contract on the production
island (DetailPanel + real DetailPanelViewModel, the island-test fixtures):
the row is a ListItem named by the entity name whose single Press is the
single selection (`select` → the facade's ``entity_selected``, task 3.1) and
whose Enter on the focused row is the card open (`activate` → the facade's
``entity_clicked``, task 3.3), the picture is the «open the image» Button
driving ``requestImage`` (the name falls back to «Изображение» when the
entity has none). NRI-0015 (task 1.1) moved the tabs onto the registry short
caption; the live tab name/description pin lives in
``tests/presentation/test_detail_panel_island.py`` and the caption/annotation
unit pins in ``tests/presentation/test_detail_tabs_labels.py``.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QAccessible, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import app.presentation.viewmodels.detail_panel_view_model as detail_vm_module
from app.presentation.views import detail_panel as detail_module
from app.presentation.views.detail_panel import DetailPanel
from tests.presentation.qml_helpers import (
    find_item,
    island_rows,
    track,
)


def _event(entity=None):
    return SimpleNamespace(
        id=1,
        name="Событие",
        start_date=date(1300, 2, 3),
        end_date=None,
        organizations=[] if entity is None else [entity],
        characters=[],
        items=[],
        locations=[],
    )


def _entity(name="Орден"):
    return SimpleNamespace(
        id=4,
        name=name,
        rating=8,
        description=None,
        tasks=None,
        characters=[],
        organizations=[],
        items=[],
        locations=[],
        image_ref=None,
    )


@pytest.fixture
def image_monkey(monkeypatch, tmp_path):
    """The island-test image plumbing: a real preview file so the row's
    imageSource is non-empty and the picture branch is live."""
    opened = []

    class Viewer:
        def __init__(self, original, preview, parent=None, theme=None):
            opened.append((original, preview, parent, theme))

    image_path = tmp_path / "preview.png"
    image = QImage(20, 20, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.red)
    assert image.save(str(image_path))
    monkeypatch.setattr(detail_module, "ImageViewerDialog", Viewer)
    monkeypatch.setattr(detail_module, "load_entity_original", lambda entity: "original")
    monkeypatch.setattr(
        detail_module, "load_entity_preview", lambda entity, slot_size: "preview"
    )
    monkeypatch.setattr(
        detail_vm_module, "resolve_preview_path", lambda entity: image_path
    )
    return opened


def _panel(qtbot, entity_name="Орден") -> DetailPanel:
    panel = DetailPanel(SimpleNamespace())
    qtbot.addWidget(panel)
    panel.show_event(_event(_entity(entity_name)))
    panel.resize(500, 500)
    panel.show()
    QApplication.processEvents()
    return panel


def accessible_of(item):
    iface = QAccessible.queryAccessibleInterface(item)
    assert iface is not None, f"no accessibility interface on {item!r}"
    return iface


def press(item) -> None:
    actions = accessible_of(item).actionInterface()
    assert "Press" in actions.actionNames()
    actions.doAction("Press")


def test_card_row_is_list_item_named_by_entity_with_selection_description(qtbot):
    # NRI-0022 task 7.1 (spec «Строка деталей описывает выбор»): the raw tree
    # of the row reads the selection wording — the description followed the
    # Press action when the card moved to Enter/double-click (task 3.1).
    panel = _panel(qtbot)
    row = island_rows(panel.quick, "detailEntityRow")[0]

    iface = accessible_of(row)
    assert iface.role() == QAccessible.Role.ListItem
    assert iface.text(QAccessible.Name) == "Орден"
    assert iface.text(QAccessible.Description) == "Выбирает сущность"


def test_row_press_selects_instead_of_opening_the_card(qtbot):
    panel = _panel(qtbot)
    row = island_rows(panel.quick, "detailEntityRow")[0]
    selected = track(panel.entity_selected)
    activated = track(panel.entity_clicked)

    press(row)

    # NRI-0022 task 3.1: the single activation runs the single selection —
    # the very step the single mouse click drives (spec qml-accessibility
    # «Строка сущности в деталях выбирается активацией»); the card path lives
    # on the mouse double-click and on Enter (test below), not on Press.
    assert selected == [("organization", 4)]
    assert activated == []
    assert row.property("rowSelected") is True


def test_enter_on_focused_row_opens_the_editable_card(qtbot):
    # NRI-0022 task 3.3: rows wear activeFocusOnTab, so the accessibility
    # SetFocus lands on the row itself; Return then bubbles to the list's
    # Keys.onReturnPressed and activates this very row through the VM — the
    # facade's entity_clicked, the same signal the mouse double-click drives.
    panel = _panel(qtbot)
    row = island_rows(panel.quick, "detailEntityRow")[0]
    activated = track(panel.entity_clicked)
    selected = track(panel.entity_selected)

    actions = accessible_of(row).actionInterface()
    assert "SetFocus" in actions.actionNames()
    actions.doAction("SetFocus")
    QApplication.processEvents()
    assert row.property("activeFocus") is True

    QTest.keyClick(panel.quick, Qt.Key.Key_Return)

    assert activated == [("organization", 4)]
    assert selected == []


def test_picture_is_image_button_pressing_it_opens_the_viewer(qtbot, image_monkey):
    panel = _panel(qtbot)
    image = find_item(panel.quick, "detailEntityImage")
    iface = accessible_of(image)
    assert iface.role() == QAccessible.Role.Button
    assert iface.text(QAccessible.Name) == "Орден"
    assert iface.text(QAccessible.Description) == "Открыть изображение"

    # Task 2.5: the press hands the viewer sheet to the connector's channel
    # (exec() is gone from this path).
    requested: list = []
    panel.sheet_requested.connect(requested.append)

    press(image)
    assert len(requested) == 1
    assert len(image_monkey) == 1


def test_picture_without_entity_name_falls_back_to_image(qtbot, image_monkey):
    panel = _panel(qtbot, entity_name="")
    row = island_rows(panel.quick, "detailEntityRow")[0]
    image = find_item(panel.quick, "detailEntityImage")

    assert row.property("entityName") == ""
    assert accessible_of(image).text(QAccessible.Name) == "Изображение"
