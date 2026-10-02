"""The live table cluster's widget-side contract (NRI-0024 task 5.2).

Design Д3 / spec character-sheet-host «Управление столом живо в шапке
главного окна». Offscreen, without the full Application: the anchor is a
plain top-level with a row of its own standing in for the search bar; the
service stand-in is the desk panel's FakeHost (its occupancy journal already
mirrors the real service's pushes). What is pinned here:

* the parentless ``Qt.Tool`` contract (Д3: the only legal way to stay
  clickable under a sheet's WindowModal — a child would freeze);
* «показ только при поднятом столе»: hidden at construction, raised by the
  start-side sync, gone on the stop push — and minimized hides, restore
  returns (design Д3's desync risk);
* the frame: right-top corner of the anchor row's right edge, re-read on the
  window's Move/Resize/WindowStateChange (space.sm inset, both the fallback
  and the number tokens.json carries);
* the caption count rides the occupancy pushes (join/leave repaint it);
* the accessibility contract, islands' convention with widget means: штатной
  text buttons (role Button, Press action, text-derived name — unlike the QML
  islands, offscreen widget buttons DO surface their name), the description
  slot only on the desk caption («Открывает пульт стола»), the stop button
  unannotated.
"""
from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from app.presentation.views.table_host.cluster import (
    _EDGE_INSET_FALLBACK_PX,
    DESK_DESCRIPTION,
    TableCluster,
    cluster_caption,
)
from tests.ui.test_table_host_panel_close import FakeHost

# space.sm as integer px — tokens.json carries exactly this number, so the
# themed (e2e) and off-skin (here) clusters pin the same frame.
_INSET = _EDGE_INSET_FALLBACK_PX


def _anchor(qtbot) -> tuple[QWidget, QWidget]:
    """A shown top-level with one fixed-height row — MainWindow + search row."""
    window = QWidget()
    layout = QVBoxLayout(window)
    layout.setContentsMargins(4, 4, 4, 4)
    row = QWidget()
    row.setFixedHeight(30)
    layout.addWidget(row)
    layout.addStretch(1)
    window.resize(600, 400)
    qtbot.addWidget(window)
    window.show()
    QApplication.processEvents()  # the layout settles before the first pin
    return window, row


def _cluster(
    qtbot, host: FakeHost
) -> tuple[QWidget, QWidget, TableCluster]:
    window, row = _anchor(qtbot)
    cluster = TableCluster(host, row)  # theme=None: the off-skin fallback skin
    return window, row, cluster


def _pin(cluster: TableCluster, row: QWidget) -> None:
    """The cluster's frame sits at the row's right edge, date-chip band."""
    top_right = row.mapToGlobal(QPoint(row.width(), 0))
    assert cluster.x() + cluster.width() == top_right.x() - _INSET
    assert cluster.y() == top_right.y() + _INSET


def _push(host: FakeHost) -> None:
    """The service's occupancy notify, exactly as join/leave fire it."""
    for callback in list(host.subscribers):
        callback()


def _press(widget: QWidget) -> None:
    iface = QAccessible.queryAccessibleInterface(widget)
    assert iface is not None, "the cluster control is absent from the tree"
    assert iface.role() == QAccessible.Role.Button
    actions = iface.actionInterface()
    assert actions is not None, "the cluster control carries no action interface"
    assert "Press" in actions.actionNames()
    actions.doAction("Press")


# ── the parentless Tool contract (design Д3) ────────────────────────────────

def test_cluster_is_a_parentless_stay_on_top_tool_band(qtbot):
    host = FakeHost()
    window, row, cluster = _cluster(qtbot, host)
    assert cluster.parent() is None
    flags = cluster.windowFlags()
    assert flags & Qt.WindowType.Tool
    assert flags & Qt.WindowType.FramelessWindowHint
    assert flags & Qt.WindowType.WindowStaysOnTopHint
    assert cluster.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    # The click channels are the cluster's whole outward contract; the
    # composition root decides what a desk click and a stop mean (main.py).
    assert cluster.desk_label.text() == cluster_caption(0)
    assert cluster.stop_button.text() == "Остановить стол"


# ── «показ только при поднятом столе» (spec) ────────────────────────────────

def test_cluster_shows_only_while_the_table_is_up(qtbot):
    host = FakeHost()
    window, row, cluster = _cluster(qtbot, host)
    # built over a stopped service → hidden from the first sync (no flash)
    assert cluster.isHidden() is True

    host.start_fake()
    cluster.sync_running()  # the start-side sync main.py performs
    assert cluster.isVisible()
    _pin(cluster, row)

    host.stop_fake()  # the real stop() fires an occupancy push — as here
    assert cluster.isHidden() is True
    # a stray repaint after the stop never brings the shadow back
    cluster.sync_running()
    assert cluster.isHidden() is True


