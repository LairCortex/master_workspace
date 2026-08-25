"""Widget tests for the character sheet editor UI (tasks 6.1–6.6)."""
import asyncio
from unittest.mock import AsyncMock

import pytest
from PySide6.QtCore import QEvent, QPointF, QPoint, Qt
from PySide6.QtGui import (
    QCloseEvent,
    QMouseEvent,
    QPainter,
    QWheelEvent,
    QImage,
    QKeyEvent,
)
from pypdf import PdfReader
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QMessageBox,
    QPushButton,
    QStyleOptionGraphicsItem,
    QVBoxLayout,
    QWidget,
)

from app.domain.entities.character_sheet import SheetField
from app.domain.enums.field_type import FieldType
from app.domain.enums.sheet_orientation import SheetOrientation
from app.presentation.viewmodels.character_sheet_viewmodel import CharacterSheetViewModel
from app.presentation.views.character_sheet import editor_dialog as editor_module
from app.presentation.views.character_sheet.canvas_items import FieldItem
from app.presentation.views.character_sheet.canvas_view import (
    MAX_ZOOM,
    MIN_ZOOM,
    SheetCanvas,
    SheetCanvasView,
)
from app.presentation.views.character_sheet.editor_dialog import CharacterSheetEditorDialog
from app.presentation.views.character_sheet.items_palette import ItemsPalette
from app.presentation.views.character_sheet.pages_dialog import PagesDialog
from app.presentation.views.character_sheet.properties_panel import PropertiesPanel


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def vm(qapp):
    viewmodel = CharacterSheetViewModel(AsyncMock())
    viewmodel.create_new("Лист")
    return viewmodel


def add_field_id(vm, field_type=FieldType.SHORT_TEXT, page=0, x=100.0, y=100.0, **kw):
    return vm.add_field(field_type, page, x, y, **kw).id


# ── helpers ────────────────────────────────────────────────────────────────


def make_widget_view(canvas: SheetCanvas):
    return SheetCanvasView(canvas)


def paint_call(item):
    """Run an item's paint() into a QImage (covers all paint branches)."""
    image = QImage(400, 400, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    item.paint(painter, QStyleOptionGraphicsItem(), None)
    painter.end()


def mouse_event(event_type, local: QPointF, button, buttons=Qt.MouseButton.NoButton):
    return QMouseEvent(
        event_type, local, local, QPointF(0, 0),
        button, buttons, Qt.KeyboardModifier(0),
    )


def drag_item(item, new_pos: QPointF) -> None:
    """Simulate a completed left-button drag: press → move → release."""
    item.setSelected(True)
    item.mousePressEvent(mouse_event(QEvent.Type.MouseButtonPress, QPointF(0, 0),
                                      Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton))
    item.setPos(new_pos)
    item._drag_moved = True
    item.mouseReleaseEvent(mouse_event(QEvent.Type.MouseButtonRelease, QPointF(0, 0),
                                       Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton))


# ── 6.1 canvas: pages, grid, zoom ─────────────────────────────────────────


class TestCanvas:
    def test_refresh_creates_pages_and_field_items(self, vm):
        add_field_id(vm, FieldType.SHORT_TEXT, x=100.0, y=100.0)
        add_field_id(vm, FieldType.HEADING, x=300.0, y=200.0)
        vm.add_page()
        canvas = SheetCanvas(vm)
        canvas.refresh()
        assert len(canvas._page_items) == 2
        assert canvas._page_items[0].size.width() == 841.89   # landscape A4
        assert canvas._page_items[1].pos().y() == 40 + 595.28 + 40
        fields = [c for c in canvas._page_items[0].childItems() if isinstance(c, FieldItem)]
        assert len(fields) == 2
        # z-order = list order
        assert fields[0].zValue() == 0 and fields[1].zValue() == 1
        assert fields[0].pos() == QPointF(100, 100)

    def test_refresh_preserves_selection(self, vm):
        add_field_id(vm)
        canvas = SheetCanvas(vm)
        canvas.refresh()
        item = [c for c in canvas._page_items[0].childItems()
                if isinstance(c, FieldItem)][0]
        assert item.isSelected()  # the viewmodel's selection is restored

    def test_page_item_paint_with_and_without_grid(self, vm):
        canvas = SheetCanvas(vm)
        canvas.refresh()
        page = canvas._page_items[0]
        paint_call(page)
        canvas.set_grid(True, 20.0)
        paint_call(page)
        canvas.set_grid(True, 0.0)  # degenerate step: grid skipped
        paint_call(page)
        canvas.set_grid(False, 20.0)
        paint_call(page)

    def test_page_index_at(self, vm, qtbot):
        canvas = SheetCanvas(vm)
        view = make_widget_view(canvas)
        qtbot.addWidget(view)
        canvas.refresh()
        assert canvas.page_index_at(QPointF(200, 200)) == 0
        assert canvas.page_index_at(QPointF(9999, 9999)) is None

    def test_page_index_at_view_center_nearest(self, vm, qtbot):
        canvas = SheetCanvas(vm)
        view = make_widget_view(canvas)
        qtbot.addWidget(view)
        view.resize(120, 80)
        canvas.refresh()
        # viewport at (0,0) scene coords: center is inside page 1
        assert canvas.page_index_at_view_center(view) == 0
        # far zoomed-out: nothing under the center → still a valid page index
        view.resetTransform()
        view.scale(0.01, 0.01)
        assert 0 <= canvas.page_index_at_view_center(view) < 2

    def test_zoom_wheel_and_clamp(self, vm, qapp):
        canvas = SheetCanvas(vm)
        view = make_widget_view(canvas)
        view.resize(400, 300)
        canvas.refresh()

        def wheel(delta: int):
            event = QWheelEvent(
                QPointF(20, 20), QPointF(0, 0), QPoint(0, delta), QPoint(0, delta * 120),
                Qt.MouseButton.NoButton, Qt.KeyboardModifier.ControlModifier,
                Qt.ScrollPhase.NoScrollPhase, False,
            )
            view.wheelEvent(event)
            return view.transform().m11()

        assert round(wheel(1), 4) > 1.0
        while view.transform().m11() < MAX_ZOOM:
            wheel(1)
        assert view.transform().m11() <= MAX_ZOOM
        while view.transform().m11() > MIN_ZOOM:
            wheel(-1)
        assert view.transform().m11() >= MIN_ZOOM

    def test_wheel_without_ctrl_is_plain_scroll(self, vm, qapp):
        canvas = SheetCanvas(vm)
        view = make_widget_view(canvas)
        view.resize(400, 300)
        canvas.refresh()
        before = view.transform().m11()
        event = QWheelEvent(
            QPointF(20, 20), QPointF(0, 0), QPoint(0, 120), QPoint(0, 120),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier(0),
            Qt.ScrollPhase.NoScrollPhase, False,
        )
        view.wheelEvent(event)
        assert view.transform().m11() == before  # no zoom

    def test_zoom_by_and_fit(self, vm, qapp):
        canvas = SheetCanvas(vm)
        view = make_widget_view(canvas)
        view.resize(400, 300)
        canvas.refresh()
        view.fit_to_window()
        fitted = view.transform().m11()
        assert fitted != 1.0
        view.zoom_by(2.0)
        assert view.transform().m11() > fitted
        for _ in range(50):
            view.zoom_by(3.0)
        assert view.transform().m11() <= MAX_ZOOM

    def test_space_pan(self, vm, qapp):
        canvas = SheetCanvas(vm)
        view = make_widget_view(canvas)
        view.resize(400, 300)
        canvas.refresh()
        view.fit_to_window()

        key_press = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier(0))
        key_release = QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Space, Qt.KeyboardModifier(0))
        view.keyPressEvent(key_press)
        assert view._space_pressed is True

        view.mousePressEvent(mouse_event(QEvent.Type.MouseButtonPress, QPointF(100, 100),
                                          Qt.MouseButton.LeftButton,
                                          Qt.MouseButton.LeftButton))
        view.mouseMoveEvent(mouse_event(QEvent.Type.MouseMove, QPointF(120, 130),
                                        Qt.MouseButton.NoButton,
                                        Qt.MouseButton.LeftButton))
        view.mouseReleaseEvent(mouse_event(QEvent.Type.MouseButtonRelease, QPointF(120, 130),
                                           Qt.MouseButton.LeftButton,
                                           Qt.MouseButton.NoButton))
        view.keyReleaseEvent(key_release)
        assert view._space_pressed is False
        assert view._panning is False

    def test_plain_click_without_space_goes_to_scene(self, vm, qapp):
        canvas = SheetCanvas(vm)
        view = make_widget_view(canvas)
        view.resize(400, 300)
        canvas.refresh()
        view.mousePressEvent(mouse_event(QEvent.Type.MouseButtonPress, QPointF(500, 500),
                                          Qt.MouseButton.LeftButton,
                                          Qt.MouseButton.LeftButton))
        view.mouseReleaseEvent(mouse_event(QEvent.Type.MouseButtonRelease, QPointF(500, 500),
                                           Qt.MouseButton.LeftButton,
                                           Qt.MouseButton.NoButton))
        assert view._panning is False


