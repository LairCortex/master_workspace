"""Editor canvas: one vertical column of pages, zoom/pan/fit, grid (D5)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QPoint, QRectF, Qt
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView

from app.domain.enums.sheet_orientation import a4_size

from app.presentation.views.character_sheet.canvas_items import (
    FieldItem,
    PageItem,
)

#: gap between pages in the column, pt
PAGE_MARGIN = 40.0

#: zoom limits — 25% … 400% (task 6.1)
MIN_ZOOM = 0.25
MAX_ZOOM = 4.0
ZOOM_FACTOR = 1.15


class SheetCanvas(QGraphicsScene):
    """Scene: pages as a column, field items rebuilt from the model.

    ``refresh()`` recreates everything from the template — the model is the
    single source of truth and a full rebuild is cheap for sheet-sized
    documents (design D6: documents are small).
    """

    def __init__(self, viewmodel=None) -> None:
        super().__init__()
        self._viewmodel = viewmodel
        self._page_items: list[PageItem] = []

    # ── lifecycle ─────────────────────────────────────────────────────────

    def clear(self) -> None:
        """Sever Python↔C++ links before the deferred item deletion.

        FieldItems keep the viewmodel in ``_viewmodel``; if a page item's C++
        destructor cascades into them while the viewmodel is being torn down,
        the re-entered ``itemChange`` would call into dying objects. Detaching
        the children and nulling the link first makes the cascade inert.
        """
        for item in self._page_items:
            self._drop_page(item)
        self._page_items = []

    def _drop_page(self, page_item: PageItem) -> None:
        self.removeItem(page_item)
        for child in list(page_item.childItems()):
            if isinstance(child, FieldItem):
                child._destroying = True
                child._viewmodel = None
            child.setParentItem(None)
            child.deleteLater()
        page_item.deleteLater()

    def __del__(self) -> None:  # pragma: no cover — finalizer timing is GC-dependent; see _shutdown_clear
        self._shutdown_clear()

    def _shutdown_clear(self) -> None:
        """clear() with a safety net for interpreter-shutdown races."""
        try:
            self.clear()
        except Exception:
            pass  # interpreter/Qt may already be gone at shutdown

    # ── rebuild ───────────────────────────────────────────────────────────

    def refresh(self) -> None:
        template = None if self._viewmodel is None else self._viewmodel.template
        if template is None:
            return
        selected_id = self._viewmodel.selected_field_id

        for item in self._page_items:
            self._drop_page(item)
        self._page_items = []

        page_w, page_h = a4_size(template.orientation)
        for index, page in enumerate(template.pages):
            page_item = PageItem(page, page_w, page_h)
            page_item.setPos(PAGE_MARGIN, PAGE_MARGIN + index * (page_h + PAGE_MARGIN))
            self.addItem(page_item)
            self._page_items.append(page_item)
            for field in page.fields:
                field_item = FieldItem(field, page_item)
                field_item._viewmodel = self._viewmodel

        for page_item in self._page_items:
            for field_index, child in enumerate(page_item.childItems()):
                if isinstance(child, FieldItem):
                    child.setZValue(float(field_index))

        for page_item in self._page_items:
            for child in page_item.childItems():
                if isinstance(child, FieldItem) and child.field.id == selected_id:
                    child.setSelected(True)

        self.setSceneRect(self._column_rect())

    def _column_rect(self) -> QRectF:
        if not self._page_items:
            return QRectF(0, 0, 100, 100)
        last = self._page_items[-1]
        return QRectF(
            0, 0,
            max(last.x() + last.size.width() + PAGE_MARGIN, 100.0),
            max(last.y() + last.size.height() + PAGE_MARGIN, 100.0),
        )

    # ── grid ──────────────────────────────────────────────────────────────

    def set_grid(self, enabled: bool, step: float) -> None:
        for item in self._page_items:
            item.set_grid(enabled, step)

    # ── queries ───────────────────────────────────────────────────────────

    def page_index_at(self, scene_point: QPointF) -> int | None:
        for index, item in enumerate(self._page_items):
            if item.sceneBoundingRect().contains(scene_point):
                return index
        return None

    def page_index_at_view_center(self, view: "SheetCanvasView") -> int:
        """Page nearest to the viewport center (palette add target, D5)."""
        scene_point = view.mapToScene(
            QPoint(view.viewport().width() // 2, view.viewport().height() // 2)
        )
        index = self.page_index_at(scene_point)
        if index is not None:
            return index
        best, best_dist = 0, float("inf")
        for i, item in enumerate(self._page_items):
            d = abs(item.sceneBoundingRect().center().x() - scene_point.x())
            d = max(d, abs(item.sceneBoundingRect().center().y() - scene_point.y()))
            if d < best_dist:
                best, best_dist = i, d
        return best


class SheetCanvasView(QGraphicsView):
    """View: Ctrl+wheel zoom to cursor (25–400%), middle/Space pan, fit."""

    def __init__(self, canvas: SheetCanvas, parent=None) -> None:
        super().__init__(canvas, parent)
        self.canvas = canvas
        # Left button goes to the scene (rubber-band selection / the items'
        # own drag logic); the middle button or Space+left pans manually
        # (mouse* handlers below). ScrollHandDrag must NOT be used: it
        # intercepts the left button and the items never receive events.
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        # _zoom_toward shifts the scrollbars with an explicit zoom-about-point
        # recipe. The default AnchorViewCenter would auto-adjust them on every
        # scale() to keep the viewport center stationary and double-correct
        # the anchor (Ctrl+wheel drift observed in the full-dispatch check).
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        # _zoom_toward shifts the scrollbars with an explicit zoom-about-point
        # recipe. The default AnchorViewCenter would auto-adjust them on every
        # scale() to keep the viewport center stationary and double-correct
        # the anchor (Ctrl+wheel drift observed in the full-dispatch check).
        self._space_pressed = False
        self._panning = False
        self._pan_start = QPoint()

    # ── zoom ──────────────────────────────────────────────────────────────

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            scale = ZOOM_FACTOR if event.angleDelta().y() > 0 else 1 / ZOOM_FACTOR
            self._zoom_toward(scale, event.position().toPoint())
            event.accept()
            return
        super().wheelEvent(event)

    def zoom_by(self, factor: float) -> None:
        """Zoom toward the viewport center (toolbar −/+ buttons)."""
        self._zoom_toward(factor, self.viewport().rect().center())

    def _zoom_toward(self, factor: float, anchor: QPoint) -> None:
        """Zoom with the scene point under ``anchor`` kept stationary."""
        current = self.transform().m11()
        target = max(MIN_ZOOM, min(MAX_ZOOM, current * factor))
        if target == current:
            return
        ratio = target / current
        self.scale(ratio, ratio)
        # Qt's zoom-about-a-point recipe: shift the scrollbars so the point
        # under the anchor stays under it.
        horizontal = self.horizontalScrollBar()
        vertical = self.verticalScrollBar()
        horizontal.setValue(horizontal.value() * ratio + anchor.x() * (ratio - 1.0))
        vertical.setValue(vertical.value() * ratio + anchor.y() * (ratio - 1.0))

    def fit_to_window(self) -> None:
        self.fitInView(self.canvas.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    # ── panning: Space+left as an alternative to the middle button ─────────

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_pressed = True
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Space:
            self._space_pressed = False
            self.unsetCursor()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def mousePressEvent(self, event) -> None:
        button = event.button()
        if button == Qt.MouseButton.MiddleButton or (
            button == Qt.MouseButton.LeftButton and self._space_pressed
        ):
            self._panning = True
            self._pan_start = event.position().toPoint()
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._panning:
            delta = event.position().toPoint() - self._pan_start
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta.x()
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - delta.y()
            )
            self._pan_start = event.position().toPoint()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._panning:
            self._panning = False
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
            event.accept()
            return
        super().mouseReleaseEvent(event)
