"""The live cluster on the real wiring (NRI-0024 task 5.2).

Offscreen-pinned slice of the «Управление столом живо в шапке главного окна»
spec on the real composition (app fixture): the cluster the game builds over
its own window and search row. The desk-caption Press path is the design Д3
bet made observable: the cluster is a top-level (Qt.Tool), so a sheet's
WindowModal — which freezes every child of the main window — never reaches
it; clicking its caption re-enters ``open_sheet`` and the desk rises over
the ACTIVE sheet, which itself stays open (spec «Глянуть пульт из-под
листа»). «Остановить стол» in the band rides the very locked stop the desk
button uses and takes the cluster down with the service (spec «Стоп из
шапки»); the sheet stack is left untouched by the stop.

The socket is not the subject here — the service runs with its HTTP unset,
like the desk-wiring suite does.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import QApplication, QCheckBox

from app.presentation.views.table_host.cluster import (
    DESK_DESCRIPTION,
    TableCluster,
    cluster_caption,
)

# space.sm — the tokens.json number the themed cluster pins its frame by.
_INSET = 8


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


def _pin(cluster: TableCluster, bar) -> None:
    """The cluster's frame sits at the search row's right edge, date-chip band."""
    top_right = bar.mapToGlobal(QPoint(bar.width(), 0))
    assert cluster.x() + cluster.width() == top_right.x() - _INSET
    assert cluster.y() == top_right.y() + _INSET


async def test_cluster_shadows_the_real_search_row(app, wait_for):
    application, window = app
    cluster = application._table_cluster
    # The parentless Qt.Tool contract (design Д3) on the real themed build
    assert isinstance(cluster, TableCluster)
    assert cluster.parent() is None
    flags = cluster.windowFlags()
    assert flags & Qt.WindowType.Tool
    assert flags & Qt.WindowType.FramelessWindowHint
    assert flags & Qt.WindowType.WindowStaysOnTopHint
    assert cluster.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    # «показ только при поднятом столе»: built over a stopped table — hidden
    assert cluster.isHidden() is True

    await _start_table(application, window, wait_for)
    # the start-side sync in _start_table raises it (start never pushes)
    assert cluster.isVisible()
    assert cluster.desk_label.text() == cluster_caption(0)
    _pin(cluster, window.search_bar)

    # the band follows the window: move re-reads the row's global rectangle
    window.move(300, 220)
    QApplication.processEvents()
    _pin(cluster, window.search_bar)

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
    assert cluster.isHidden() is True


async def test_desk_caption_opens_the_desk_over_the_active_sheet(app, wait_for):
    application, window = app
    await _start_table(application, window, wait_for)
    panel = application._table_host_panel
    cluster = application._table_cluster
    assert cluster.isVisible()

    # the desk sheet may close — the table stays up, the band outlives its close
    panel.close()
    assert cluster.isVisible()

    # an active sheet of a different content: «Обзор мира»
    window.world_snapshot_action.trigger()
    snapshot_sheet = application._wiring.snapshot_sheet
    assert snapshot_sheet is not None and snapshot_sheet.isVisible()

    # the caption click over the scrim — the cluster is outside the modal
    # layer (Д3), the sheet modality freezes main-window children only
    cluster.desk_label.click()
    await wait_for(lambda: panel.isVisible())
    # the active sheet stays open; the desk rose over it as a stack member
    assert snapshot_sheet.isVisible()
    assert panel.parentWidget() is window
    stack = application._wiring._open_sheets
    assert stack[-2] is snapshot_sheet
    assert stack[-1] is panel

    # «Стоп из шапки»: the band's button is the same stop, sheets untouched
    cluster.stop_button.click()
    await wait_for(lambda: application._table_host.is_running is False)
    assert cluster.isHidden() is True
    assert snapshot_sheet.isVisible()
    assert panel.isVisible()  # stopping never closes an opened desk (Д5)
    # the stack was not touched by the stop either
    assert application._wiring._open_sheets == [snapshot_sheet, panel]