# ── 6.2 FieldItem: drag, resize, paint branches ───────────────────────────


class TestFieldItem:
    def make_vm_field(self, vm, **kw) -> SheetField:
        add_field_id(vm, **kw)
        return vm.template.pages[0].fields[0]

    def test_paint_branches(self, vm):
        for field_type, kw in (
            (FieldType.SHORT_TEXT, dict()),
            (FieldType.NUMBER, dict(min_value=1, max_value=9)),
            (FieldType.CHECKBOX, dict(w=20.0, h=20.0, initial_checked=True)),
            (FieldType.CHECKBOX, dict(w=20.0, h=20.0, initial_checked=False)),
            (FieldType.DROPDOWN, dict(options=["А", "Б"])),
            (FieldType.DATE, dict()),
            (FieldType.LONG_TEXT, dict(h=80.0)),
            (FieldType.PORTRAIT, dict(w=120.0, h=150.0, label="")),
            (FieldType.HEADING, dict(label="ЗАГОЛОВОК", font_size=16.0)),
            (FieldType.STATIC_TEXT, dict(label="строка 1\nстрока 2", label_2="x")),
        ):
            if "label_2" in kw:
                kw.pop("label_2")
            vm2 = CharacterSheetViewModel(AsyncMock())
            vm2.create_new("Т")
            f = vm2.add_field(field_type, 0, 50.0, 50.0, **kw)
            item = FieldItem(f)
            paint_call(item)

    def test_drag_commits_new_position(self, vm, qtbot):
        vm.set_snap(False)
        field = self.make_vm_field(vm)
        canvas = SheetCanvas(vm)
        view = make_widget_view(canvas)
        qtbot.addWidget(view)
        canvas.refresh()
        item = [c for c in canvas._page_items[0].childItems()
                if isinstance(c, FieldItem)][0]
        item._viewmodel = vm  # canvas wires this in refresh
        drag_item(item, QPointF(250, 350))
        assert (field.x, field.y) == (250.0, 350.0)
        assert vm.can_undo

    def test_plain_click_does_not_snapshot(self, vm):
        add_field_id(vm)
        canvas = SheetCanvas(vm)
        canvas.refresh()
        item = [c for c in canvas._page_items[0].childItems()
                if isinstance(c, FieldItem)][0]
        snapshots = len(vm._undo)
        item.mousePressEvent(mouse_event(QEvent.Type.MouseButtonPress, QPointF(0, 0),
                                          Qt.MouseButton.LeftButton,
                                          Qt.MouseButton.LeftButton))
        item.mouseReleaseEvent(mouse_event(QEvent.Type.MouseButtonRelease, QPointF(0, 0),
                                           Qt.MouseButton.LeftButton,
                                           Qt.MouseButton.NoButton))
        # a plain click must not create an undo entry
        assert len(vm._undo) == snapshots

    def test_unselected_move_not_flagged(self, vm):
        add_field_id(vm)
        canvas = SheetCanvas(vm)
        canvas.refresh()
        item = [c for c in canvas._page_items[0].childItems()
                if isinstance(c, FieldItem)][0]
        item.setSelected(True)
        item.setSelected(False)
        snapshots = len(vm._undo)
        item.mouseMoveEvent(mouse_event(QEvent.Type.MouseMove, QPointF(0, 0),
                                        Qt.MouseButton.NoButton,
                                        Qt.MouseButton.LeftButton))
        item.mouseReleaseEvent(mouse_event(QEvent.Type.MouseButtonRelease, QPointF(0, 0),
                                           Qt.MouseButton.LeftButton,
                                           Qt.MouseButton.NoButton))
        assert len(vm._undo) == snapshots

    def test_corner_handle_resizes_and_commits(self, vm):
        vm.set_snap(False)
        field = self.make_vm_field(vm, x=100.0, y=100.0, w=100.0, h=50.0)
        canvas = SheetCanvas(vm)
        canvas.refresh()
        item = [c for c in canvas._page_items[0].childItems()
                if isinstance(c, FieldItem)][0]
        item._viewmodel = vm
        # bottom-right handle
        handle = item._handles[2]
        # drive the handle in local parent coordinates directly
        handle.mousePressEvent(mouse_event(QEvent.Type.MouseButtonPress, QPointF(0, 0),
                                            Qt.MouseButton.LeftButton,
                                            Qt.MouseButton.LeftButton))
        handle.mouseMoveEvent(mouse_event(QEvent.Type.MouseMove, QPointF(30, 20),
                                          Qt.MouseButton.NoButton,
                                          Qt.MouseButton.LeftButton))
        handle.mouseReleaseEvent(mouse_event(QEvent.Type.MouseButtonRelease, QPointF(30, 20),
                                             Qt.MouseButton.LeftButton,
                                             Qt.MouseButton.NoButton))
        assert field.w == 130.0 and field.h == 70.0

    def test_handle_min_size_clamp(self, vm):
        vm.set_snap(False)
        field = self.make_vm_field(vm, x=100.0, y=100.0, w=30.0, h=12.0)
        canvas = SheetCanvas(vm)
        canvas.refresh()
        item = [c for c in canvas._page_items[0].childItems()
                if isinstance(c, FieldItem)][0]
        item._viewmodel = vm
        handle = item._handles[2]
        handle.mousePressEvent(mouse_event(QEvent.Type.MouseButtonPress, QPointF(0, 0),
                                            Qt.MouseButton.LeftButton,
                                            Qt.MouseButton.LeftButton))
        handle.mouseMoveEvent(mouse_event(QEvent.Type.MouseMove, QPointF(-400, -400),
                                          Qt.MouseButton.NoButton,
                                          Qt.MouseButton.LeftButton))
        handle.mouseReleaseEvent(mouse_event(QEvent.Type.MouseButtonRelease, QPointF(-400, -400),
                                             Qt.MouseButton.LeftButton,
                                             Qt.MouseButton.NoButton))
        assert field.w >= 20.0 and field.h >= 10.0

    def test_handle_left_top_corner(self, vm):
        vm.set_snap(False)
        self.make_vm_field(vm, x=100.0, y=100.0, w=100.0, h=50.0)
        canvas = SheetCanvas(vm)
        canvas.refresh()
        item = [c for c in canvas._page_items[0].childItems()
                if isinstance(c, FieldItem)][0]
        item._viewmodel = vm
        handle = item._handles[0]  # top-left
        handle.mousePressEvent(mouse_event(QEvent.Type.MouseButtonPress, QPointF(0, 0),
                                            Qt.MouseButton.LeftButton,
                                            Qt.MouseButton.LeftButton))
        handle.mouseMoveEvent(mouse_event(QEvent.Type.MouseMove, QPointF(-20, -10),
                                          Qt.MouseButton.NoButton,
                                          Qt.MouseButton.LeftButton))
        handle.mouseReleaseEvent(mouse_event(QEvent.Type.MouseButtonRelease, QPointF(-20, -10),
                                             Qt.MouseButton.LeftButton,
                                             Qt.MouseButton.NoButton))
        assert vm.template.pages[0].fields[0].x == 80.0
        assert vm.template.pages[0].fields[0].y == 90.0

    def test_handle_reject_without_press(self, vm):
        add_field_id(vm)
        canvas = SheetCanvas(vm)
        canvas.refresh()
        item = [c for c in canvas._page_items[0].childItems()
                if isinstance(c, FieldItem)][0]
        handle = item._handles[0]
        snapshots = len(vm._undo)
        handle.mouseMoveEvent(mouse_event(QEvent.Type.MouseMove, QPointF(5, 5),
                                          Qt.MouseButton.NoButton,
                                          Qt.MouseButton.LeftButton))
        handle.mouseReleaseEvent(mouse_event(QEvent.Type.MouseButtonRelease, QPointF(5, 5),
                                             Qt.MouseButton.LeftButton,
                                             Qt.MouseButton.NoButton))
        # no press → the gesture must not create an undo entry
        assert len(vm._undo) == snapshots

    def test_label_visibility(self, vm):
        add_field_id(vm, label="Метка")
        canvas = SheetCanvas(vm)
        canvas.refresh()
        item = [c for c in canvas._page_items[0].childItems()
                if isinstance(c, FieldItem)][0]
        assert item._label.text() == "Метка"
        # heading: no label above the box
        add_field_id(vm, FieldType.HEADING, x=400.0, label="Х")
        canvas.refresh()
        items = [c for c in canvas._page_items[0].childItems() if isinstance(c, FieldItem)]
        assert items[1]._label.text() == ""


