"""World snapshot QML island behind the existing panel facade."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from PySide6.QtCore import QPoint, QRect, QSize, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPixmap
from PySide6.QtQml import QQmlComponent, QQmlContext
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from app.presentation.qml import setup_qml_shell
from app.presentation.qml.engine import QML_IMPORT_PATH, release_island
from app.presentation.qml.tooltip_shim import install_island_tooltips
from app.presentation.theme import get_default_theme
from app.presentation.theme.qml_palette import QmlPalette
from app.presentation.viewmodels.world_snapshot_view_model import (
    WorldSnapshotViewModel,
)
from app.presentation.views.theme_date_popup import ThemeDatePopup


ROOT_QML = str(Path(QML_IMPORT_PATH) / "WorldSnapshotRoot.qml")


def _colored_circle(color: QColor, size: int = 16) -> QIcon:
    """Compatibility helper retained for callers that build legend icons."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QBrush(color))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(1, 1, size - 2, size - 2)
    painter.end()
    return QIcon(pixmap)


class WorldSnapshotWidget(QWidget):
    """Thin shared-engine island preserving the original wiring surface."""

    entity_clicked = Signal(str, int)
    snapshot_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None, theme=None) -> None:
        super().__init__(parent)
        self._theme = theme if theme is not None else get_default_theme()
        self.vm = WorldSnapshotViewModel(self._theme, parent=self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        engine = setup_qml_shell(QApplication.instance(), self._theme)
        self._engine = engine
        self.quick = QQuickWidget(engine, self)
        self.quick.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self._palette = QmlPalette(self._theme, parent=self)
        self._context = QQmlContext(engine.rootContext(), self)
        self.vm.setParent(self._context)
        self._palette.setParent(self._context)
        self._context.setContextProperty("worldSnapshotVm", self.vm)
        self._context.setContextProperty("islandPalette", self._palette)
        self._tooltip_bridge = install_island_tooltips(self.quick, self._context)

        source = QUrl.fromLocalFile(ROOT_QML)
        self._component = QQmlComponent(engine, source, self)
        root = self._component.create(self._context)
        assert root is not None, self._component.errors()
        self.quick.setContent(source, self._component, root)
        assert self.quick.status() == QQuickWidget.Status.Ready, self.quick.errors()
        layout.addWidget(self.quick)
        self._root = self.quick.rootObject()

        self.date_popup = ThemeDatePopup(self)
        self.date_popup.date_selected.connect(self.vm.set_date)
        self.vm.datePopupRequested.connect(self._open_date_popup)
        self.vm.snapshotRequested.connect(self.snapshot_requested.emit)
        self.vm.entitySelected.connect(self.entity_clicked.emit)

    def populate(self, events: Sequence[Any], for_date: Any) -> None:
        # ``for_date`` is the snapshot bridge payload: a (coordinate, era)
        # pair since piece C3a (a bare date or None stay legal) — the ViewModel
        # splits it.
        self.vm.populate(events, for_date)

    def _open_date_popup(
        self, x: float, y: float, width: float, height: float
    ) -> None:
        top_left = self.quick.mapToGlobal(QPoint(int(x), int(y)))
        anchor = QRect(
            top_left,
            QSize(max(int(width), 0), max(int(height), 0)),
        )
        # Since piece C3b (design D3) the popup grid paints the snapshot's
        # coordinate itself (intercalary chip included) — the picture-only
        # clamp of piece C3a died with the Gregorian widget, so the bridge
        # carries the coordinate pair as stored.
        self.date_popup.open_at(anchor, (self.vm._date, self.vm._date_bc))

    def _on_clear(self) -> None:
        self.vm.clear()

    def _release_island(self) -> None:
        release_island(self.quick)

    def closeEvent(self, event) -> None:  # Qt API name
        QTimer.singleShot(0, self, self._release_island)
        super().closeEvent(event)
