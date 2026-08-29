"""Character-sheet canvas: a QGraphicsView of the vertical page tape (D1/D2).

Scene coordinates equal page points (1 unit = 1 pt, origin top-left). Page
``i`` is a white rectangle at ``page_origin(i, page_h)`` with the GUTTER_PT
gap between pages (the view background shows through the gutters as grey).
Fields are rect items positioned at ``page_origin + field-local``; the z-order
is the field order within its page (later-placed on top).

Wheel (A-playable, D2): the plain wheel scrolls the tape; Ctrl+wheel zooms
(cursor-anchored, 25%–400%); there is no separate zoom panel. On open the
view fits the **width** of one A4 sheet (not the whole tape) with the first
page at the top.

Fields use the bundled DejaVu Sans (registered once via
``QFontDatabase.addApplicationFont``); text wraps/clips inside the field
frame per the editor spec.
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPixmap,
    QPen,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsProxyWidget,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QRubberBand,
    QWidget,
)

from app.domain.entities.character_sheet import (
    GUTTER_PT,
    PAGE_HEIGHT_PT,
    PAGE_WIDTH_PT,
    SheetField,
    page_origin,
    scene_to_page,
    tape_height,
)
from app.domain.enums.field_type import FieldType
from app.presentation.viewmodels.character_sheet_viewmodel import (
    SNAP_PT,
    TOOL_POINTER,
    CharacterSheetViewModel,
    field_type_for_tool,
)

log = logging.getLogger(__name__)

SHEET_FONT_FAMILY: str = "DejaVu Sans"

MIN_ZOOM: float = 0.25
MAX_ZOOM: float = 4.0
ZOOM_STEP: float = 1.15

GUTTER_BACKGROUND: QColor = QColor(226, 226, 226)
_PAGE_FRAME = QPen(QColor(90, 90, 90), 1.0)

_FRAME_COLOR = QColor(120, 140, 180)
_SELECTED_COLOR = QColor(47, 125, 225)
_TEXT_COLOR = QColor(20, 20, 20)
_LINE_COLOR = QColor(60, 60, 60)
_CHECK_COLOR = QColor(30, 110, 190)
_IMAGE_PLACEHOLDER = QColor(150, 150, 150)
_TEXT_INSET = 2.0
_RUBBER_THRESHOLD_PX = 4
_GRID_COLOR = QColor(210, 218, 228)
_HANDLE_PT = 8.0

_font_registered = False


def _font_path() -> Path:
    """The bundled TTF lives next to this module.

    Same layout as the dev tree holds in the PyInstaller bundle: the app ships
    as a directory bundle and the compiled module's ``__file__`` resolves
    inside it right next to the ``datas``-shipped ``fonts/`` directory
    (verified in a real bundle: ``Path(__file__).resolve().parent ==
    Path(sys._MEIPASS)/<module path>``), so no separate ``_MEIPASS`` lookup is
    needed.
    """
    return Path(__file__).resolve().parent / "fonts" / "DejaVuSans.ttf"


def register_sheet_font() -> None:
    """Register the bundled DejaVu Sans (idempotent per process).

    A missing font file must be visible in the log: without it the canvas
    silently falls back to a default font (wrong metrics, later wrong PDF).
    """
    global _font_registered
    if _font_registered:
        return
    from PySide6.QtGui import QFontDatabase

    path = _font_path()
    font_id = QFontDatabase.addApplicationFont(str(path))
    if font_id < 0:
        log.warning("bundled sheet font failed to load: %s", path)
    _font_registered = True


def sheet_font(size_pt: float) -> QFont:
    """The single sheet font at a given point size."""
    font = QFont(SHEET_FONT_FAMILY)
    font.setPointSizeF(size_pt)
    return font


class SheetFieldItem(QGraphicsRectItem):
    """One field drawn in its page-local coordinates.

    The canvas sets the item position to the page origin; the rect here is
    the field's own (x, y, w, h). Rendering per type:

    - label / text / textarea / number / dropdown: frame + inner text
      (label and textarea wrap; the rest are single line), per the A1 rules;
    - checkbox: a square, a check mark when content is "true", no text;
    - rect: outline only, no data;
    - line: an axis — filled thin rect, thickness is the smaller side
      (width > height → horizontal, otherwise vertical);
    - image: a dashed frame placeholder; when a pixmap is loaded it is drawn
      kept-inside-aspect.
    """

    def __init__(self, field: SheetField, parent: QGraphicsRectItem | None = None) -> None:
        super().__init__(QRectF(field.x, field.y, field.w, field.h), parent)
        self._field = field
        self.selected: bool = False
        self.setPen(self._normal_pen())
        self._pixmap: QPixmap | None = None
        self._show_handles = False
        self._display_text: str | None = None
        self._checked: bool | None = None
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    # -- data --------------------------------------------------------------

    @property
    def field(self) -> SheetField:
        return self._field

    @property
    def field_id(self) -> str:
        return self._field.id

    def font(self) -> QFont:
        return sheet_font(self._field.font_size)

    def set_pixmap(self, pixmap: QPixmap | None) -> None:
        if pixmap is self._pixmap:
            return
        self._pixmap = pixmap
        self.update()

    def sync_from_field(self) -> None:
        self.prepareGeometryChange()
        f = self._field
        self.setRect(QRectF(f.x, f.y, f.w, f.h))

    def set_selected(self, flag: bool) -> None:
        if flag == self.selected:
            return
        self.selected = flag
        self._show_handles = flag
        self.setPen(QPen(_SELECTED_COLOR, 1.5) if flag else self._normal_pen())
        self.update()

    def set_show_handles(self, flag: bool) -> None:
        if flag == self._show_handles:
            return
        self._show_handles = flag
        self.update()

    def set_fill_display(self, text: str | None, checked: bool | None = None) -> None:
        self._display_text = text
        self._checked = checked
        self.update()

    def _shown_text(self) -> str:
        if self._display_text is not None:
            return self._display_text
        return self._field.content

    def _is_checked(self) -> bool:
        if self._checked is not None:
            return self._checked
        return self._field.content == "true"

    # -- drawing -----------------------------------------------------------

    @staticmethod
    def _normal_pen() -> QPen:
        return QPen(_FRAME_COLOR, 1.0)

    def _text_flags(self) -> Qt.TextFlag:
        if self._field.type is FieldType.TEXT or self._field.type is FieldType.NUMBER:
            return Qt.TextFlag(Qt.TextSingleLine)
        return Qt.TextFlag(Qt.TextWordWrap)  # label / textarea

    def _has_text(self) -> bool:
        return self._field.type in (
            FieldType.LABEL, FieldType.TEXT, FieldType.TEXTAREA,
            FieldType.NUMBER, FieldType.DROPDOWN,
        )

    def paint(self, painter: QPainter, option, widget: QWidget | None = None) -> None:
        f = self._field
        if f.type is FieldType.LINE:
            self._paint_line(painter)
        elif f.type is FieldType.CHECKBOX:
            self._paint_checkbox(painter)
        elif f.type is FieldType.IMAGE:
            self._paint_image(painter)
        else:
            # label / text / textarea / number / dropdown / rect: the frame
            # (image/line/checkbox are drawn by their own branches above)
            painter.setPen(self.pen())
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.rect())
            if self._has_text() and self._shown_text():
                painter.setPen(QPen(_TEXT_COLOR))
                painter.setFont(self.font())
                painter.drawText(
                    self.rect().adjusted(
                        _TEXT_INSET, _TEXT_INSET, -_TEXT_INSET, -_TEXT_INSET
                    ),
                    self._text_flags(),
                    self._shown_text(),
                )
        if self._show_handles:
            self._paint_handles(painter)

    def _paint_handles(self, painter: QPainter) -> None:
        painter.setBrush(QBrush(_SELECTED_COLOR))
        painter.setPen(QPen(QColor("white"), 0.5))
        r = self.rect()
        half = _HANDLE_PT / 2
        for pt in (r.topLeft(), r.topRight(), r.bottomLeft(), r.bottomRight()):
            painter.drawRect(QRectF(pt.x() - half, pt.y() - half, _HANDLE_PT, _HANDLE_PT))

    def _paint_line(self, painter: QPainter) -> None:
        """Axis line: thickness is the smaller side (w > h → horizontal,
        otherwise vertical), drawn in the item's local coordinates."""
        f = self._field
        painter.setPen(Qt.PenStyle.NoPen)
        color = _SELECTED_COLOR if self.selected else _LINE_COLOR
        painter.setBrush(QBrush(color))
        if f.w > f.h:
            local = QRectF(0.0, 0.0, f.w, max(f.h, 1.0))
        else:
            local = QRectF(0.0, 0.0, max(f.w, 1.0), f.h)
        painter.drawRect(local)

    def _paint_checkbox(self, painter: QPainter) -> None:
        painter.setPen(self.pen())
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self.rect())
        if self._is_checked():
            painter.setPen(QPen(_CHECK_COLOR, 2.0))
            r = self.rect()
            painter.drawLine(
                r.topLeft() + QPointF(r.width() * 0.2, r.height() * 0.5),
                r.topLeft() + QPointF(r.width() * 0.42, r.height() * 0.75),
            )
            painter.drawLine(
                r.topLeft() + QPointF(r.width() * 0.42, r.height() * 0.75),
                r.topLeft() + QPointF(r.width() * 0.8, r.height() * 0.25),
            )

    def _paint_image(self, painter: QPainter) -> None:
        pen = QPen(_SELECTED_COLOR, 1.5) if self.selected else QPen(_IMAGE_PLACEHOLDER, 1.2)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self.rect())
        pixmap = self._pixmap
        if pixmap is not None and not pixmap.isNull():
            target = self.rect().adjusted(_TEXT_INSET, _TEXT_INSET, -_TEXT_INSET, -_TEXT_INSET)
            if target.width() > 1 and target.height() > 1:
                scaled = pixmap.scaled(
                    int(target.width()), int(target.height()),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                pos = target.topLeft() + QPointF(
                    (target.width() - scaled.width()) / 2,
                    (target.height() - scaled.height()) / 2,
                )
                painter.drawPixmap(pos, scaled)


class PageSheetItem(QGraphicsRectItem):
    """One A4 sheet in the tape; draws the snap grid when the VM flag is on."""

    def __init__(self, rect: QRectF, vm: CharacterSheetViewModel) -> None:
        super().__init__(rect)
        self._vm = vm
        self.setPen(_PAGE_FRAME)
        self.setBrush(QBrush(QColor("white")))
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def paint(self, painter: QPainter, option, widget: QWidget | None = None) -> None:
        super().paint(painter, option, widget)
        if not self._vm.snap_enabled:
            return
        r = self.rect()
        painter.setPen(QPen(_GRID_COLOR, 0))
        x = r.left()
        while x <= r.right() + 0.01:
            painter.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            x += SNAP_PT
        y = r.top()
        while y <= r.bottom() + 0.01:
            painter.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            y += SNAP_PT


class CharacterSheetCanvas(QGraphicsView):
    """The editor canvas: the vertical tape of pages + field items, all driven
    by the ViewModel."""

    # A-playable:
    visible_page_changed = Signal(int)      # the page with the largest visible area
    image_field_double_clicked = Signal(str)  # ask the owner to pick a file

    def __init__(self, vm: CharacterSheetViewModel, parent: QWidget | None = None,
                 image_store=None, fill_mode: bool = False) -> None:
        super().__init__(parent)
        register_sheet_font()

        # The scene rect grows with the template; start with one portrait page.
        scene = QGraphicsScene(0, 0, PAGE_WIDTH_PT, PAGE_HEIGHT_PT, self)
        self.setScene(scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(QBrush(GUTTER_BACKGROUND))

        self._vm = vm
        self._image_store = image_store
        self._fill_mode = fill_mode
        self._items: dict[str, SheetFieldItem] = {}
        self._page_items: list[PageSheetItem] = []
        self._selected_item: SheetFieldItem | None = None
        self._drag_fid: str | None = None
        self._grab_dx = 0.0
        self._grab_dy = 0.0
        self._rubber: QRubberBand | None = None
        self._rubber_origin: QPoint | None = None
        self._rubber_additive: bool = False
        self._pending_clear: bool = False
        self._resize_corner: str | None = None
        self._resize_start: tuple[float, float, float, float] | None = None
        self._fitted = False
        self._last_fit_scale: float | None = None  # the settle guard, see below
        self._visible_page: int = -1
        self._inline_proxy: QGraphicsProxyWidget | None = None
        self._inline_widget: QWidget | None = None
        self._dropdown_menu: QMenu | None = None
        self._fill_click_at: dict[str, float] = {}

        vm.template_changed.connect(self._rebuild)
        vm.pages_changed.connect(self._rebuild)
        vm.field_added.connect(self._on_field_added)
        vm.field_removed.connect(self._on_field_removed)
        vm.field_geometry_changed.connect(self._on_geometry_changed)
        vm.field_content_changed.connect(self._on_field_data_changed)
        vm.field_font_changed.connect(self._on_field_data_changed)
        vm.field_props_changed.connect(self._on_field_data_changed)
        vm.selection_changed.connect(self._on_selection_changed)
        vm.inline_changed.connect(self._on_inline_changed)
        vm.snap_changed.connect(self._on_snap_changed)
        if fill_mode and hasattr(vm, "values_changed"):
            vm.values_changed.connect(self._on_fill_values_changed)

        self.verticalScrollBar().valueChanged.connect(self._update_visible_page)
        self.horizontalScrollBar().valueChanged.connect(self._update_visible_page)
        # Scrollbar Show/Hide has no Qt signal: an event filter re-fits the
        # width once the tape bar actually appears/disappears (fit_width docs).
        self.verticalScrollBar().installEventFilter(self)

        if vm.template is not None:
            self._rebuild()

    # -- geometry helpers ----------------------------------------------------

    def _template_size(self) -> tuple[float, float, int]:
        """(page_w, page_h, page_count) of the current template (portrait A4
        before the first load)."""
        template = self._vm.template
        if template is None:
            return PAGE_WIDTH_PT, PAGE_HEIGHT_PT, 1
        page_w, page_h = template.page_size
        return page_w, page_h, len(template.pages)

    def _page_scene_pos(self, field_id: str) -> QPointF:
        page_idx = self._vm.page_of(field_id)
        if page_idx is None:
            return QPointF(0, 0)
        _, page_h = self._template_size()[0], self._template_size()[1]
        _, oy = page_origin(page_idx, page_h)
        return QPointF(0.0, oy)

    def fit_width(self) -> None:
        """Fit the width of one A4 page into the viewport; the first page is
        at the top (D2). The fit is capped by MAX_ZOOM from above only — a
        tiny viewport still shows the whole page width.

        The fit uses the viewport width as it actually is: when the tape is
        taller than the viewport the vertical scrollbar appears and shrinks
        the viewport — the scrollbar's visibility change then triggers one
        more pass of this method (``_on_vbar_visibility``) so the sheet width
        ends up matching the canvas area exactly.
        """
        w, h = self._viewport_size()
        if w <= 0 or h <= 0:
            return
        page_w, _page_h, _n = self._template_size()
        scale = min(MAX_ZOOM, w / page_w)
        self.resetTransform()
        self.scale(scale, scale)
        self.centerOn(page_w / 2, 0)
        self.verticalScrollBar().setValue(0)
        self._fitted = True
        self._last_fit_scale = scale

    def _on_vbar_visibility(self, visible: bool) -> None:
        """Re-fit when the tape scrollbar appears/disappears: the available
        width changed, and the sheet must still exactly span the canvas area.

        Only during the initial settle this applies: while the view scale is
        still exactly the last fit scale. A user zoom moves the scale away,
        which both cancels the settle and is never undone by a re-fit (a
        scrollbar toggle caused by the zoom itself must not snap the zoom).
        """
        if (
            self._last_fit_scale is None
            or not self._vm.template
            or abs(self.transform().m11() - self._last_fit_scale) > 1e-9
        ):
            return
        self.fit_width()

    def _viewport_size(self) -> tuple[int, int]:
        return self.viewport().width(), self.viewport().height()

    def scroll_to_page(self, index: int) -> None:
        """Scroll so the top of page ``index`` is at the top of the viewport."""
        template = self._vm.template
        if template is None:
            return
        _, page_h, n = self._template_size()
        if not 0 <= index < n:
            return
        _, oy = page_origin(index, page_h)
        scale = self.transform().m11()
        self.verticalScrollBar().setValue(max(0, int(oy * scale)))

    # -- page/field items -----------------------------------------------------

    def item_for(self, field_id: str) -> SheetFieldItem | None:
        return self._items.get(field_id)

    def item_count(self) -> int:
        return len(self._items)

    @property
    def dropdown_menu(self) -> QMenu | None:
        return self._dropdown_menu

    def _rebuild(self) -> None:
        if self._inline_widget is not None:
            self._close_inline_widget()
        scene = self.scene()
        for page_item in self._page_items:
            scene.removeItem(page_item)
        self._page_items.clear()
        for item in list(self._items.values()):
            self._remove_item(item)
        self._items.clear()
        self._selected_item = None

        template = self._vm.template
        if template is None:
            return
        page_w, page_h = template.page_size
        n = len(template.pages)
        scene.setSceneRect(0, 0, page_w, tape_height(n, page_h))

        for i in range(n):
            _, oy = page_origin(i, page_h)
            page_item = PageSheetItem(QRectF(0, oy, page_w, page_h), self._vm)
            page_item.setZValue(0)
            scene.addItem(page_item)
            self._page_items.append(page_item)

        for page_idx, page in enumerate(template.pages):
            for index, field in enumerate(page.fields):
                self._add_item(field, page_idx, index)
        if not self._fitted and self._viewport_size()[0] > 0:
            self.fit_width()
        self._update_visible_page()
        self._sync_handle_vis()

    def _add_item(self, field: SheetField, page_index: int, field_index: int) -> None:
        item = SheetFieldItem(field)
        _page_w, page_h, _n = self._template_size()
        _, oy = page_origin(page_index, page_h)
        item.setPos(0.0, oy)
        item.setZValue(page_index * 10000 + field_index + 1)
        item.set_selected(field.id in self._vm.selected_ids)
        if self._fill_mode:
            item.set_show_handles(False)
            self._apply_fill_display(item)
        self._items[field.id] = item
        self.scene().addItem(item)
        image_id = self._image_id_of(field)
        if field.type is FieldType.IMAGE and image_id is not None:
            self._schedule_image_load(field.id, image_id)

    def _remove_item(self, item: SheetFieldItem) -> None:
        self.scene().removeItem(item)
        self._items.pop(item.field_id, None)
        if self._selected_item is item:
            self._selected_item = None

    def _image_id_of(self, field: SheetField) -> int | None:
        if self._fill_mode and hasattr(self._vm, "display_value"):
            value = self._vm.display_value(field.id)
            return value if isinstance(value, int) and not isinstance(value, bool) else None
        return field.image_id

    def _apply_fill_display(self, item: SheetFieldItem) -> None:
        field = item.field
        if not hasattr(self._vm, "display_value"):
            return
        value = self._vm.display_value(field.id)
        if field.type is FieldType.CHECKBOX:
            item.set_fill_display(None, bool(value))
        elif field.type is FieldType.IMAGE:
            item.set_fill_display(None, None)
        else:
            item.set_fill_display("" if value is None else str(value))

    def _on_field_added(self, field_id: str) -> None:
        template = self._vm.template
        if template is None:
            return
        field = template.get_field(field_id)
        page_index = template.page_of(field_id)
        if field is None or page_index is None:
            return
        self._add_item(field, page_index, len(template.pages[page_index].fields) - 1)

    def _on_field_removed(self, field_id: str) -> None:
        item = self._items.pop(field_id, None)
        if item is None:
            return
        self.scene().removeItem(item)
        if self._selected_item is item:
            self._selected_item = None

    def _on_geometry_changed(self, field_id: str) -> None:
        item = self._items.get(field_id)
        if item is None:
            return
        item.sync_from_field()
        widget = self._inline_widget
        if widget is not None and item.field_id == self._vm.inline_field_id:
            f = item.field
            widget.resize(int(f.w - 2), int(f.h - 2))

    def _on_field_data_changed(self, field_id: str) -> None:
        item = self._items.get(field_id)
        if item is not None:
            if self._fill_mode:
                self._apply_fill_display(item)
                if item.field.type is FieldType.IMAGE:
                    image_id = self._image_id_of(item.field)
                    if image_id is not None:
                        self._schedule_image_load(field_id, image_id)
                    else:
                        item.set_pixmap(None)
            item.update()
        if self._inline_widget is not None and field_id == self._vm.inline_field_id:
            self._sync_inline_widget()

    def _on_fill_values_changed(self) -> None:
        for fid, item in self._items.items():
            self._apply_fill_display(item)
            if item.field.type is FieldType.IMAGE:
                image_id = self._image_id_of(item.field)
                if image_id is not None:
                    self._schedule_image_load(fid, image_id)
                else:
                    item.set_pixmap(None)
            item.update()

    def _on_selection_changed(self, field_id) -> None:
        ids = set(self._vm.selected_ids)
        single = len(ids) == 1 and self._vm.inline_field_id is None
        self._selected_item = None
        for fid, item in self._items.items():
            on = fid in ids
            item.set_selected(on)
            item.set_show_handles(single and on and not self._fill_mode)
            if fid == field_id:
                self._selected_item = item

    def _on_snap_changed(self, _enabled: bool) -> None:
        for page_item in self._page_items:
            page_item.update()

    @property
    def grid_visible(self) -> bool:
        return self._vm.snap_enabled and bool(self._page_items)

    # -- image loading (best effort; needs a running loop, i.e. the app) -----

    def _schedule_image_load(self, field_id: str, image_id: int) -> None:
        if self._image_store is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # unit tests without an app loop: placeholder only
        loop.create_task(self._load_image(field_id, image_id))

    async def _load_image(self, field_id: str, image_id: int) -> None:
        try:
            path = await self._image_store.original_file_path(image_id)
        except Exception as exc:  # session gone / app shutting down
            log.debug("sheet image load skipped: %s", exc)
            return
        item = self._items.get(field_id)
        expected = self._image_id_of(item.field) if item is not None else None
        if item is None or expected != image_id:
            return  # the field went away (or was re-pointed) meanwhile
        if path is None or not path.exists():
            item.set_pixmap(None)
            return
        item.set_pixmap(QPixmap(str(path)))

    # -- rail sync: page with the largest visible area ------------------------

    def _update_visible_page(self) -> None:
        template = self._vm.template
        if template is None:
            return
        page_w, page_h = template.page_size
        n = len(template.pages)
        top_left = self.mapToScene(0, 0)
        bottom_right = self.mapToScene(*self._viewport_size())
        left, right = top_left.x(), bottom_right.x()
        top, bottom = top_left.y(), bottom_right.y()
        best, best_area = self._visible_page, -1.0
        for i in range(n):
            _, y0 = page_origin(i, page_h)
            oy0 = max(top, y0)
            oy1 = min(bottom, y0 + page_h)
            if oy1 <= oy0:
                continue
            ox0 = max(left, 0.0)
            ox1 = min(right, page_w)
            if ox1 <= ox0:
                continue
            area = (oy1 - oy0) * (ox1 - ox0)
            if area > best_area:
                best, best_area = i, area
        if best != self._visible_page:
            self._visible_page = best
            self.visible_page_changed.emit(best)

    # -- geometry helpers ----------------------------------------------------

    def _page_hit(self, scene_pos) -> tuple[int, float, float] | None:
        page_w, page_h, n = self._template_size()
        return scene_to_page(scene_pos.x(), scene_pos.y(), page_w, page_h, n)

    def _field_at(self, scene_pos) -> str | None:
        selected_hits: list[SheetFieldItem] = []
        for field_id in self._vm.selected_ids:
            item = self._items.get(field_id)
            if item is not None and item.sceneBoundingRect().contains(scene_pos):
                selected_hits.append(item)
        if selected_hits:
            return max(selected_hits, key=lambda i: i.zValue()).field_id
        item = self.scene().itemAt(scene_pos, QTransform())
        if isinstance(item, SheetFieldItem):
            return item.field_id
        return None

    def _handle_at(self, scene_pos) -> str | None:
        if len(self._vm.selected_ids) != 1 or self._vm.inline_field_id is not None:
            return None
        item = self._items.get(self._vm.selected_ids[0])
        if item is None:
            return None
        r = item.rect()
        points = {
            "nw": item.mapToScene(r.topLeft()),
            "ne": item.mapToScene(r.topRight()),
            "sw": item.mapToScene(r.bottomLeft()),
            "se": item.mapToScene(r.bottomRight()),
        }
        half = _HANDLE_PT / 2
        for corner, pt in points.items():
            box = QRectF(pt.x() - half, pt.y() - half, _HANDLE_PT, _HANDLE_PT)
            if box.contains(scene_pos):
                return corner
        return None

    def handle_count(self) -> int:
        if len(self._vm.selected_ids) != 1 or self._vm.inline_field_id is not None:
            return 0
        if self._items.get(self._vm.selected_ids[0]) is None:
            return 0
        return 4

    def _sync_handle_vis(self) -> None:
        show = (
            len(self._vm.selected_ids) == 1
            and self._vm.inline_field_id is None
        )
        selected = set(self._vm.selected_ids)
        for fid, item in self._items.items():
            item.set_show_handles(show and fid in selected)

    def visible_page_center(self, page_index: int) -> tuple[float, float]:
        """Page-local center of the viewport ∩ page (else the page center)."""
        template = self._vm.template
        if template is None:
            return (PAGE_WIDTH_PT / 2, PAGE_HEIGHT_PT / 2)
        page_w, page_h = template.page_size
        if not 0 <= page_index < len(template.pages):
            return (page_w / 2, page_h / 2)
        _, oy = page_origin(page_index, page_h)
        page_rect = QRectF(0.0, oy, page_w, page_h)
        top_left = self.mapToScene(0, 0)
        bottom_right = self.mapToScene(*self._viewport_size())
        view_rect = QRectF(top_left, bottom_right).normalized()
        inter = page_rect.intersected(view_rect)
        if inter.isEmpty():
            return (page_w / 2, page_h / 2)
        return (inter.center().x(), inter.center().y() - oy)

    def _viewport_pos(self, event) -> QPoint:
        return event.position().toPoint()

    def _apply_handle_resize(self, scene_pos) -> None:
        if self._resize_corner is None or self._resize_start is None:
            return
        fid = self._vm.selection
        if fid is None:
            return
        page_idx = self._vm.page_of(fid)
        if page_idx is None:
            return
        _page_w, page_h, _n = self._template_size()
        _, oy = page_origin(page_idx, page_h)
        lx = scene_pos.x()
        ly = scene_pos.y() - oy
        x, y, w, h = self._resize_start
        corner = self._resize_corner
        if "e" in corner:
            w = lx - x
        if "s" in corner:
            h = ly - y
        if "w" in corner:
            w = x + w - lx
            x = lx
        if "n" in corner:
            h = y + h - ly
            y = ly
        self._vm.resize(fid, x, y, w, h)

    def _start_drag(self, field_id: str, scene_pos) -> None:
        field = self._vm.template.get_field(field_id) if self._vm.template else None
        page_idx = self._vm.page_of(field_id)
        if field is None or page_idx is None:
            return
        _page_w, page_h, _n = self._template_size()
        _, oy = page_origin(page_idx, page_h)
        self._drag_fid = field_id
        self._grab_dx = scene_pos.x() - (field.x + 0.0)
        self._grab_dy = scene_pos.y() - (field.y + oy)

    # -- mouse ---------------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        pos = self.mapToScene(event.position().toPoint())

        if self._fill_mode:
            self._fill_press(pos, event)
            event.accept()
            return

        if self._vm.tool != TOOL_POINTER:
            field_type = field_type_for_tool(self._vm.tool)
            hit = self._page_hit(pos)
            if field_type is not None and hit is not None:
                self._vm.place(field_type, hit[1], hit[2], page_index=hit[0])
            # clicking a gutter with a place tool places nothing (spec)
            event.accept()
            return

        field_id = self._field_at(pos)
        inline_fid = self._vm.inline_field_id
        if inline_fid is not None:
            if field_id == inline_fid:
                return  # press on the field being edited: the widget owns it
            self._commit_inline_close()  # commit (apply number if due), continue
        corner = self._handle_at(pos)
        if corner is not None:
            field = self._vm.template.get_field(self._vm.selected_ids[0])
            if field is not None:
                self._resize_corner = corner
                self._resize_start = (field.x, field.y, field.w, field.h)
                self._vm.begin_gesture()
            event.accept()
            return
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if field_id is not None:
            if shift:
                self._vm.toggle_select(field_id)
            elif field_id in self._vm.selected_ids:
                self._start_drag(field_id, pos)
            else:
                self._vm.select(field_id)
                self._start_drag(field_id, pos)
        else:
            self._rubber_origin = self._viewport_pos(event)
            self._rubber_additive = shift
            self._pending_clear = True
            if not shift:
                self._vm.select(None)
        event.accept()
        super().mousePressEvent(event)

    def _fill_press(self, pos, event=None) -> None:
        if getattr(self._vm, "read_only", False):
            field_id = self._field_at(pos)
            self._vm.select(field_id)
            return
        field_id = self._field_at(pos)
        inline_fid = self._vm.inline_field_id
        if inline_fid is not None:
            if field_id == inline_fid:
                return
            self._commit_inline_close()
        if field_id is None:
            self._vm.select(None)
            return
        field = self._vm.template.get_field(field_id) if self._vm.template else None
        if field is None:
            return
        self._vm.select(field_id)
        is_dbl = False
        if event is not None:
            is_dbl = bool(
                event.flags() & Qt.MouseEventFlag.MouseEventCreatedDoubleClick
            )
        now = time.monotonic()
        app = QApplication.instance()
        interval_ms = (
            app.styleHints().mouseDoubleClickInterval() if app is not None else 400
        )
        interval = interval_ms / 1000.0
        last = self._fill_click_at.get(field_id)
        if last is not None and (now - last) < interval:
            is_dbl = True
        if field.type is FieldType.CHECKBOX:
            if is_dbl:
                return
            self._fill_click_at[field_id] = now
            self._vm.toggle_checkbox(field_id)
        elif field.type in (FieldType.TEXT, FieldType.TEXTAREA, FieldType.NUMBER):
            self._vm.open_inline(field_id)
        elif field.type is FieldType.DROPDOWN:
            self._popup_dropdown(field, pos)
        elif field.type is FieldType.IMAGE:
            if is_dbl:
                return
            self._fill_click_at[field_id] = now
            self.image_field_double_clicked.emit(field_id)

    def _popup_dropdown(self, field: SheetField, scene_pos) -> None:
        if self._dropdown_menu is not None:
            self._dropdown_menu.close()
            self._dropdown_menu.deleteLater()
            self._dropdown_menu = None
        menu = QMenu(self)
        current = (
            self._vm.display_value(field.id)
            if hasattr(self._vm, "display_value")
            else field.content
        )
        options = list(field.options)
        if isinstance(current, str) and current and current not in options:
            orphan = menu.addAction(current)
            orphan.setEnabled(False)
            menu.addSeparator()
        for opt in options:
            action = menu.addAction(opt)
            action.triggered.connect(
                lambda _c=False, o=opt, fid=field.id: self._vm.set_dropdown(fid, o)
            )
        self._dropdown_menu = menu
        view_pos = self.mapFromScene(scene_pos)
        global_pos = self.viewport().mapToGlobal(view_pos)
        menu.popup(global_pos)

    def mouseMoveEvent(self, event) -> None:
        if self._fill_mode:
            super().mouseMoveEvent(event)
            return
        if self._resize_corner is not None and self._resize_start is not None:
            pos = self.mapToScene(event.position().toPoint())
            shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            self._vm.set_snap_override(False if shift else None)
            self._apply_handle_resize(pos)
        elif self._drag_fid is not None and self._vm.inline_field_id is None:
            pos = self.mapToScene(event.position().toPoint())
            shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            self._vm.set_snap_override(False if shift else None)
            if len(self._vm.selected_ids) > 1:
                self._vm.drag_move_selection(
                    pos.x(), pos.y(), self._grab_dx, self._grab_dy,
                    ref_id=self._drag_fid,
                )
            else:
                self._vm.drag_move(
                    self._drag_fid, pos.x(), pos.y(), self._grab_dx, self._grab_dy
                )
        elif self._rubber_origin is not None:
            if not (event.buttons() & Qt.MouseButton.LeftButton):
                super().mouseMoveEvent(event)
                return
            pos = self._viewport_pos(event)
            dist = (pos - self._rubber_origin).manhattanLength()
            if dist > _RUBBER_THRESHOLD_PX:
                self._pending_clear = False
                if self._rubber is None:
                    self._rubber = QRubberBand(
                        QRubberBand.Shape.Rectangle, self.viewport()
                    )
                self._rubber.setGeometry(QRect(self._rubber_origin, pos).normalized())
                self._rubber.show()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._fill_mode:
            event.accept()
            super().mouseReleaseEvent(event)
            return
        if self._resize_corner is not None and event.button() == Qt.MouseButton.LeftButton:
            self._vm.end_gesture()
            self._vm.set_snap_override(None)
            self._resize_corner = None
            self._resize_start = None
        elif self._drag_fid is not None and event.button() == Qt.MouseButton.LeftButton:
            pos = self.mapToScene(event.position().toPoint())
            if len(self._vm.selected_ids) > 1:
                self._vm.commit_drag_selection(
                    pos.x(), pos.y(), self._grab_dx, self._grab_dy,
                    ref_id=self._drag_fid,
                )
            else:
                self._vm.commit_drag(
                    self._drag_fid, pos.x(), pos.y(), self._grab_dx, self._grab_dy
                )
            self._vm.set_snap_override(None)
        elif (
            self._rubber is not None
            and self._rubber.isVisible()
            and event.button() == Qt.MouseButton.LeftButton
        ):
            view_rect = self._rubber.geometry()
            scene_rect = self.mapToScene(view_rect).boundingRect()
            hit_ids = [
                fid for fid, item in self._items.items()
                if item.sceneBoundingRect().intersects(scene_rect)
            ]
            self._vm.select_ids(hit_ids, additive=self._rubber_additive)
            self._rubber.hide()
        elif self._pending_clear:
            self._vm.select(None)
        self._drag_fid = None
        self._rubber_origin = None
        self._pending_clear = False
        if self._rubber is not None:
            self._rubber.hide()
        event.accept()
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if self._fill_mode:
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseDoubleClickEvent(event)
            return
        pos = self.mapToScene(event.position().toPoint())
        field_id = self._field_at(pos)
        if field_id is None:
            super().mouseDoubleClickEvent(event)
            return
        field = self._vm.template.get_field(field_id) if self._vm.template else None
        if field is None:
            super().mouseDoubleClickEvent(event)
            return

        if field.type is FieldType.CHECKBOX:
            # double-click (or the panel) toggles the default value
            if self._vm.inline_field_id not in (None, field_id):
                self._commit_inline_close()
            self._vm.toggle_checkbox(field_id)
            return
        if field.type is FieldType.IMAGE:
            self.image_field_double_clicked.emit(field_id)
            return
        if field.type in (FieldType.DROPDOWN, FieldType.RECT, FieldType.LINE):
            self._vm.select(field_id)
            return
        # label / text / textarea / number: inline editing
        if self._vm.inline_field_id not in (None, field_id):
            self._commit_inline_close()
        self._vm.open_inline(field_id)
        super().mouseDoubleClickEvent(event)

    # -- inline editing --------------------------------------------------------

    def _on_inline_changed(self, field_id) -> None:
        """Open/close the inline editor widget on the canvas (design D3)."""
        if self._inline_widget is not None:
            self._close_inline_widget()
        self._sync_handle_vis()
        if field_id is None:
            return
        item = self._items.get(field_id)
        if item is None:
            return
        field = item.field
        if field.type is FieldType.TEXTAREA:
            widget: QWidget = QPlainTextEdit()
        else:  # label, text, number — single line
            widget = QLineEdit()
        widget.setFont(sheet_font(field.font_size))
        initial = self._inline_initial_text(field)
        if isinstance(widget, QPlainTextEdit):
            widget.setPlainText(initial)
        else:
            widget.setText(initial)
        # label/text/textarea write live (one buffer); number commits on
        # Enter / close — an invalid value must not leak into the field
        if field.type is not FieldType.NUMBER:
            widget.textChanged.connect(lambda: self._on_inline_text_changed(field_id))
        if isinstance(widget, QLineEdit):
            if field.type is FieldType.NUMBER:
                widget.returnPressed.connect(
                    lambda f=field.id: self._commit_number_inline(f)
                )
            else:
                widget.returnPressed.connect(lambda: self._vm.commit_inline())
        widget.installEventFilter(self)

        widget.resize(int(field.w - 2), int(field.h - 2))
        self._inline_widget = widget
        # child of the field item: follows it on move
        proxy = QGraphicsProxyWidget(item)
        proxy.setPos(0.5, 0.5)
        proxy.setWidget(widget)
        widget.show()
        widget.setFocus()
        self._inline_proxy = proxy

    def _inline_initial_text(self, field: SheetField) -> str:
        if self._fill_mode and hasattr(self._vm, "display_value"):
            value = self._vm.display_value(field.id)
            return "" if value is None else str(value)
        return field.content

    def _on_inline_text_changed(self, field_id: str) -> None:
        """The inline widget is the single live buffer while editing: every
        keystroke lands in the VM (the same line the panel and the item read)."""
        widget = self._inline_widget
        if widget is None or field_id != self._vm.inline_field_id:
            return
        text = widget.toPlainText() if isinstance(widget, QPlainTextEdit) else widget.text()
        self._vm.set_content(field_id, text)

    def _commit_number_inline(self, field_id: str) -> None:
        """Enter on a number inline editor: accept if valid, else keep the
        old value and reshow it (the rejected value is not accepted, spec)."""
        widget = self._inline_widget
        if widget is None or field_id != self._vm.inline_field_id:
            return
        if self._vm.apply_number(field_id, widget.text()):
            self._vm.commit_inline()
        else:
            field = self._vm.template.get_field(field_id) if self._vm.template else None
            if field is not None:
                widget.blockSignals(True)
                widget.setText(self._inline_initial_text(field))
                widget.blockSignals(False)
                widget.selectAll()

    def _commit_inline_close(self) -> None:
        """Commit-close used by click-away / other-field / re-double-click:
        a number value is applied first (kept if rejected)."""
        field_id = self._vm.inline_field_id
        widget = self._inline_widget
        if (
            field_id is not None
            and widget is not None
            and not isinstance(widget, QPlainTextEdit)
        ):
            field = self._vm.template.get_field(field_id) if self._vm.template else None
            if field is not None and field.type is FieldType.NUMBER:
                self._vm.apply_number(field_id, widget.text())
        self._vm.commit_inline()

    def _sync_inline_widget(self) -> None:
        """Push a VM-side change (e.g. from the panel) into the open inline
        widget — no second buffer, one line."""
        field_id = self._vm.inline_field_id
        if field_id is None or self._inline_widget is None:
            return
        field = self._vm.template.get_field(field_id) if self._vm.template else None
        if field is None:
            return
        widget = self._inline_widget
        widget.blockSignals(True)
        try:
            if isinstance(widget, QPlainTextEdit):
                widget.setPlainText(self._inline_initial_text(field))
            else:
                widget.setText(self._inline_initial_text(field))
            widget.setFont(sheet_font(field.font_size))
        finally:
            widget.blockSignals(False)

    def _close_inline_widget(self) -> None:
        """Tear down the inline editor. Defensive against a half-torn-down
        state: if the field item the widget was parented to was already
        destroyed (e.g. its page was removed), the C++ proxy and widget are
        gone too — touching them would raise, so they are skipped."""
        from shiboken6 import delete, isValid

        widget = self._inline_widget
        if widget is not None:
            if isValid(widget):
                widget.removeEventFilter(self)
            else:
                widget = None  # C++ object already gone
            self._inline_widget = None
        proxy = self._inline_proxy
        self._inline_proxy = None
        if proxy is not None:
            if not isValid(proxy):
                return  # destroyed with its parent item
            proxy.setWidget(None)
            self.scene().removeItem(proxy)
            delete(proxy)  # deterministic C++ teardown order
        if widget is not None:
            widget.setParent(None)  # plain widget destroyed with its refcount

    def inline_edit(self) -> QWidget | None:
        """The widget being edited inline (or None)."""
        return self._inline_widget

    # -- keyboard --------------------------------------------------------------

    def eventFilter(self, obj, event) -> bool:
        if obj is self.verticalScrollBar() and event.type() in (
            QEvent.Type.Show,
            QEvent.Type.Hide,
        ):
            self._on_vbar_visibility(event.type() is QEvent.Type.Show)
        if (
            self._inline_widget is not None
            and obj is self._inline_widget
            and event.type() == QEvent.Type.KeyPress
        ):
            if event.key() == Qt.Key_Escape:
                self._vm.cancel_inline()
                return True
            if (
                isinstance(self._inline_widget, QPlainTextEdit)
                and event.key() in (Qt.Key_Return, Qt.Key_Enter)
                and (event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            ):
                self._vm.commit_inline()
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event) -> None:
        if self._fill_mode:
            if (
                event.key() == Qt.Key_Escape
                and self._vm.inline_field_id is None
            ):
                self._vm.select(None)
                return
            super().keyPressEvent(event)
            return
        if self._vm.inline_field_id is None:
            if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
                if self._vm.selected_ids:
                    self._vm.remove_selection()
                    return
            if event.key() == Qt.Key_Escape:
                self._vm.select(None)
                return
        super().keyPressEvent(event)

    # -- wheel: scroll the tape; Ctrl = zoom (D2) -------------------------------

    def wheelEvent(self, event) -> None:
        angle = event.angleDelta().y()
        if not angle:
            return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._zoom_at_cursor(event.position().toPoint(),
                                 ZOOM_STEP if angle > 0 else 1.0 / ZOOM_STEP)
        else:
            bar = self.verticalScrollBar()
            bar.setValue(bar.value() - angle)
        # no super(): the view must not zoom/scroll on its own

    def _zoom_at_cursor(self, cursor: QPointF, factor: float) -> None:
        """Zoom keeping the scene point under the cursor in place — the
        "same sheet" stays under the cursor (D2)."""
        before = self.mapToScene(cursor)
        current = self.transform().m11()
        new = max(MIN_ZOOM, min(MAX_ZOOM, current * factor))
        if new == current:
            return
        self.scale(new / current, new / current)
        after = self.mapToScene(cursor)
        dx = (after.x() - before.x()) * new
        dy = (after.y() - before.y()) * new
        h_bar = self.horizontalScrollBar()
        v_bar = self.verticalScrollBar()
        h_bar.setValue(int(h_bar.value() + dx))
        v_bar.setValue(int(v_bar.value() + dy))

    # -- view lifecycle ----------------------------------------------------------

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not self._fitted and self.viewport().width() > 0 and self.viewport().height() > 0:
            self.fit_width()