class TestRealDispatch:
    """Events synthesized by QTest through the real view → scene → item
    pipeline.

    The item then receives genuine QGraphicsSceneMouseEvent objects (the
    ``scenePos()`` branch of ``_pointer_pos``); the plain-QMouseEvent doubles
    used above never reach that branch. Asserting the exact committed
    geometry also guards the stable-frame contract: mapping the pointer
    through the item's own moving position would cut the drag in half.
    """

    def make_view(self, vm, qapp, qtbot):
        """Shown canvas view; returns (view, host).

        The test must keep ``host`` alive: it is the C++ parent of the view,
        and releasing it cascades the C++ deletion into the view (the
        ``qtbot`` registration does not protect against that).
        """
        canvas = SheetCanvas(vm)
        view = make_widget_view(canvas)
        host = QWidget()
        host.setLayout(QVBoxLayout())
        host.layout().addWidget(view)
        host.resize(500, 400)
        host.show()
        qtbot.addWidget(host)
        canvas.refresh()
        view.resetTransform()
        view.centerOn(QPointF(100, 100))
        qapp.processEvents()
        return view, host

    def test_real_click_selects_field(self, vm, qapp, qtbot):
        add_field_id(vm)  # scene rect ≈ (140,140)-(240,190)
        view, _ = self.make_view(vm, qapp, qtbot)
        vp = view.mapFromScene(QPointF(145, 145))
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier(0), vp)
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton,
                           Qt.KeyboardModifier(0), vp)
        qapp.processEvents()
        assert vm.selected_field_id is not None

    def test_wheel_zoom_anchors_cursor(self, vm, qapp, qtbot):
        # Regression: the default AnchorViewCenter auto-shifted the
        # scrollbars on scale() and the explicit recipe in _zoom_toward
        # shifted them again, so the scene point under the cursor drifted
        # ~40 px per Ctrl+wheel step.
        add_field_id(vm)
        view, _ = self.make_view(vm, qapp, qtbot)
        cursor = QPoint(250, 180)
        scene_at_cursor = view.mapToScene(cursor)
        event = QWheelEvent(
            QPointF(cursor.x(), cursor.y()), QPointF(0, 0), QPoint(0, 120), QPoint(0, 14400),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.ControlModifier,
            Qt.ScrollPhase.NoScrollPhase, False,
        )
        view.wheelEvent(event)
        qapp.processEvents()
        mapped = view.mapFromScene(scene_at_cursor)
        # scrollbars quantize to px, so sub-pixel drift is expected
        assert abs(mapped.x() - cursor.x()) <= 2
        assert abs(mapped.y() - cursor.y()) <= 2

    def test_real_drag_full_speed(self, vm, qapp, qtbot):
        vm.set_snap(False)
        add_field_id(vm, x=100.0, y=100.0, w=100.0, h=50.0)
        view, _ = self.make_view(vm, qapp, qtbot)
        vp = view.mapFromScene(QPointF(145, 145))
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier(0), vp)
        qapp.processEvents()
        for step in (20, 40, 60):
            QTest.mouseMove(view.viewport(), vp + QPoint(step, step))
            qapp.processEvents()
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton,
                           Qt.KeyboardModifier(0), vp + QPoint(60, 60))
        qapp.processEvents()
        f = vm.template.pages[0].fields[0]
        assert (f.x, f.y, f.w, f.h) == (160.0, 160.0, 100.0, 50.0)


