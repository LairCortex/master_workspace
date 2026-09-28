from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QImage
from PySide6.QtQml import QQmlEngine
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
    found = _items(root, name)
    assert len(found) == 1, name
    return found[0]


def _items(root, name):
    found, pending = [], [root]
    while pending:
        item = pending.pop()
        if item.objectName() == name:
            found.append(item)
        pending.extend(item.childItems())
    return found


def _click(panel, item, *, double=False):
    """A synthetic left click on the item's right side — away from the row's
    left-hand picture, which owns its own MouseArea (the existing picture
    test addresses that one directly)."""
    scene = item.mapToScene(QPointF(item.width() - 10, item.height() / 2))
    pos = QPoint(round(scene.x()), round(scene.y()))
    if double:
        QTest.mouseDClick(panel.quick, Qt.MouseButton.LeftButton, pos=pos)
    else:
        QTest.mouseClick(panel.quick, Qt.MouseButton.LeftButton, pos=pos)


def _visible_flags(panel, name):
    items = _items(panel.quick.rootObject(), name)
    items.sort(key=lambda i: i.mapToScene(QPointF(0, 0)).y())
    return [bool(i.property("visible")) for i in items]


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
    # NRI-0015 (M1): the detail island shows the tab tooltips now, so its
    # private context carries the island's own tooltip bridge (the
    # timeline/editor pattern).
    assert context.contextProperty("tooltipBridge") is panel._tooltip_bridge


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


# ── change nri-0022-entity-preview, tasks 3.1/3.2: the single-click selection ──


def test_single_click_selects_washes_and_relays_without_opening_the_card(qtbot):
    panel = DetailPanel(SimpleNamespace())
    qtbot.addWidget(panel)
    panel.show_event(_event(_entity()))
    panel.resize(500, 500)
    panel.show()
    qtbot.wait(20)

    selected, activated = [], []
    panel.entity_selected.connect(lambda *args: selected.append(args))
    panel.entity_clicked.connect(lambda *args: activated.append(args))
    # Off the bat no row wears the wash (the role is False for fresh rows).
    assert _visible_flags(panel, "detailRowWash") == [False]

    _click(panel, _item(panel.quick.rootObject(), "detailEntityRow"))

    # Task 3.1: the single click is the selection — the relay fired, the
    # card signal stayed silent, the row's accent wash is on with the
    # radius.sm rounding the card itself carries (same token, task check).
    assert selected == [("organization", 4)]
    assert activated == []
    row = _item(panel.quick.rootObject(), "detailEntityRow")
    assert bool(row.property("rowSelected")) is True
    wash = _item(panel.quick.rootObject(), "detailRowWash")
    assert bool(wash.property("visible")) is True
    assert wash.property("radius") == row.property("radius")


def test_second_click_moves_the_wash_to_the_clicked_row(qtbot):
    # The mutual removal of task 3.1 on the live island: two rows, one wash.
    def entity(entity_id, name):
        row = _entity()
        row.id = entity_id
        row.name = name
        return row

    event = _event()
    event.organizations = [entity(4, "Орден"), entity(5, "Гильдия")]
    panel = DetailPanel(SimpleNamespace())
    qtbot.addWidget(panel)
    panel.show_event(event)
    panel.resize(500, 500)
    panel.show()
    qtbot.wait(20)

    rows = _items(panel.quick.rootObject(), "detailEntityRow")
    rows.sort(key=lambda i: i.mapToScene(QPointF(0, 0)).y())
    _click(panel, rows[0])
    assert _visible_flags(panel, "detailRowWash") == [True, False]

    _click(panel, rows[1])
    assert _visible_flags(panel, "detailRowWash") == [False, True]


def test_picture_click_opens_viewer_without_selecting(qtbot, monkeypatch, tmp_path):
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

    panel = DetailPanel(SimpleNamespace())
    qtbot.addWidget(panel)
    panel.show_event(_event(_entity()))
    panel.resize(500, 500)
    panel.show()
    qtbot.wait(20)

    selected = []
    panel.entity_selected.connect(lambda *args: selected.append(args))

    # The picture keeps its own gesture (task 3.1, design D3 risk row): its
    # MouseArea accepts the press above the row's, so the viewer opens and
    # the row is NOT selected.
    _click(panel, _item(panel.quick.rootObject(), "detailImageMouseArea"))

    assert opened[-1] == "exec"
    assert selected == []
    assert _visible_flags(panel, "detailRowWash") == [False]


def test_tab_switch_hides_wash_but_remembers_the_selection(qtbot):
    # Task 3.2: the wash is screen state — switching tabs hides it — while
    # the VM still remembers the last selection (the preview keeps showing
    # it; the signal half of that rule is the group-5 wiring).
    panel = DetailPanel(SimpleNamespace())
    qtbot.addWidget(panel)
    panel.show_event(_event(_entity()))
    panel.resize(500, 500)
    panel.show()
    qtbot.wait(20)

    _click(panel, _item(panel.quick.rootObject(), "detailEntityRow"))
    assert _visible_flags(panel, "detailRowWash") == [True]

    panel.quick.rootObject().setProperty("currentTab", 1)
    qtbot.wait(20)

    # The role itself answers False — the hide is the VM's, not the tab pane
    # merely putting the row out of sight.
    assert bool(
        _item(panel.quick.rootObject(), "detailEntityRow").property("rowSelected")
    ) is False
    assert _visible_flags(panel, "detailRowWash") == [False]
    assert panel.vm.last_selected == ("organization", 4)


def test_empty_detail_panel_shows_the_action_hint(qtbot):
    # NRI-0015 (M4, spec «Пустая панель деталей объясняет себя»): no row
    # picked -> the muted hint names the next action; an opened event replaces
    # it, and clearing the selection brings it back.
    panel = DetailPanel(SimpleNamespace())
    qtbot.addWidget(panel)
    panel.resize(500, 500)
    panel.show()
    qtbot.wait(20)

    hint = _item(panel.quick.rootObject(), "detailEmptyHint")
    assert hint.property("visible") is True
    assert hint.property("text") == "Выберите строку — тут появятся детали"
    # same face as the timeline hint: the library's muted HintText
    assert hint.metaObject().className().startswith("HintText")

    panel.show_event(_event(_entity()))
    assert hint.property("visible") is False

    panel.clear()
    assert hint.property("visible") is True


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
