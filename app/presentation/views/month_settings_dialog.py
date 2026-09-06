"""Dialog for configuring custom month names — QML island (R3 pack 1)."""
from __future__ import annotations

from pathlib import Path
from typing import Dict

from PySide6.QtCore import QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout, QWidget

from app.presentation.qml import setup_qml_shell
from app.presentation.qml.engine import QML_IMPORT_PATH, island_context, load_island
from app.presentation.theme import get_default_theme
from app.presentation.theme.qml_palette import QmlPalette
from app.presentation.viewmodels.month_settings_view_model import MonthSettingsViewModel

ROOT_QML = str(Path(QML_IMPORT_PATH) / "MonthSettingsRoot.qml")


class MonthSettingsDialog(QDialog):
    saved = Signal(object)

    def __init__(
        self,
        current_months: Dict[int, str] | None = None,
        parent: QWidget | None = None,
        theme=None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme if theme is not None else get_default_theme()
        self.setWindowTitle("Названия месяцев")
        self.setMinimumWidth(380)

        self.vm = MonthSettingsViewModel(current_months, parent=self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        engine = setup_qml_shell(QApplication.instance(), self._theme)
        self._engine = engine
        self.quick = QQuickWidget(engine, self)
        self.quick.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self._palette = QmlPalette(self._theme, parent=self)
        # A dialog's names stay in a dialog-owned context: the shared engine's
        # root context has one global slot per name, nulled for every live
        # island when the facade that wrote it dies.
        self._context = island_context(
            engine, self, monthSettingsVm=self.vm, islandPalette=self._palette
        )
        self._palette.setParent(self._context)
        self._component = load_island(self.quick, self._context, ROOT_QML)
        assert self.quick.status() == QQuickWidget.Status.Ready, self.quick.errors()
        layout.addWidget(self.quick)
        self._root = self.quick.rootObject()
        self._root.saveRequested.connect(self._on_save)
        self._root.cancelRequested.connect(self.reject)
        self.vm.saved.connect(self.saved)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            marker = self._root.property("defaultButton") if self._root is not None else None
            clicked = getattr(marker, "clicked", None) if marker is not None else None
            if clicked is not None:
                clicked.emit()
                return
        super().keyPressEvent(event)

    def _on_save(self) -> None:
        self.vm.save()
        self.accept()

    def _release_island(self) -> None:
        self.quick.setSource(QUrl())

    def done(self, result: int) -> None:
        QTimer.singleShot(0, self, self._release_island)
        super().done(result)