# ── 6.3 palette + properties panel ────────────────────────────────────────


class TestPalette:
    def test_nine_buttons_emit_types(self, qapp, qtbot):
        palette = ItemsPalette()
        qtbot.addWidget(palette)
        received = []
        palette.field_type_clicked.connect(received.append)
        for field_type in FieldType:
            palette.button_for(field_type).click()
        assert received == list(FieldType)


class TestPropertiesPanel:
    def make_panel(self, vm, qtbot):
        panel = PropertiesPanel(vm)
        qtbot.addWidget(panel)
        return panel

    def test_no_selection_shows_hint_and_hides_rows(self, vm, qtbot):
        panel = self.make_panel(vm, qtbot)
        assert "не выбрано" in panel.empty_hint.text()
        for i in range(panel._form.count()):
            widget = panel._form.itemAt(i).widget()
            assert widget is None or not widget.isVisible()

    def test_short_text_rows(self, vm, qtbot):
        panel = self.make_panel(vm, qtbot)
        add_field_id(vm, FieldType.SHORT_TEXT, label="Подпись", x=10.0)
        visible = {i for i in range(panel._form.count())
                   if (w := panel._form.itemAt(i).widget()) is not None
                   and w.isVisibleTo(panel)}
        assert 0 in visible and 1 in visible and 2 in visible
        assert 3 not in visible and 4 not in visible  # min/max hidden
        assert 5 not in visible and 6 not in visible
        assert panel.label_input.text() == "Подпись"

    def test_number_rows_incl_min_max(self, vm, qtbot):
        panel = self.make_panel(vm, qtbot)
        add_field_id(vm, FieldType.NUMBER, min_value=5, max_value=40)
        inner_min = panel._form.itemAt(3).widget()._field_widget
        inner_max = panel._form.itemAt(4).widget()._field_widget
        assert inner_min.value() == 5 and inner_max.value() == 40

    def test_checkbox_row_and_commit(self, vm, qtbot):
        panel = self.make_panel(vm, qtbot)
        add_field_id(vm, FieldType.CHECKBOX, initial_checked=False)
        inner = panel._form.itemAt(5).widget()._field_widget
        assert inner.isChecked() is False
        inner.setChecked(True)
        assert vm.selected_field.initial_checked is True

    def test_dropdown_options_editor(self, vm, qtbot):
        panel = self.make_panel(vm, qtbot)
        add_field_id(vm, FieldType.DROPDOWN, options=["А", "Б"])
        options: list = panel.options_widget.options()
        assert options == ["А", "Б"]
        options_widget = panel.options_widget
        options_widget.new_option.setText("В")
        options_widget.new_option.returnPressed.emit()
        assert vm.selected_field.options == ["А", "Б", "В"]
        # remove the last option
        options_widget.list.setCurrentRow(2)
        remove_btn = options_widget.findChildren(QPushButton)[-1]
        remove_btn.click()
        assert vm.selected_field.options == ["А", "Б"]

    def test_label_edit_commits(self, vm, qtbot):
        panel = self.make_panel(vm, qtbot)
        add_field_id(vm)
        panel.label_input.setText("Новая подпись")
        panel.label_input.editingFinished.emit()
        assert vm.selected_field.label == "Новая подпись"

    def test_default_value_commit(self, vm, qtbot):
        panel = self.make_panel(vm, qtbot)
        add_field_id(vm, FieldType.SHORT_TEXT)
        panel.default_input.setText("Херой")
        panel.default_input.editingFinished.emit()
        assert vm.selected_field.default_value == "Херой"

    def test_font_size_commit(self, vm, qtbot):
        panel = self.make_panel(vm, qtbot)
        add_field_id(vm)
        panel.font_spin.setValue(20)
        assert vm.selected_field.font_size == 20.0

    def test_invalid_min_max_reloads(self, vm, qtbot):
        panel = self.make_panel(vm, qtbot)
        add_field_id(vm, FieldType.NUMBER, min_value=1, max_value=10)
        inner_min = panel._form.itemAt(3).widget()._field_widget
        inner_min.setValue(50)  # now min > max
        assert vm.selected_field.min_value == 1  # model untouched
        # panel re-synced from the model
        assert inner_min.value() == 1

    def test_commit_ignores_without_selection(self, vm, qtbot):
        panel = self.make_panel(vm, qtbot)
        panel.label_input.setText("x")
        panel.label_input.editingFinished.emit()  # no selection → no-op
        assert len(vm.template.pages[0].fields) == 0

    def test_visible_for_all_types(self):
        for field_type in FieldType:
            visible = PropertiesPanel._visible_for(field_type)
            assert 0 in visible and 2 in visible
        assert 3 in PropertiesPanel._visible_for(FieldType.NUMBER)
        assert 5 in PropertiesPanel._visible_for(FieldType.CHECKBOX)
        assert 6 in PropertiesPanel._visible_for(FieldType.DROPDOWN)
        assert 1 not in PropertiesPanel._visible_for(FieldType.HEADING)