def test_caption_count_rides_the_occupancy_pushes(qtbot):
    host = FakeHost()
    host.start_fake()
    window, row, cluster = _cluster(qtbot, host)  # __init__ sync → shown
    assert cluster.isVisible()
    assert cluster.desk_label.text() == "Стол · 0 игроков"

    host.players_list = [(1, "Вася")]
    _push(host)
    assert cluster.desk_label.text() == "Стол · 1 игроков"

    host.players_list = [(1, "Вася"), (2, "Петя")]
    _push(host)
    assert cluster.desk_label.text() == "Стол · 2 игроков"

    host.players_list = [(2, "Петя")]  # one player left — the table stays up
    _push(host)
    assert cluster.desk_label.text() == "Стол · 1 игроков"
    assert cluster.isVisible()
    host.stop_fake()


# ── the frame follows the anchor window (move/resize/minimize) ──────────────

def test_frame_follows_the_window_through_move_and_resize(qtbot):
    host = FakeHost()
    host.start_fake()
    window, row, cluster = _cluster(qtbot, host)
    _pin(cluster, row)

    window.move(310, 140)
    QApplication.processEvents()  # the Move event re-reads the row rectangle
    _pin(cluster, row)

    window.resize(800, 600)  # the row stretches with the window — the pin too
    QApplication.processEvents()
    _pin(cluster, row)

    host.stop_fake()


def test_minimize_hides_the_shadow_restore_brings_it_back(qtbot):
    host = FakeHost()
    host.start_fake()
    window, row, cluster = _cluster(qtbot, host)
    assert cluster.isVisible()

    window.showMinimized()  # the anchor row is off screen → hide the band
    QApplication.processEvents()  # (WindowStateChange)
    assert cluster.isHidden() is True

    window.showNormal()  # the table is still up → the band returns, pinned
    QApplication.processEvents()  # (WindowStateChange)
    assert cluster.isHidden() is False
    assert cluster.isVisible()
    _pin(cluster, row)

    # a raise attempted while the window sleeps stays hidden (sync_running's
    # minimized guard — no floating band over the desktop)
    window.showMinimized()
    QApplication.processEvents()
    cluster.sync_running()
    assert cluster.isHidden() is True
    window.showNormal()
    QApplication.processEvents()
    host.stop_fake()


def test_closing_the_anchor_window_takes_the_cluster_down(qtbot):
    host = FakeHost()
    host.start_fake()
    window, row, cluster = _cluster(qtbot, host)
    assert cluster.isVisible()

    window.close()  # game switch / exit route — the shadow never outlives it
    assert cluster.isHidden() is True
    host.stop_fake()
    # The deleteLater this route queued must land NOW: the C++ side dies with
    # the window's teardown, not several tests later.
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


# ── the accessibility contract (islands' convention, widget means) ──────────

def test_both_controls_are_pressable_buttons_named_by_their_captions(qtbot):
    host = FakeHost()
    host.start_fake()
    window, row, cluster = _cluster(qtbot, host)

    stop_iface = QAccessible.queryAccessibleInterface(cluster.stop_button)
    desk_iface = QAccessible.queryAccessibleInterface(cluster.desk_label)
    assert stop_iface is not None and desk_iface is not None
    assert stop_iface.role() == QAccessible.Role.Button
    assert desk_iface.role() == QAccessible.Role.Button
    # names — штатно, derived from the visible captions (never re-annotated;
    # unlike the QML islands, offscreen widget buttons DO surface the name)
    assert stop_iface.text(QAccessible.Name) == "Остановить стол"
    assert desk_iface.text(QAccessible.Name) == cluster_caption(0)
    # the description slot carries the hidden meaning of the desk activation
    # and sits on the desk caption ONLY — the stop's name already says it all
    assert desk_iface.text(QAccessible.Description) == DESK_DESCRIPTION
    assert stop_iface.text(QAccessible.Description) == ""


def test_ax_press_actuates_the_same_channels_as_the_mouse(qtbot):
    host = FakeHost()
    host.start_fake()
    window, row, cluster = _cluster(qtbot, host)
    desks: list[int] = []
    stops: list[int] = []
    cluster.desk_requested.connect(lambda: desks.append(1))
    cluster.stop_requested.connect(lambda: stops.append(1))

    _press(cluster.desk_label)
    # QAccessibleButton's Press releases through animateClick's timer — the
    # seats-accessibility pattern: the wait pumps the Qt loop for the release.
    qtbot.waitUntil(lambda: desks == [1], timeout=3000)
    _press(cluster.stop_button)
    qtbot.waitUntil(lambda: stops == [1], timeout=3000)

    # neither Press stopped the table or moved the cluster itself — the tree
    # only emits; the composition root owns the consequences
    assert host.running is True
    assert cluster.isVisible()
    host.stop_fake()


def test_desk_caption_click_emits_the_desk_request(qtbot):
    host = FakeHost()
    host.start_fake()
    window, row, cluster = _cluster(qtbot, host)
    desks: list[int] = []
    cluster.desk_requested.connect(lambda: desks.append(1))

    cluster.desk_label.click()

    assert desks == [1]
    host.stop_fake()


def test_stop_button_click_emits_the_stop_request(qtbot):
    host = FakeHost()
    host.start_fake()
    window, row, cluster = _cluster(qtbot, host)
    stops: list[int] = []
    cluster.stop_requested.connect(lambda: stops.append(1))

    cluster.stop_button.click()

    assert stops == [1]
    host.stop_fake()
