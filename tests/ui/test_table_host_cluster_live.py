"""The docked cluster on the real wiring (was NRI-0024 task 5.2; the owner
ruling 2026-10-05 re-docked the floating band into the window).

Offscreen-pinned slice of the «Управление столом живо в шапке главного окна»
family on the real composition (app fixture): the cluster the game builds as
a CHILD row of its own window — under the search bar, right-aligned, visible
only while the table is up. The deliberate loss of the re-dock (accepted by
the owner; the spec is retouched by the next change) is pinned exactly: with
a sheet open the panel stays VISIBLE, but SPONTANEOUS pointer input aimed at
it dies in the window's stack gate — the sheet block covers the whole content
layer, this panel included. Without a sheet up both controls ride the real
spontaneous mouse route: «Остановить стол» is the very locked stop the desk
button uses and takes the panel down with the service («Стоп из шапки»), the
desk caption re-enters ``open_sheet`` with the live desk. The themed build
also covers the token half of the insets (space.sm from tokens.json).

The socket is not the subject here — the service runs with its HTTP unset,
like the desk-wiring suite does.
"""
from __future__ import annotations

import asyncio

from PySide6.QtCore import Qt
from PySide6.QtGui import QAccessible
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QSplitter

from app.presentation.views.table_host.cluster import (
    DESK_DESCRIPTION,
    TableCluster,
    cluster_caption,
)

# space.sm — the tokens.json number the themed cluster insets itself by.
_INSET = 8
# central column's margins/spacing, copied from main_window.py
_MARGIN = 4
_SPACING = 4


async def _start_table(application, window, wait_for) -> None:
    """Raise the real table on the desk (no socket: the cluster is the subject)."""
    application._table_host.set_http(None)
    window.table_host_action.trigger()
    await wait_for(lambda: application._table_host_panel is not None)
    panel = application._table_host_panel
    panel.set_instances([(1, "Лист")])
    panel.seat_boxes()[0].setChecked(True)
    await application._start_table()
    assert application._table_host.is_running


async def _pump(qtbot, rounds: int = 25) -> None:
    """A fixed-budget copy of the wait_for pump: if a blocked click had
    fired, its locked stop would have reached the service by now — the
    negative assertion below then reads as evidence, not an un-pumped turn."""
    for _ in range(rounds):
        await asyncio.sleep(0)
        qtbot.wait(1)


async def test_cluster_is_a_docked_row_under_the_search_bar(app, qtbot, wait_for):
    application, window = app
    cluster = application._table_cluster
    central = window.centralWidget()
    # the child posture on the real themed build (was the parentless Qt.Tool)
    assert isinstance(cluster, TableCluster)
    assert cluster.parent() is central
    flags = cluster.windowFlags()
    assert not flags & Qt.WindowType.Tool
    assert not flags & Qt.WindowType.FramelessWindowHint
    assert not flags & Qt.WindowType.WindowStaysOnTopHint
    assert cluster.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating) is False
    layout = central.layout()
    assert layout.indexOf(cluster) == layout.indexOf(window.search_bar) + 1
    assert layout.stretch(layout.indexOf(cluster)) == 0
    splitter = window.findChild(QSplitter)
    search_bar = window.search_bar
    # «показ только при поднятом столе»: built over a stopped table — hidden,
    # and the hidden row reserves neither height nor spacing
    assert cluster.isHidden() is True
    assert splitter.y() == search_bar.y() + search_bar.height() + _SPACING

    await _start_table(application, window, wait_for)
    QApplication.processEvents()  # the band's show re-activates the column layout
    # the start-side sync in _start_table raises it (start never pushes)
    assert cluster.isVisible()
    assert cluster.desk_label.text() == cluster_caption(0)
    # right-aligned in its row, token-inset, in the same band as the row's edge
    assert cluster.x() == _MARGIN
    assert cluster.x() + cluster.width() == central.width() - _MARGIN
    assert cluster.geometry().right() == search_bar.geometry().right()
    assert cluster.layout().contentsMargins().right() == _INSET
    assert (
        cluster.stop_button.x() + cluster.stop_button.width()
        == cluster.width() - _INSET
    )
    # the band cost the columns exactly its height plus the one spacing
    assert splitter.y() == (
        search_bar.y() + search_bar.height() + _SPACING
        + cluster.height() + _SPACING
    )
    # fixed height: a taller window stretches the splitter, never the panel
    band_height0 = cluster.height()
    splitter_height0 = splitter.height()
    window.resize(1280, 950)
    QApplication.processEvents()
    assert cluster.height() == band_height0 == cluster.sizeHint().height()
    assert splitter.height() > splitter_height0

    # accessibility (islands' convention, widget means): штатной text buttons,
    # role Button, names from the captions, the description slot on the desk
    stop_iface = QAccessible.queryAccessibleInterface(cluster.stop_button)
    desk_iface = QAccessible.queryAccessibleInterface(cluster.desk_label)
    assert stop_iface.role() == QAccessible.Role.Button
    assert desk_iface.role() == QAccessible.Role.Button
    assert stop_iface.text(QAccessible.Name) == "Остановить стол"
    assert desk_iface.text(QAccessible.Name) == cluster_caption(0)
    assert desk_iface.text(QAccessible.Description) == DESK_DESCRIPTION
    assert stop_iface.text(QAccessible.Description) == ""

    await application._stop_table()  # the occupancy push takes the band down
    QApplication.processEvents()  # its hide collapses the row again
    assert cluster.isHidden() is True
    assert splitter.y() == search_bar.y() + search_bar.height() + _SPACING


