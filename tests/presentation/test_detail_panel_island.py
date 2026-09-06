from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QImage
from PySide6.QtQml import QQmlEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest

import app.presentation.viewmodels.detail_panel_view_model as detail_vm_module
from app.infrastructure.ui_prefs.config import UiPrefsManager
from app.presentation.theme.compiler import tokens_file_path
from app.presentation.theme.runtime import ThemeRuntime
from app.presentation.views import detail_panel as detail_module
from app.presentation.views.detail_panel import DetailPanel


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


def _entity():
    return SimpleNamespace(
        id=4,
        name="Орден",
        rating=8,
        description=None,
        tasks=None,
        characters=[],
        organizations=[],
        items=[],
        locations=[],
        image_ref=None,
    )


def _item(root, name):
    pending = [root]
    while pending:
        item = pending.pop()
        if item.objectName() == name:
            return item
        pending.extend(item.childItems())
    raise AssertionError(name)


def test_detail_root_contract_and_minimal_child_context(qtbot):
    panel = DetailPanel(SimpleNamespace())
    qtbot.addWidget(panel)
    panel.resize(500, 500)
    panel.show()
    qtbot.wait(20)

    root = panel.quick.rootObject()
    assert root.objectName() == "detailPanelRoot"
    for name in (
        "detailTitle",
        "detailDate",
        "detailTabBar",
        "detailStack",
        "organizationList",
        "characterList",
        "itemList",
        "locationList",
    ):
        _item(root, name)

    context = QQmlEngine.contextForObject(root)
    assert context.contextProperty("detailPanelVm") is panel.vm
    assert context.contextProperty("islandPalette") is panel._palette
    assert context.contextProperty("tooltipBridge") is None


def test_detail_rows_activate_and_image_click_reach_facade(
    qtbot, monkeypatch, tmp_path
):
    opened = []

    class Viewer:
        def __init__(self, original, preview, parent=None, theme=None):
            opened.append((original, preview, parent, theme))

        def exec(self):
            opened.append("exec")

    monkeypatch.setattr(detail_module, "ImageViewerDialog", Viewer)
    monkeypatch.setattr(detail_module, "load_entity_original", lambda entity: "original")
    monkeypatch.setattr(
        detail_module, "load_entity_preview", lambda entity, slot_size: "preview"
    )
    image_path = tmp_path / "preview.png"
    image = QImage(20, 20, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.red)
    assert image.save(str(image_path))
    monkeypatch.setattr(
        detail_vm_module, "resolve_preview_path", lambda entity: image_path
    )

    entity = _entity()
    panel = DetailPanel(SimpleNamespace())
    qtbot.addWidget(panel)
    panel.show_event(_event(entity))
    panel.resize(500, 500)
    panel.show()
    qtbot.wait(20)

    with qtbot.waitSignal(panel.entity_clicked) as selected:
        row = _item(panel.quick.rootObject(), "detailEntityRow")
        scene = row.mapToScene(QPointF(row.width() - 10, row.height() / 2))
        QTest.mouseDClick(
            panel.quick,
            Qt.MouseButton.LeftButton,
            pos=QPoint(round(scene.x()), round(scene.y())),
        )
    assert selected.args == ["organization", entity.id]

    image_mouse = _item(panel.quick.rootObject(), "detailImageMouseArea")
    scene = image_mouse.mapToScene(
        QPointF(image_mouse.width() / 2, image_mouse.height() / 2)
    )
    QTest.mouseClick(
        panel.quick,
        Qt.MouseButton.LeftButton,
        pos=QPoint(round(scene.x()), round(scene.y())),
    )
    assert opened[-1] == "exec"
    assert opened[0][:2] == ("original", "preview")


def test_live_retheme_keeps_tab_and_scroll_state(qtbot, tmp_path):
    runtime = ThemeRuntime(
        prefs=UiPrefsManager(tmp_path / "ui.json"),
        tokens_path=tokens_file_path(),
    )
    panel = DetailPanel(SimpleNamespace(), theme=runtime)
    qtbot.addWidget(panel)
    panel.show_event(_event(_entity()))
    panel.resize(500, 500)
    panel.show()
    qtbot.wait(20)
    root = panel.quick.rootObject()
    root.setProperty("currentTab", 2)
    root.setProperty("organizationContentY", 11.0)

    assert runtime.toggle() is True

    assert root.property("currentTab") == 2
    assert root.property("organizationContentY") == 11.0


def test_detail_island_teardown_is_deferred(qtbot):
    panel = DetailPanel(SimpleNamespace())
    qtbot.addWidget(panel)
    assert panel.quick.rootObject() is not None
    panel.close()
    assert panel.quick.rootObject() is not None
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qtbot.wait(1)
    assert panel.quick.rootObject() is None
    assert panel.quick.source() == QUrl()
