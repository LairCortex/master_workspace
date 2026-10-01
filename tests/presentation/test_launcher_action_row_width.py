"""Launcher action row never clips at the window minimum (F1, live audit
docs/qa/2026-09-30-lucide-pass-main-window.md).

The Lucide pass gave each of the launcher's four action buttons a 16 px
glyph plus the shared ``iconGap`` — 20 px per button — and the bottom row
(«Новая игра» · «Импорт» · ☐ «Светлая тема» · «Удалить» · «Открыть») stopped
fitting the 480-step island: live, «Открыть» was cut by the window's right
edge. The row width is font-metric dependent, so the gate is geometric (the
right-edge pattern of ``test_island_dialog_sizing.test_sheet_list_buttons_keep_their_own_width_on_both_tabs``)
on the real dialog at its own minimum width: the row's rightmost control ends
inside the island with the content inset kept, and the measured worst case
is pinned so a future caption cannot silently shrink the window back — the
minimum may only stay as long as it covers the row.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF

from app.presentation.layout_grid import ceil_to_width_step
from app.presentation.theme import get_default_theme
from app.presentation.views.game_launcher_dialog import GameLauncherDialog
from tests.presentation.qml_helpers import find_item

#: Column insets of the island (``space.md``, same constant as the sheet
#: inset pin in test_window_width_scale.py).
CONTENT_INSET_PX = 16

#: Inter-control gap of the row (``space.sm`` of LauncherRoot's RowLayout).
ROW_GAP_PX = 8


def _pump(qtbot) -> None:
    for _ in range(4):
        qtbot.wait(5)


def _bottom_row(root):
    children = root.childItems()
    assert len(children) == 1, "the island root holds exactly the column layout"
    row = children[0].childItems()[-1]
    assert row.property("spacing") == ROW_GAP_PX
    return row


def test_dialog_minimum_covers_the_worst_case_action_row(qtbot):
    """The F1 regression pinned offscreen: the 480-step dialog opened narrower
    than its own Lucide row measured, so «Открыть» was cut by the window edge.
    The row's implicit width is the layout's own worst case — the five gaps
    and the per-item pixel rounding included (the stretchy filler contributes
    nothing to it) — and the minimum (python floor) and the island ask must
    each cover it plus the two column insets, on the ui-layout-grid step."""
    dialog = GameLauncherDialog(theme=get_default_theme())
    qtbot.addWidget(dialog)

    row = _bottom_row(dialog._root)
    needed = ceil_to_width_step(row.implicitWidth() + 2 * CONTENT_INSET_PX)

    assert needed > 480, "the Lucide row outgrew the old 480 step"
    assert dialog.minimumWidth() >= needed, (dialog.minimumWidth(), needed)
    assert dialog._root.implicitWidth() >= needed


def test_open_button_ends_inside_the_island_at_the_minimum(qtbot):
    """The offscreen gate of the audit recommendation: at exactly the window
    minimum the rightmost control of the row keeps its own implicit width and
    its right edge ends no further than the island minus the content inset."""
    dialog = GameLauncherDialog(theme=get_default_theme())
    qtbot.addWidget(dialog)
    dialog.resize(dialog.minimumWidth(), dialog.minimumHeight())
    dialog.show()
    _pump(qtbot)
    assert int(dialog.width()) == int(dialog.minimumWidth())

    root = dialog._root
    opener = find_item(dialog.quick, "openButton")
    assert opener.width() >= opener.implicitWidth() - 1
    right_edge = opener.mapToScene(QPointF(opener.width(), 0)).x()
    assert right_edge <= root.width() - CONTENT_INSET_PX + 1, right_edge
