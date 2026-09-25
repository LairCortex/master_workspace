"""Accessibility contract of the detail-panel island (change
nri-0012-qml-accessibility, task 2.2).

The card row and its picture carry the design-map contract on the production
island (DetailPanel + real DetailPanelViewModel, the island-test fixtures):
the row is a ListItem named by the entity name whose single Press is the
double-click open (`activate` → the facade's ``entity_clicked``; D3), the
picture is the «open the image» Button driving ``requestImage`` (the name
falls back to «Изображение» when the entity has none). NRI-0015 (task 1.1)
moved the tabs onto the registry short caption; the live tab name/description
pin lives in ``tests/presentation/test_detail_panel_island.py`` and the
caption/annotation unit pins in ``tests/presentation/test_detail_tabs_labels.py``.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QAccessible, QImage
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

        def exec(self):
            opened.append("exec")

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


def test_card_row_is_list_item_named_by_entity_with_open_description(qtbot):
    panel = _panel(qtbot)
    row = island_rows(panel.quick, "detailEntityRow")[0]

    iface = accessible_of(row)
    assert iface.role() == QAccessible.Role.ListItem
    assert iface.text(QAccessible.Name) == "Орден"
    assert iface.text(QAccessible.Description) == "Открывает карточку"


def test_row_press_opens_the_card_through_activate(qtbot):
    panel = _panel(qtbot)
    row = island_rows(panel.quick, "detailEntityRow")[0]
    clicked = track(panel.entity_clicked)

    press(row)

    # The very signal the mouse double-click drives: the card opens with one
    # accessibility Press (design D3), no selection step.
    assert clicked == [("organization", 4)]


def test_picture_is_image_button_pressing_it_opens_the_viewer(qtbot, image_monkey):
    panel = _panel(qtbot)
    image = find_item(panel.quick, "detailEntityImage")

    iface = accessible_of(image)
    assert iface.role() == QAccessible.Role.Button
    assert iface.text(QAccessible.Name) == "Орден"
    assert iface.text(QAccessible.Description) == "Открыть изображение"

    press(image)
    assert image_monkey[-1] == "exec"


def test_picture_without_entity_name_falls_back_to_image(qtbot, image_monkey):
    panel = _panel(qtbot, entity_name="")
    row = island_rows(panel.quick, "detailEntityRow")[0]
    image = find_item(panel.quick, "detailEntityImage")

    assert row.property("entityName") == ""
    assert accessible_of(image).text(QAccessible.Name) == "Изображение"
