"""Tests for ImageViewerDialog (design D10, task 5.3) — QML island."""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QKeyEvent, QPixmap
from PySide6.QtWidgets import QApplication

from app.presentation.views.image_viewer_dialog import ImageViewerDialog
from tests.presentation.qml_helpers import click_item, find_item


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _pixmap(w: int = 800, h: int = 600, color=Qt.GlobalColor.red) -> QPixmap:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(color)
    return QPixmap.fromImage(img)


class TestOriginalShown:
    def test_original_pixmap_displayed_in_scroll_area(self, qapp, qtbot):
        dlg = ImageViewerDialog(_pixmap(), QPixmap())
        qtbot.addWidget(dlg)
        image = find_item(dlg.quick, "viewerImage")
        source = image.property("source")
        text = source.toString() if hasattr(source, "toString") else str(source)
        assert text.startswith("image://dialog/")
        assert find_item(dlg.quick, "fallbackNote").property("visible") is False


class TestPreviewFallback:
    def test_missing_original_shows_preview_with_note(self, qapp, qtbot):
        dlg = ImageViewerDialog(QPixmap(), _pixmap(200, 200))
        qtbot.addWidget(dlg)
        assert find_item(dlg.quick, "fallbackNote").property("visible") is True

    def test_none_original_falls_back_to_preview(self, qapp, qtbot):
        dlg = ImageViewerDialog(None, _pixmap())
        qtbot.addWidget(dlg)
        source = find_item(dlg.quick, "viewerImage").property("source")
        text = source.toString() if hasattr(source, "toString") else str(source)
        assert "image://dialog/" in text


class TestBothMissing:
    def test_both_missing_shows_message(self, qapp, qtbot):
        dlg = ImageViewerDialog(QPixmap(), QPixmap())
        qtbot.addWidget(dlg)
        assert find_item(dlg.quick, "unavailableText").property("visible") is True

    def test_both_none_shows_message(self, qapp, qtbot):
        dlg = ImageViewerDialog(None, None)
        qtbot.addWidget(dlg)
        assert find_item(dlg.quick, "unavailableText").property("visible") is True


class TestCloseInteractions:
    def test_close_button_closes_dialog(self, qapp, qtbot):
        dlg = ImageViewerDialog(_pixmap())
        qtbot.addWidget(dlg)
        dlg.show()
        click_item(dlg.quick, find_item(dlg.quick, "closeButton"))
        qtbot.waitUntil(lambda: not dlg.isVisible(), timeout=2000)

    def test_escape_closes_dialog(self, qapp, qtbot):
        dlg = ImageViewerDialog(_pixmap())
        qtbot.addWidget(dlg)
        dlg.show()
        event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        dlg.keyPressEvent(event)
        assert not dlg.isVisible()

    def test_other_key_does_not_close(self, qapp, qtbot):
        dlg = ImageViewerDialog(_pixmap())
        qtbot.addWidget(dlg)
        dlg.show()
        event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier)
        dlg.keyPressEvent(event)
        assert dlg.isVisible()
