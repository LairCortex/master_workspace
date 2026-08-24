"""Full-size image viewer (design D10, task 5.3).

A single ``QDialog`` (``QLabel`` inside a ``QScrollArea``) opened by clicking
an image slot in the entity card or the detail panel. Decoupled from ORM
entities on purpose: callers resolve the pixmaps themselves (``image_utils``)
so this dialog also works for a freshly picked, not-yet-saved file (no
entity row exists yet to resolve from).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget


class ImageViewerDialog(QDialog):
    """Shows ``original`` full-size; falls back to ``preview``; else a message.

    Degradation matches spec image-display: missing/undecodable original
    with a preview on disk shows the preview (with a note); missing both
    shows an explanatory message instead of an empty window.
    """

    def __init__(
        self,
        original: QPixmap | None,
        preview: QPixmap | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Просмотр изображения")
        self.resize(700, 600)

        layout = QVBoxLayout(self)

        pixmap: QPixmap | None = None
        used_preview = False
        if original is not None and not original.isNull():
            pixmap = original
        elif preview is not None and not preview.isNull():
            pixmap = preview
            used_preview = True

        if pixmap is None:
            message = QLabel("Изображение недоступно.")
            message.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(message, 1)
        else:
            image_label = QLabel()
            image_label.setPixmap(pixmap)
            scroll = QScrollArea()
            scroll.setWidgetResizable(False)
            scroll.setWidget(image_label)
            layout.addWidget(scroll, 1)
            if used_preview:
                note = QLabel("Оригинал недоступен — показан preview.")
                note.setAlignment(Qt.AlignmentFlag.AlignCenter)
                layout.addWidget(note)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)
