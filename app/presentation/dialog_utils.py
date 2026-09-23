"""Shared dialog helpers (design D3, audit A5).

The discard-changes confirmation was copy-pasted four times in ``main.py``
(game switch, table master, sheet switch ×2): the same question box, the
same buttons, the same default — only the text differed. One function now
owns the box; each call site contributes only its own sentence.
"""
from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from app.domain.allowed_image_extensions import ALLOWED_IMAGE_EXTENSIONS

_DISCARD_TITLE = "Несохранённые изменения"

#: Filter for image pickers, built from the domain whitelist so the dialog
#: can never offer a file the import/pipeline rules would reject (audit A5).
IMAGE_FILE_FILTER = (
    "Изображения ("
    + " ".join(f"*{ext}" for ext in ALLOWED_IMAGE_EXTENSIONS)
    + ");;Все файлы (*)"
)


def confirm_discard(parent, text: str) -> bool:
    """Ask whether unsaved changes may be lost; True = proceed without saving.

    The same Yes/No box everywhere: No is the default, so Enter/Escape keep
    the current window, and only an explicit Yes discards the edits.
    """
    answer = QMessageBox.question(
        parent,
        _DISCARD_TITLE,
        text,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return answer == QMessageBox.StandardButton.Yes
