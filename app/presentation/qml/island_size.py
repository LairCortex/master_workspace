"""Window sizing driven by the QML island's own content size.

A ``QQuickWidget`` in ``SizeRootObjectToView`` never reports the scene's
implicit size as a layout hint (the same seam ``search_bar.py`` works around
for the height), so a dialog that hardcodes ``resize()`` opens whatever box the
port happened to pick. Whenever that box is smaller than the island's content,
the layouts squeeze their widgets and the last rows fall off the window — the
card lost its «Сохранить»/«Отмена» row, the sheet list its whole button row.

The islands publish their natural size through ``implicitWidth`` /
``implicitHeight`` (derived from the content layout, with the port's original
numbers kept as the floor); the facades mirror it onto the window here. A dialog
may never cover the whole screen — the rest has to stay reachable — so the
requested size is capped by the screen's available geometry.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QSize
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickItem
from PySide6.QtWidgets import QDialog

#: Biggest share of the screen a single dialog is allowed to take.
SCREEN_COVER_LIMIT = 0.9

log = logging.getLogger(__name__)


def _screen_limit(dialog: QDialog) -> QSize:
    window = dialog.window()
    screen = window.screen() if window is not None else None
    if screen is None:
        screen = QGuiApplication.primaryScreen()
    if screen is None:  # headless without any screen: no cap at all
        return QSize(100000, 100000)
    geometry = screen.availableGeometry()
    return QSize(
        max(1, int(geometry.width() * SCREEN_COVER_LIMIT)),
        max(1, int(geometry.height() * SCREEN_COVER_LIMIT)),
    )


def _natural_size(root: QQuickItem | None, floor: tuple[int, int]) -> tuple[int, int]:
    """What the island asked for, never below the ``floor`` it came with.

    A broken island (no root object) must not open a 0x0 window either — it
    gets the size its port used to pin.
    """
    if root is None:
        return floor
    return (
        max(floor[0], int(round(root.implicitWidth()))),
        max(floor[1], int(round(root.implicitHeight()))),
    )


def fit_dialog_to_island(
    dialog: QDialog,
    root: QQuickItem | None,
    *,
    floor: tuple[int, int],
) -> QSize:
    """Open ``dialog`` at the island's natural size, capped by the screen.

    ``floor`` is the size the port used to hardcode: the content may ask for
    more, never less. Only ``resize`` is touched — every facade keeps its own
    ``setMinimumSize``, so the window stays shrinkable (the islands keep their
    scroll machinery for that); this decides how a window opens. The window's
    own minimum size wins over the screen cap (Qt refuses a smaller resize), so
    the returned size is the one the dialog ended up with.
    """
    limit = _screen_limit(dialog)
    natural = _natural_size(root, floor)
    dialog.resize(QSize(*natural).boundedTo(limit))
    size = dialog.size()  # read back: Qt keeps the dialog's own minimum size
    log.debug(
        "island fit for %s: scene %sx%s -> window %sx%s (screen cap %sx%s)",
        dialog.metaObject().className(),
        natural[0], natural[1], size.width(), size.height(),
        limit.width(), limit.height(),
    )
    return size
