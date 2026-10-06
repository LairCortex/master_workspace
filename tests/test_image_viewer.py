"""Tests for ImageViewerDialog (design D10, task 5.3) — QML island."""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent, QPixmap
from PySide6.QtWidgets import QApplication

from app.presentation.utils.clipboard_utils import copy_pixmap, copy_text
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


# ── «Копировать» → the system clipboard (user request 2026-10-05) ─────────────


class TestClipboardHelper:
    """The one clipboard knowledge lives in ``utils/clipboard_utils`` (AGENTS
    principle 2): the image half lands, both no-image halves refuse silently."""

    def test_copy_pixmap_lands_the_image(self, qapp):
        qapp.clipboard().clear()
        assert copy_pixmap(_pixmap(3, 3, Qt.GlobalColor.blue)) is True
        image = qapp.clipboard().image()
        assert (image.width(), image.height()) == (3, 3)
        assert image.pixelColor(1, 1).name() == QColor(Qt.GlobalColor.blue).name()

    @pytest.mark.parametrize("kind", ["none", "null"])
    def test_copy_pixmap_refuses_and_leaves_the_clipboard_alone(self, qapp, kind):
        qapp.clipboard().setText("сторонняя строка")
        assert copy_pixmap(None if kind == "none" else QPixmap()) is False
        assert qapp.clipboard().text() == "сторонняя строка"

    def test_copy_text_lands_the_string(self, qapp):
        qapp.clipboard().clear()
        assert copy_text("http://10.0.0.9:7845/") is True
        assert qapp.clipboard().text() == "http://10.0.0.9:7845/"

    @pytest.mark.parametrize("kind", ["none", "empty"])
    def test_copy_text_refuses_and_leaves_the_clipboard_alone(self, qapp, kind):
        qapp.clipboard().setText("сторонняя строка")
        assert copy_text(None if kind == "none" else "") is False
        assert qapp.clipboard().text() == "сторонняя строка"


class TestCopyButton:
    """The island's «Копировать» copies what the sheet SHOWS — the original,
    else the preview — and with no image it neither crashes nor overwrites
    what the user had copied before."""

    @pytest.fixture(autouse=True)
    def _clean_clipboard(self, qapp):
        # Every case starts and ends on an empty buffer: no test inherits the
        # image another one copied, nothing is left in the user's clipboard.
        qapp.clipboard().clear()
        yield
        qapp.clipboard().clear()

    def test_button_is_a_worded_theme_button_in_the_close_band(self, qapp, qtbot):
        dlg = ImageViewerDialog(_pixmap())
        qtbot.addWidget(dlg)
        copy = find_item(dlg.quick, "copyButton")
        assert copy.property("text") == "Копировать"
        assert copy.property("iconName") == "copy"
        # Same band as «Закрыть» (one RowLayout), so no second chrome row.
        assert copy.parentItem() is find_item(dlg.quick, "closeButton").parentItem()
        # The sheet's Enter keeps the exit outcome: the copy button is never
        # the island's default action.
        assert dlg._root.property("defaultButton").objectName() == "closeButton"

    def test_click_copies_the_original(self, qapp, qtbot):
        dlg = ImageViewerDialog(
            _pixmap(7, 5, Qt.GlobalColor.green),
            _pixmap(3, 3, Qt.GlobalColor.blue),
        )
        qtbot.addWidget(dlg)
        dlg.show()
        click_item(dlg.quick, find_item(dlg.quick, "copyButton"))
        image = qapp.clipboard().image()
        assert (image.width(), image.height()) == (7, 5)
        assert image.pixelColor(0, 0).name() == QColor(Qt.GlobalColor.green).name()

    def test_click_copies_the_preview_when_the_original_is_missing(self, qapp, qtbot):
        dlg = ImageViewerDialog(QPixmap(), _pixmap(4, 6, Qt.GlobalColor.red))
        qtbot.addWidget(dlg)
        dlg.show()
        click_item(dlg.quick, find_item(dlg.quick, "copyButton"))
        image = qapp.clipboard().image()
        assert (image.width(), image.height()) == (4, 6)
        assert image.pixelColor(0, 0).name() == QColor(Qt.GlobalColor.red).name()

    def test_click_without_any_image_keeps_the_clipboard_untouched(self, qapp, qtbot):
        qapp.clipboard().setText("сторонняя строка")
        dlg = ImageViewerDialog(None, None)
        qtbot.addWidget(dlg)
        dlg.show()
        click_item(dlg.quick, find_item(dlg.quick, "copyButton"))
        assert qapp.clipboard().text() == "сторонняя строка"
        assert qapp.clipboard().image().isNull()
        assert dlg.isVisible()
