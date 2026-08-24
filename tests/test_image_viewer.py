"""Tests for ImageViewerDialog (design D10, task 5.3)."""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QKeyEvent, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QScrollArea

from app.presentation.views.image_viewer_dialog import ImageViewerDialog


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
    def test_original_pixmap_displayed_in_scroll_area(self, qapp):
        dlg = ImageViewerDialog(_pixmap(), QPixmap())
        scroll = dlg.findChild(QScrollArea)
        assert scroll is not None
        label = scroll.widget()
        assert isinstance(label, QLabel)
        assert not label.pixmap().isNull()
        # No "preview fallback" note when the original is present.
        assert "preview" not in " ".join(
            lbl.text() for lbl in dlg.findChildren(QLabel)
        ).lower()


class TestPreviewFallback:
    def test_missing_original_shows_preview_with_note(self, qapp):
        dlg = ImageViewerDialog(QPixmap(), _pixmap(200, 200))
        scroll = dlg.findChild(QScrollArea)
        assert scroll is not None
        label = scroll.widget()
        assert not label.pixmap().isNull()
        texts = [lbl.text() for lbl in dlg.findChildren(QLabel)]
        assert any("оригинал недоступен" in t.lower() for t in texts)

    def test_none_original_falls_back_to_preview(self, qapp):
        dlg = ImageViewerDialog(None, _pixmap())
        scroll = dlg.findChild(QScrollArea)
        assert scroll is not None
        assert not scroll.widget().pixmap().isNull()


class TestBothMissing:
    def test_both_missing_shows_message(self, qapp):
        dlg = ImageViewerDialog(QPixmap(), QPixmap())
        assert dlg.findChild(QScrollArea) is None
        texts = [lbl.text() for lbl in dlg.findChildren(QLabel)]
        assert any("недоступно" in t.lower() for t in texts)

    def test_both_none_shows_message(self, qapp):
        dlg = ImageViewerDialog(None, None)
        assert dlg.findChild(QScrollArea) is None


class TestCloseInteractions:
    def test_close_button_closes_dialog(self, qapp, qtbot):
        from PySide6.QtWidgets import QPushButton

        dlg = ImageViewerDialog(_pixmap())
        qtbot.addWidget(dlg)
        dlg.show()
        btn = dlg.findChild(QPushButton)
        assert btn is not None
        btn.click()
        assert not dlg.isVisible()

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