# ── 6.5 pages dialog ──────────────────────────────────────────────────────


class TestPagesDialog:
    def make_dialog(self, vm, qtbot):
        dialog = PagesDialog(vm)
        qtbot.addWidget(dialog)
        return dialog

    def test_rename_applies_to_model(self, vm, qtbot, monkeypatch):
        dialog = self.make_dialog(vm, qtbot)
        dialog._list.setCurrentRow(0)
        item = dialog._list.item(0)
        item.setText("Вторая")
        dialog._on_item_changed(item)
        assert vm.template.pages[0].name == "Вторая"

    def test_rename_empty_rejected(self, vm, qtbot):
        dialog = self.make_dialog(vm, qtbot)
        vm.add_page()
        item = dialog._list.item(1)
        item.setText("   ")
        dialog._on_item_changed(item)
        assert vm.template.pages[1].name == "Стр 2"

    def test_rename_during_reload_ignored(self, vm, qtbot):
        dialog = self.make_dialog(vm, qtbot)
        dialog._reloading = True
        item = dialog._list.item(0)
        item.setText("Проигнорировано")
        assert vm.template.pages[0].name == "Стр 1"

    def test_delete_empty_page_immediately(self, vm, qtbot):
        add_field_id(vm, page=0)
        vm.add_page()
        dialog = self.make_dialog(vm, qtbot)
        dialog._list.setCurrentRow(1)
        dialog._remove()
        assert len(vm.template.pages) == 1

    def test_delete_page_with_fields_confirms(self, vm, qtbot, monkeypatch):
        add_field_id(vm)
        vm.add_page()
        add_field_id(vm, page=1)
        dialog = self.make_dialog(vm, qtbot)
        dialog._list.setCurrentRow(1)

        questions = iter([QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes])
        monkeypatch.setattr(QMessageBox, "question",
                            staticmethod(lambda *a, **k: next(questions)))
        dialog._remove()
        assert len(vm.template.pages) == 2  # declined
        dialog._remove()
        assert len(vm.template.pages) == 1  # confirmed

    def test_remove_without_selection_noop(self, vm, qtbot):
        dialog = self.make_dialog(vm, qtbot)
        dialog._list.clearSelection()
        dialog._remove()
        assert len(vm.template.pages) == 1

    def test_move_pages(self, vm, qtbot):
        vm.add_page()
        vm.add_page()
        dialog = self.make_dialog(vm, qtbot)
        dialog._list.setCurrentRow(0)
        dialog._move(+1)
        assert [p.name for p in vm.template.pages] == ["Стр 2", "Стр 1", "Стр 3"]
        dialog._list.setCurrentRow(2)
        dialog._move(-1)
        assert [p.name for p in vm.template.pages] == ["Стр 2", "Стр 3", "Стр 1"]
        dialog._list.setCurrentRow(0)
        dialog._move(-1)  # top edge
        assert [p.name for p in vm.template.pages] == ["Стр 2", "Стр 3", "Стр 1"]
        dialog._list.clearSelection()
        assert dialog._move(-1) is None  # no selection

    def test_reload_keeps_selection_clamped(self, vm, qtbot):
        dialog = self.make_dialog(vm, qtbot)
        dialog._list.setCurrentRow(0)
        dialog._reload()
        assert dialog._list.currentRow() == 0

    def test_edit_item_entry_point(self, vm, qtbot):
        dialog = self.make_dialog(vm, qtbot)
        dialog._list.setCurrentRow(0)
        dialog._rename()  # flags the item as editable (editItem is a no-op offscreen)
        assert vm.template.pages[0].name == "Стр 1"

    def test_item_change_on_invalidated_item_ignored(self, vm, qtbot):
        dialog = self.make_dialog(vm, qtbot)
        item = dialog._list.item(0)
        vm.add_page()  # state_changed → _reload rebuilds the list, invalidating `item`
        dialog._reloading = False
        dialog._on_item_changed(item)  # isValid(item) is False → early return
        assert vm.template.pages[0].name == "Стр 1"

    def test_item_change_on_stray_item_ignored(self, vm, qtbot):
        from PySide6.QtWidgets import QListWidgetItem

        dialog = self.make_dialog(vm, qtbot)
        stray = QListWidgetItem("чужая")  # never added to _list → row() == -1
        dialog._on_item_changed(stray)
        assert vm.template.pages[0].name == "Стр 1"

    def test_actions_without_selection_noop(self, vm, qtbot):
        dialog = self.make_dialog(vm, qtbot)
        dialog._list.setCurrentRow(-1)
        dialog._rename()
        dialog._remove()
        dialog._move(+1)
        dialog._move(-1)
        assert len(vm.template.pages) == 1
        assert vm.template.pages[0].name == "Стр 1"


