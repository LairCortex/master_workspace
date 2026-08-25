"""QGraphics items for the character sheet canvas.

Scene coordinates equal editor coordinates (pt, top-left origin): one
PageItem per page, FieldItems are its children so their local rect equals
the domain geometry (x, y, w, h). The model (viewmodel template) is the
single source of truth — items live-move during a gesture and commit the
final rect to the viewmodel once on mouse release (one undo snapshot).
"""
from __future__ import annotations

import gc

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPen
from PySide6.QtWidgets import QGraphicsObject, QGraphicsSimpleTextItem

from app.domain.entities.character_sheet import SheetField, SheetPage
from app.domain.enums.field_type import INTERACTIVE_FIELDS, FieldType

#: default size of the four corner resize handles, pt
HANDLE_SIZE = 8.0
#: minimum field size (kept in sync with the viewmodel clamp)
MIN_WIDTH = 20.0
MIN_HEIGHT = 10.0
#: gap between a field label and the top edge of its box, pt
_LABEL_GAP = 3.0

_GRID_COLOR = QColor(160, 160, 160, 60)  # semi-transparent (design D5)
_BORDER_PEN = QPen(QColor(0, 0, 0))
_WHITE_BRUSH = QBrush(Qt.GlobalColor.white)
_GRAY_PEN = QPen(QColor(120, 120, 120))


def _font(size: float, bold: bool = False) -> QFont:
    """Canvas font matching the PDF export size.

    Scene units are PDF pt; a Qt point renders 4/3 px per point at 96 dpi,
    so 0.75 keeps the preview text the same height as the exported PDF text.
    """
    font = QFont()
    font.setPointSizeF(max(1.0, size * 0.75))
    font.setBold(bold)
    return font


def _pointer_pos(event) -> QPointF:
    """Absolute pointer position in a STABLE frame for the drag math.

    Real dispatch delivers QGraphicsSceneMouseEvent (use scenePos()); the
    test doubles are plain QMouseEvent whose ``position()`` values are
    stable-frame by construction. A stable frame is required: mapping the
    pointer through the item subtracts the item's own preview movement and
    makes the edge track the mouse at half speed (review regression).
    """
    scene_pos = getattr(event, "scenePos", None)
    if callable(scene_pos):
        return scene_pos()
    return event.position()


class PageItem(QGraphicsObject):
    """A white A4 page with border and (optional) grid (design D5)."""

    def __init__(self, page: SheetPage, width: float, height: float) -> None:
        super().__init__()
        self.page = page
        self.size = QRectF(0, 0, width, height)
        self.grid_enabled = False
        self.grid_step = 20.0
        self.setCacheMode(QGraphicsObject.CacheMode.DeviceCoordinateCache)

    def set_grid(self, enabled: bool, step: float) -> None:
        self.grid_enabled = bool(enabled)
        self.grid_step = float(step)
        self.update()

    def boundingRect(self) -> QRectF:
        return self.size

    def paint(self, painter, option, widget=None) -> None:
        painter.fillRect(self.size, _WHITE_BRUSH)
        if self.grid_enabled and self.grid_step > 0:
            painter.setPen(QPen(_GRID_COLOR, 0.5, Qt.PenStyle.DotLine))
            x = 0.0
            while x <= self.size.width():
                painter.drawLine(QPointF(x, 0), QPointF(x, self.size.height()))
                x += self.grid_step
            y = 0.0
            while y <= self.size.height():
                painter.drawLine(QPointF(0, y), QPointF(self.size.width(), y))
                y += self.grid_step
        painter.setPen(_BORDER_PEN)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self.size)


