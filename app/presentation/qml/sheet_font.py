"""The character-sheet island font (change Q3b, design D7).

Moved out of the widgets ``canvas.py`` when the canvas became a QML island:
the registration belongs to the island (the python side of the qml package),
not to the deleted paint-widget implementation this module replaces. The rules
are unchanged: one bundled DejaVu Sans for every sheet surface, registered
once per process via ``QFontDatabase.addApplicationFont`` (the TTF is not a
system font on all three OSes and the PDF shares these metrics); the text is
rendered at the field's own point size.

Called before any island loads: ``setup_qml_shell`` runs it while bringing the
one shared engine up, so no island can paint before the family exists.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtGui import QFont

log = logging.getLogger(__name__)

SHEET_FONT_FAMILY: str = "DejaVu Sans"

_font_registered = False


def _font_path() -> Path:
    """The bundled TTF, at the path the ``datas`` bundle already ships.

    ``register_sheet_font`` moved here but the font file did not (D7: the
    directory and the ``.spec`` datas stay as they were): the TTF stays in
    the character-sheet views directory. The same layout the dev tree holds
    in the PyInstaller bundle — the compiled module resolves
    inside the bundle right next to the datas-shipped ``fonts/`` directory,
    so no separate ``_MEIPASS`` lookup is needed.
    """
    return (
        Path(__file__).resolve().parents[1]
        / "views"
        / "character_sheet"
        / "fonts"
        / "DejaVuSans.ttf"
    )


def register_sheet_font() -> None:
    """Register the bundled DejaVu Sans (idempotent per process).

    A missing font file must be visible in the log: without it the canvas
    silently falls back to a default font (wrong metrics, later wrong PDF).
    """
    global _font_registered
    if _font_registered:
        return
    from PySide6.QtGui import QFontDatabase

    path = _font_path()
    font_id = QFontDatabase.addApplicationFont(str(path))
    if font_id < 0:
        log.warning("bundled sheet font failed to load: %s", path)
    _font_registered = True


def sheet_font(size_pt: float) -> QFont:
    """The single sheet font at a given point size."""
    font = QFont(SHEET_FONT_FAMILY)
    font.setPointSizeF(size_pt)
    return font