async def test_under_an_open_sheet_the_panel_is_visible_but_blocked(
    app, qtbot, wait_for
):
    application, window = app
    await _start_table(application, window, wait_for)
    cluster = application._table_cluster
    desk = application._table_host_panel
    # the panel is seen under the open desk sheet (it is part of the window)
    assert cluster.isVisible()
    # the real sheet stack is up: the window's content gate holds its layer
    assert window._content_gate_installed is True
    stack = list(application._wiring._open_sheets)

    # the accepted loss of the re-dock: SPONTANEOUS pointer input aimed at
    # the panel dies in the gate — no stop, no sheet re-entry, no state move
    QTest.mouseClick(cluster.stop_button, Qt.MouseButton.LeftButton)
    QTest.mouseClick(cluster.desk_label, Qt.MouseButton.LeftButton)
    await _pump(qtbot)
    assert application._table_host.is_running is True
    assert cluster.isVisible()
    assert application._wiring._open_sheets == stack
    assert desk.isVisible()


async def test_stop_from_the_header_without_a_sheet_stops_the_table(
    app, qtbot, wait_for
):
    application, window = app
    await _start_table(application, window, wait_for)
    cluster = application._table_cluster
    desk = application._table_host_panel

    # the desk sheet may close — the table stays up, the panel outlives its close
    desk.close()
    await wait_for(lambda: application._wiring._open_sheets == [])
    assert cluster.isVisible()
    assert window._content_gate_installed is False

    # with no sheet up the real spontaneous mouse route reaches the panel:
    # «Стоп из шапки» is the very locked stop the desk button uses
    QTest.mouseClick(cluster.stop_button, Qt.MouseButton.LeftButton)
    await wait_for(lambda: application._table_host.is_running is False)
    assert cluster.isHidden() is True


async def test_desk_caption_reopens_the_desk_when_no_sheet_is_up(
    app, qtbot, wait_for
):
    application, window = app
    await _start_table(application, window, wait_for)
    cluster = application._table_cluster
    desk = application._table_host_panel
    desk.close()
    await wait_for(lambda: application._wiring._open_sheets == [])
    assert cluster.isVisible()

    # the caption click re-enters the connector's one open_sheet path with
    # the LIVE desk (re-entry shows the same panel, never a second copy)
    QTest.mouseClick(cluster.desk_label, Qt.MouseButton.LeftButton)
    await wait_for(lambda: desk.isVisible())
    assert application._wiring._open_sheets == [desk]
    assert application._table_host.is_running is True