# ── 6.4 toolbar ────────────────────────────────────────────────────────────


@pytest.fixture
def editor(qapp, qtbot):
    dialog = CharacterSheetEditorDialog(AsyncMock(), name="Лист")
    # qtbot closes the dialog in pytest_runtest_teardown, which runs BEFORE
    # this fixture finalizes — suppress the close prompt up front; tests that
    # exercise the guard reset _closing themselves
    dialog._closing = True
    qtbot.addWidget(dialog)
    yield dialog


def key_event(key_code, modifiers=Qt.KeyboardModifier(0)):
    return QKeyEvent(QEvent.Type.KeyPress, key_code, modifiers)


async def spin(times: int = 10) -> None:
    for _ in range(times):
        await asyncio.sleep(0)


class TestToolbar:
    async def test_save_button_persists_and_clears_dirty(self, editor):
        editor._vm.add_field(FieldType.SHORT_TEXT, 0, 30.0, 30.0)
        assert editor._vm.dirty
        editor.save_btn.click()
        await spin()
        editor._service.create.assert_awaited_once()
        assert not editor._vm.dirty

    async def test_export_button_writes_pdf(self, editor, tmp_path, monkeypatch):
        dest = tmp_path / "sheet.pdf"
        monkeypatch.setattr(
            editor_module.QFileDialog, "getSaveFileName",
            staticmethod(lambda *a, **k: (str(dest), "PDF файлы (*.pdf)")),
        )
        editor.export_btn.click()
        await spin(20)
        assert dest.exists()
        reader = PdfReader(str(dest))
        assert reader.metadata.title == "Лист"
        assert "PDF сохранён" in editor._status.text()

    def test_undo_redo_enabled_state(self, editor):
        assert not editor._undo_btn.isEnabled()
        assert not editor._redo_btn.isEnabled()
        editor._vm.add_field(FieldType.SHORT_TEXT, 0, 30.0, 30.0)
        assert editor._undo_btn.isEnabled()
        editor._vm.undo()
        assert not editor._undo_btn.isEnabled()
        assert editor._redo_btn.isEnabled()
        editor._vm.redo()
        assert not editor._redo_btn.isEnabled()
        assert editor._undo_btn.isEnabled()

    def test_grid_checkbox_and_step(self, editor):
        editor._grid_cb.setChecked(True)
        editor._grid_spin.setValue(10)
        assert editor._vm.snap_enabled is True
        assert editor._vm.snap_step == 10.0
        page_item = editor._canvas._page_items[0]
        assert page_item.grid_enabled and page_item.grid_step == 10.0
        editor._grid_cb.setChecked(False)
        assert editor._vm.snap_enabled is False
        assert not page_item.grid_enabled

    def test_orientation_combo_rebuilds_pages(self, editor):
        editor._orientation_combo.setCurrentIndex(1)
        assert editor._vm.template.orientation is SheetOrientation.PORTRAIT
        page = editor._canvas._page_items[0]
        assert page.size.width() == 595.28 and page.size.height() == 841.89

    def test_add_page_button(self, editor):
        assert len(editor._vm.template.pages) == 1
        editor.add_page_btn.click()
        assert len(editor._vm.template.pages) == 2
        assert len(editor._canvas._page_items) == 2

    def test_pages_button_opens_pages_dialog(self, editor, monkeypatch):
        captured = {}

        class FakePagesDialog:
            def __init__(self, vm, parent=None):
                captured["vm"] = vm

            def exec(self):
                return 0

        monkeypatch.setattr(
            editor_module, "make_pages_dialog",
            lambda vm, parent=None: FakePagesDialog(vm, parent),
        )
        editor.pages_btn.click()
        assert captured["vm"] is editor._vm

    def test_zoom_buttons(self, editor):
        editor._canvas_view.resize(400, 300)
        start = editor._canvas_view.transform().m11()
        editor.zoom_in_btn.click()
        zoomed = editor._canvas_view.transform().m11()
        assert zoomed > start
        editor.zoom_out_btn.click()
        assert editor._canvas_view.transform().m11() < zoomed

    def test_fit_button(self, editor):
        editor._canvas_view.resize(400, 300)
        editor.fit_btn.click()
        assert editor._canvas_view.transform().m11() != 1.0

    def test_key_delete(self, editor):
        editor._vm.add_field(FieldType.SHORT_TEXT, 0, 30.0, 30.0)
        editor.keyPressEvent(key_event(Qt.Key.Key_Delete))
        assert len(editor._vm.template.pages[0].fields) == 0

    def test_key_duplicate(self, editor):
        editor._vm.add_field(FieldType.SHORT_TEXT, 0, 30.0, 30.0)
        editor.keyPressEvent(key_event(Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier))
        assert len(editor._vm.template.pages[0].fields) == 2

    def test_key_undo_redo(self, editor):
        editor._vm.add_field(FieldType.SHORT_TEXT, 0, 30.0, 30.0)
        editor.keyPressEvent(key_event(Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier))
        assert len(editor._vm.template.pages[0].fields) == 0
        editor.keyPressEvent(key_event(
            Qt.Key.Key_Z,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
        ))
        assert len(editor._vm.template.pages[0].fields) == 1

    async def test_key_save_shortcut(self, editor):
        editor._vm.add_field(FieldType.SHORT_TEXT, 0, 30.0, 30.0)
        editor.keyPressEvent(key_event(Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier))
        await spin()
        editor._service.create.assert_awaited_once()
        assert not editor._vm.dirty