class _ResizeHandle(QGraphicsObject):
    """A corner handle: drags preview the new rect, releases commit it."""

    def __init__(self, field_item: "FieldItem", sx: int, sy: int) -> None:
        super().__init__(field_item)  # parent item set via the constructor
        self._field_item = field_item
        self._corner = (sx, sy)  # (-1 | +1, -1 | +1): which box corner
        self._drag_start: QPointF | None = None
        self._rect_start: QRectF | None = None

    def boundingRect(self) -> QRectF:
        return QRectF(-HANDLE_SIZE / 2, -HANDLE_SIZE / 2, HANDLE_SIZE, HANDLE_SIZE)

    def paint(self, painter, option, widget=None) -> None:
        painter.setBrush(QBrush(Qt.GlobalColor.white))
        painter.setPen(QPen(QColor(0, 0, 0)))
        painter.drawRect(self.boundingRect())

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = _pointer_pos(event)
            self._rect_start = self._field_item.rect
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_start is None or self._rect_start is None:
            return
        pos = _pointer_pos(event)
        start = self._rect_start
        dx = pos.x() - self._drag_start.x()
        dy = pos.y() - self._drag_start.y()
        sx, sy = self._corner
        left, right = start.left(), start.right()
        top, bottom = start.top(), start.bottom()
        if sx == -1:
            left = min(left + dx, right - MIN_WIDTH)  # left edge limited by the opposite one
        else:
            right = max(right + dx, left + MIN_WIDTH)
        if sy == -1:
            top = min(top + dy, bottom - MIN_HEIGHT)
        else:
            bottom = max(bottom + dy, top + MIN_HEIGHT)
        self._field_item.preview_rect(QRectF(left, top, right - left, bottom - top))
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_start is None:
            return
        self._drag_start = None
        self._rect_start = None
        self._field_item.commit_rect()
        event.accept()


