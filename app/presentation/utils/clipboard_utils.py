"""System clipboard — the ONLY place the app reaches ``QApplication.clipboard()``.

The reader's request 2026-10-05: a picture shown in the «Просмотр изображения»
sheet must be copyable into the system clipboard. Coding principle 2 (one
knowledge, one place) keeps the Qt details here: the ``QPixmap`` → ``QImage``
conversion ``QClipboard::setImage`` demands, the clipboard's own lookup, and the
refusal rule for a missing image. A usage site hands over a pixmap and never
touches the clipboard object itself, so a second surface that later wants to
copy an image reuses this call instead of re-deriving the conversion. The text
half joined the same roof the same day (the «Стол» desk copying its LAN
address): a site hands over a string, and the empty text of a surface that has
nothing to offer is refused exactly like a null image.
"""
from __future__ import annotations

from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication


def copy_pixmap(pixmap: QPixmap | None) -> bool:
    """Put ``pixmap`` into the system clipboard as an image.

    Returns True when the image landed. ``None`` or a null pixmap answers False
    and leaves the clipboard EXACTLY as it was — a viewer opened over a missing
    file must not push a null image through and wipe what the user copied.
    """
    if pixmap is None or pixmap.isNull():
        return False
    QApplication.clipboard().setImage(pixmap.toImage())
    return True


def copy_text(text: str | None) -> bool:
    """Put ``text`` into the system clipboard as plain text.

    Returns True when the text landed. ``None`` or an empty string answers
    False and leaves the clipboard EXACTLY as it was — a desk whose table is
    not up yet must not push an empty address through and wipe the copy the
    user made before.
    """
    if not text:
        return False
    QApplication.clipboard().setText(text)
    return True