# ── 6.6 window assembly + close guard ──────────────────────────────────────


class TestEditorWindow:
    def test_layout_contains_palette_canvas_properties(self, editor):
        assert isinstance(editor._palette, ItemsPalette)
        assert isinstance(editor._canvas_view, SheetCanvasView)
        assert isinstance(editor._properties, PropertiesPanel)
        for widget in (editor._palette, editor._canvas_view, editor._properties):
            assert widget.parent() is not None

    def test_title_marks_dirty(self, editor):
        assert "*" not in editor.windowTitle()
        editor._vm.add_field(FieldType.SHORT_TEXT, 0, 30.0, 30.0)
        assert "*" in editor.windowTitle()
        editor._vm.undo()
        # undo also commits — the template differs from the last save again
        assert "*" in editor.windowTitle()

    def test_close_without_dirty_is_immediate(self, editor, monkeypatch):
        editor._closing = False
        called = []
        monkeypatch.setattr(QMessageBox, "question",
                            staticmethod(lambda *a, **k: called.append(a)
                                         or QMessageBox.StandardButton.No))
        event = QCloseEvent()
        editor.closeEvent(event)
        assert event.isAccepted()
        assert called == []

    def test_close_with_dirty_cancelled(self, editor, monkeypatch):
        editor._closing = False
        editor._vm.add_field(FieldType.SHORT_TEXT, 0, 30.0, 30.0)
        monkeypatch.setattr(QMessageBox, "question",
                            staticmethod(lambda *a, **k: QMessageBox.StandardButton.Cancel))
        event = QCloseEvent()
        editor.closeEvent(event)
        assert not event.isAccepted()
        # a second close attempt asks again (pending flag was reset)
        event_again = QCloseEvent()
        editor.closeEvent(event_again)
        assert not event_again.isAccepted()

    def test_close_with_dirty_no_closes(self, editor, monkeypatch):
        editor._closing = False
        editor._vm.add_field(FieldType.SHORT_TEXT, 0, 30.0, 30.0)
        monkeypatch.setattr(QMessageBox, "question",
                            staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
        event = QCloseEvent()
        editor.closeEvent(event)
        assert event.isAccepted()

    async def test_close_with_dirty_yes_saves_then_closes(self, editor, monkeypatch):
        editor._closing = False
        editor._vm.add_field(FieldType.SHORT_TEXT, 0, 30.0, 30.0)
        monkeypatch.setattr(QMessageBox, "question",
                            staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
        event = QCloseEvent()
        editor.closeEvent(event)
        assert not event.isAccepted()  # close only after the async save finishes
        await spin()
        editor._service.create.assert_awaited_once()
        assert editor._closing
        assert not editor._vm.dirty

    def test_reject_without_dirty_closes(self, editor):
        editor._closing = False
        editor.reject()
        from PySide6.QtWidgets import QDialog

        assert editor.result() == QDialog.DialogCode.Rejected

    async def test_close_with_dirty_yes_save_fails_keeps_dialog(self, editor, monkeypatch):
        editor._closing = False
        editor._vm.add_field(FieldType.SHORT_TEXT, 0, 30.0, 30.0)

        async def failed_save():
            return False

        editor._vm.save = failed_save
        monkeypatch.setattr(QMessageBox, "question",
                            staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
        event = QCloseEvent()
        editor.closeEvent(event)
        assert not event.isAccepted()
        await spin()
        assert not editor._closing  # closing was not forced
        assert editor._vm.dirty  # nothing was lost


# ── coverage gaps: branches no UI flow reaches ─────────────────────────────


class TestGaps:
    def test_make_pages_dialog_factory(self, vm, qtbot):
        dialog = editor_module.make_pages_dialog(vm)
        assert isinstance(dialog, PagesDialog)
        qtbot.addWidget(dialog)

    async def test_open_missing_sheet_rejects(self, qapp, qtbot, monkeypatch):
        service = AsyncMock()
        service.load = AsyncMock(return_value=None)
        dialog = CharacterSheetEditorDialog(service, sheet_id=99)
        criticals: list[tuple] = []
        monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: criticals.append(a)))
        qtbot.addWidget(dialog)
        await spin()
        assert criticals
        assert "Шаблон не найден" in str(criticals[0])

    def test_palette_click_adds_centered_field(self, editor):
        editor._on_palette_clicked(FieldType.HEADING)
        fields = editor._vm.template.pages[0].fields
        assert len(fields) == 1
        assert fields[0].id == editor._vm.selected_field_id

    def test_export_cancelled_picker_is_noop(self, editor, monkeypatch):
        from PySide6.QtWidgets import QFileDialog

        monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", "")))
        editor.export_btn.click()
        assert editor._status.text() == ""

    def test_plain_key_press_falls_through(self, editor):
        editor.keyPressEvent(key_event(Qt.Key.Key_A))  # unhandled → super()


class TestFieldItemGaps:
    """Items are always taken from a canvas refresh (the lifetime-safe
    pattern of this file): a bare FieldItem's C++ teardown cascades into its
    handles and re-enters itemChange on dying objects."""

    def _item_from_canvas(self, vm, qtbot, x=100.0, y=100.0):
        field_id = vm.add_field(FieldType.SHORT_TEXT, 0, x, y).id
        canvas = SheetCanvas(vm)
        view = make_widget_view(canvas)
        qtbot.addWidget(view)
        canvas.refresh()
        item = [c for c in canvas._page_items[0].childItems()
                if isinstance(c, FieldItem)][0]
        field = vm.template.find_field(field_id)[1]
        # Keep strong refs: pytest-qt holds only a weak ref to the widget, so
        # letting canvas/view go out of scope would GC the canvas Python
        # wrapper -> SheetCanvas.__del__ -> clear() -> _viewmodel = None while
        # the C++ scene (and this item) are still alive. The test instance
        # (self) lives for the whole test method, so stashing here is enough.
        self._keep_alive = (canvas, view)
        return item, field

    def test_commit_without_viewmodel_is_noop(self, vm, qtbot):
        item, field = self._item_from_canvas(vm, qtbot)
        item._viewmodel = None
        item.commit_rect()  # no viewmodel → nothing is committed

    def test_plain_click_commit_takes_no_snapshot(self, vm, qtbot):
        item, field = self._item_from_canvas(vm, qtbot)
        snapshots_before = len(vm._undo)
        item.commit_rect()  # geometry unchanged → no snapshot
        assert len(vm._undo) == snapshots_before
        assert (field.x, field.y) == (100.0, 100.0)

    def test_mouse_drag_through_move_and_release(self, vm, qtbot):
        vm.set_snap(False)
        item, field = self._item_from_canvas(vm, qtbot)

        item.mousePressEvent(
            mouse_event(QEvent.Type.MouseButtonPress, QPointF(0, 0),
                        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton))
        item.mouseMoveEvent(
            mouse_event(QEvent.Type.MouseMove, QPointF(30, 40),
                        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton))
        assert item.pos() == QPointF(130, 140)  # live preview position
        item.mouseReleaseEvent(
            mouse_event(QEvent.Type.MouseButtonRelease, QPointF(30, 40),
                        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton))
        assert (field.x, field.y) == (130.0, 140.0)  # commit went to the model


class TestCanvasViewGaps:
    def test_refresh_without_viewmodel_is_noop(self, qapp):
        canvas = SheetCanvas(None)
        canvas.refresh()  # no template → early return
        assert canvas._page_items == []

    def test_column_rect_without_pages(self, qapp):
        canvas = SheetCanvas(None)
        rect = canvas._column_rect()
        assert (rect.width(), rect.height()) == (100.0, 100.0)

    def test_plain_key_events_fall_through(self, qapp, vm):
        view = SheetCanvasView(SheetCanvas(vm))
        view.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier(0)))
        view.keyReleaseEvent(QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_A, Qt.KeyboardModifier(0)))

    def test_plain_mouse_move_falls_through(self, qapp, vm):
        view = SheetCanvasView(SheetCanvas(vm))
        event = QMouseEvent(
            QEvent.Type.MouseMove, QPointF(5, 5), QPointF(5, 5), QPointF(0, 0),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier(0),
        )
        view.mouseMoveEvent(event)  # not panning → super()

    def test_shutdown_clear_normal(self, qapp, vm):
        canvas = SheetCanvas(vm)
        canvas.refresh()  # real items → clear() takes the drop branch
        canvas._shutdown_clear()
        assert canvas._page_items == []

    def test_shutdown_clear_swallows_errors(self, qapp, vm):
        canvas = SheetCanvas(vm)
        canvas.refresh()
        # A non-item object makes _drop_page's removeItem raise mid-clear;
        # the guard must swallow it (interpreter-shutdown chaos, D-safety).
        canvas._page_items = [object()]
        canvas._shutdown_clear()  # must not raise

    def test_properties_panel_set_guards(self, vm, qtbot):
        from PySide6.QtWidgets import QWidget

        panel = PropertiesPanel(vm)
        qtbot.addWidget(panel)
        panel._set(None, "label", "x")  # missing row widget → no-op
        panel._set(QWidget(), "label", "x")  # row without _field_widget → no-op

    def test_properties_panel_commit_while_loading(self, vm, qtbot):
        panel = PropertiesPanel(vm)
        qtbot.addWidget(panel)
        calls: list = []
        original = vm.update_field

        def spy(field_id, **changes):
            calls.append(field_id)
            return original(field_id, **changes)

        vm.update_field = spy
        vm.select(add_field_id(vm))
        panel._loading = True
        panel._commit()  # loading guard → no commit
        assert calls == []

    def test_option_list_ignores_empty_add(self, vm, qtbot):
        from app.presentation.views.character_sheet.properties_panel import _OptionList

        options = _OptionList()
        qtbot.addWidget(options)
        options.new_option.setText("   ")
        options.new_option.returnPressed.emit()
        assert options.options() == []