class FieldItem(QGraphicsObject):
    """One field: static appearance, selection, four corner resize handles.

    Dragging is implemented manually (no ItemIsMovable flag): the base
    QGraphicsItem drag/select logic needs real QGraphicsSceneMouseEvent
    objects and would fight the editor's commit-on-release semantics.
    """

    def __init__(self, field: SheetField, parent: QGraphicsObject | None = None) -> None:
        # The constructor links child items to this (still-constructing) one;
        # Qt re-enters the Python itemChange() from inside the C++ linking
        # calls. If the cyclic GC starts collecting mid-reentry it can tear
        # down Qt objects in use by that very C++ call (segfault observed in
        # the full test suite under coverage tracing). Keep this window
        # GC-free and restore the previous GC state afterwards.
        gc_was_enabled = gc.isenabled()
        gc.disable()
        try:
            self._init_impl(field, parent)
        finally:
            if gc_was_enabled:
                gc.enable()

    def _init_impl(self, field: SheetField, parent: QGraphicsObject | None) -> None:
        super().__init__(parent)
        self.field = field
        self._viewmodel = None  # set by the canvas
        self._destroying = False  # set before deferred C++ deletion
        self._drag_moved = False
        self._drag_start: QPointF | None = None  # item pos at press
        self._press_pos: QPointF | None = None  # stable-frame pointer pos at press
        # must exist before sync_from_field: prepareGeometryChange() calls
        # boundingRect() -> rect -> _w/_h
        self._w, self._h = 0.0, 0.0
        self.setFlag(QGraphicsObject.GraphicsItemFlag.ItemIsSelectable, True)
        self._label = QGraphicsSimpleTextItem("", self)
        self._handles = [
            _ResizeHandle(self, sx, sy)
            for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))
        ]
        for handle in self._handles:
            handle.setVisible(False)
        self.sync_from_field()

    # ── geometry sync ─────────────────────────────────────────────────────

    def sync_from_field(self) -> None:
        """Adopt the domain geometry (called on canvas re-sync)."""
        f = self.field
        self.prepareGeometryChange()
        self.setPos(f.x, f.y)
        self._set_size(f.w, f.h)

    def _set_size(self, w: float, h: float) -> None:
        self.prepareGeometryChange()
        self._w, self._h = w, h
        self._update_handles()
        self._sync_label()
        self.update()

    @property
    def rect(self) -> QRectF:
        # QRectF(QPointF, QPointF) is a two-CORNERS ctor — spell out x/y/w/h.
        # getattr: boundingRect() (hence rect) can run during C++ teardown
        # before __init__ stores _w/_h.
        return QRectF(
            self.pos().x(), self.pos().y(),
            getattr(self, "_w", 0.0), getattr(self, "_h", 0.0),
        )

    def preview_rect(self, new_rect: QRectF) -> None:
        """Live drag/resize preview (no model change yet)."""
        self.prepareGeometryChange()
        self.setPos(new_rect.x(), new_rect.y())
        self._set_size(new_rect.width(), new_rect.height())

    def commit_rect(self) -> None:
        """Push the final rect into the viewmodel (one undo snapshot)."""
        if self._viewmodel is None:
            return
        rect = self.rect
        current = self.field
        if (rect.x(), rect.y(), rect.width(), rect.height()) == (
            current.x, current.y, current.w, current.h
        ):
            return  # a plain click: no geometry change, no snapshot
        self._viewmodel.set_field_rect(
            current.id, rect.x(), rect.y(), rect.width(), rect.height()
        )

    # ── appearance ────────────────────────────────────────────────────────

    def _sync_label(self) -> None:
        f = self.field
        if f.label and f.type in INTERACTIVE_FIELDS:
            self._label.setText(f.label)
            self._label.setFont(_font(f.font_size))
            self._label.setBrush(QBrush(QColor(0, 0, 0)))
            self._label.setPos(0, -f.font_size - _LABEL_GAP)
        else:
            self._label.setText("")

    def _update_handles(self) -> None:
        r = self.rect
        corners = [
            (0.0, 0.0),
            (r.width(), 0.0),
            (r.width(), r.height()),
            (0.0, r.height()),
        ]
        for handle, (cx, cy) in zip(self._handles, corners):
            handle.setPos(cx, cy)

    # ── Qt item events ────────────────────────────────────────────────────

    def itemChange(self, change, value):
        # Qt re-enters this virtual from ~QGraphicsItem during C++ deletion —
        # getattr guards the window before __init__ stores the attribute
        destroying = getattr(self, "_destroying", False)
        if change == QGraphicsObject.GraphicsItemChange.ItemSelectedChange:
            selected = bool(value)
            if not destroying:
                for handle in getattr(self, "_handles", ()):
                    handle.setVisible(selected)
                if self._viewmodel is not None:
                    self._viewmodel.select(self.field.id if selected else None)
            return value
        if destroying:
            # scene state is not used on a dying item — skipping the C++ base
            # avoids a re-entrant call into an object being destroyed
            return False
        return super().itemChange(change, value)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            # single-selection: a click selects this field, drops the others
            scene = self.scene()
            if scene is not None:
                for other in scene.selectedItems():
                    other.setSelected(False)
            self.setSelected(True)
            self._drag_start = self.pos()
            self._press_pos = _pointer_pos(event)
            self._drag_moved = False
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if (
            self._drag_start is not None
            and self._press_pos is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            self.setPos(self._drag_start + (_pointer_pos(event) - self._press_pos))
            self._drag_moved = True
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_moved:
            self.commit_rect()
        self._drag_moved = False
        self._drag_start = None
        self._press_pos = None
        event.accept()

    def boundingRect(self) -> QRectF:
        # include the label above the box
        r = self.rect
        top = -self.field.font_size - _LABEL_GAP - 2 if (
            self.field.label and self.field.type in INTERACTIVE_FIELDS
        ) else 0.0
        return QRectF(0, min(0.0, top), r.width(), max(r.height(), r.height() - top) + 2)

    def paint(self, painter, option, widget=None) -> None:
        r = self.rect
        f = self.field
        painter.setPen(_BORDER_PEN)
        if f.type in INTERACTIVE_FIELDS:
            painter.setBrush(_WHITE_BRUSH)
            painter.drawRect(r)
            if f.type is FieldType.CHECKBOX and f.initial_checked:
                painter.drawLine(r.topLeft() + QPointF(4, 4), r.bottomRight() - QPointF(4, 4))
                painter.drawLine(r.topRight() - QPointF(4, 4), r.bottomLeft() + QPointF(4, 4))
        elif f.type is FieldType.PORTRAIT:
            painter.setBrush(_WHITE_BRUSH)
            painter.drawRect(r)
            painter.setPen(_GRAY_PEN)
            self._draw_centered(painter, "Портрет", r, 12.0)
            painter.setPen(_BORDER_PEN)
        else:  # HEADING / STATIC_TEXT
            painter.setFont(_font(f.font_size, bold=f.type is FieldType.HEADING))
            leading = f.font_size * 1.2
            for i, line in enumerate(f.label.split("\n")):
                painter.drawText(QPointF(0, (i + 1) * leading), line)

    def _draw_centered(self, painter, text: str, r: QRectF, size: float) -> None:
        font = _font(size)
        painter.setFont(font)
        text_w = QFontMetrics(font).horizontalAdvance(text)
        painter.drawText(QPointF(r.width() / 2 - text_w / 2, r.height() / 2 + size / 3), text)
