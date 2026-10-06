"""The docked table cluster's widget-side contract (was NRI-0024 task 5.2;
the owner ruling 2026-10-05 re-docked the floating band into the window).

Offscreen, without the full Application: the parent is a plain top-level with
a central-column layout (search-row stand-in on top, a stretch-less
«columns» label below) standing in for MainWindow's content column; the desk
placement itself is pinned on the real MainWindow with mock view models —
the very route the composition root takes (``attach_table_cluster``). The
service stand-in is the desk panel's FakeHost (its occupancy journal already
mirrors the real service's pushes). What is pinned here:

* the child posture: a plain child panel — no Tool, no frameless chrome, no
  stays-on-top, no show-without-activating (the floating band of design Д3
  is retired; under a sheet the panel rides the window's own content block);
* «показ только при поднятом столе»: hidden at construction, raised by the
  start-side sync, gone on the stop push — and a stopped table reserves no
  strip: the hidden panel collapses its row including the adjacent spacing;
* the frame: the leading stretch keeps the controls at the row's right end
  with the space.sm inset (the fallback here, the token number in the live
  suite); the vertical size policy is Fixed and the attach inserts with
  stretch 0, so a window resize stretches the splitter, never the band;
* the caption count rides the occupancy pushes (join/leave repaint it);
* the accessibility contract, islands' convention with widget means: штатной
  text buttons (role Button, Press action, text-derived name — unlike the QML
  islands, offscreen widget buttons DO surface their name), the description
  slot only on the desk caption («Открывает пульт стола»), the stop button
  unannotated.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from PySide6.QtCore import Qt
from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import (
    QApplication, QLabel, QSizePolicy, QSplitter, QVBoxLayout, QWidget,
)

from app.presentation.views.main_window import MainWindow
from app.presentation.views.table_host.cluster import (
    _EDGE_INSET_FALLBACK_PX,
    DESK_DESCRIPTION,
    TableCluster,
    cluster_caption,
)
from tests.ui.test_table_host_panel_close import FakeHost

# space.sm as integer px — tokens.json carries exactly this number, so the
# themed (e2e) and off-skin (here) clusters pin the same inset.
_INSET = _EDGE_INSET_FALLBACK_PX

# the central column's margins/spacing — both the stand-in and MainWindow
# copy these numbers (main_window.py: setContentsMargins(4,4,4,4)/setSpacing(4))
_MARGIN = 4
_SPACING = 4


def _host(started: bool = False) -> FakeHost:
    host = FakeHost()
    if started:
        host.start_fake()
    return host


def _parent(qtbot) -> QWidget:
    """A shown top-level with a content column: search row, free slot 1 for
    the cluster, a stretch-less «columns» label that absorbs the surplus."""
    window = QWidget()
    layout = QVBoxLayout(window)
    layout.setContentsMargins(_MARGIN, _MARGIN, _MARGIN, _MARGIN)
    layout.setSpacing(_SPACING)
    search_row = QLabel("строка поиска", window)
    search_row.setObjectName("search_row")
    search_row.setFixedHeight(30)
    layout.addWidget(search_row)
    columns = QLabel("колонки", window)
    columns.setObjectName("columns")
    layout.addWidget(columns)
    window.resize(600, 400)
    qtbot.addWidget(window)
    window.show()
    QApplication.processEvents()  # the layout settles before the first pin
    return window


def _cluster(qtbot, host: FakeHost) -> tuple[QWidget, TableCluster]:
    """The docked posture off the real attach path: child + slot under the row."""
    window = _parent(qtbot)
    cluster = TableCluster(host, window)  # theme=None: the off-skin fallback skin
    window.layout().insertWidget(1, cluster)
    QApplication.processEvents()
    return window, cluster


def _columns(window: QWidget) -> QLabel:
    return window.findChild(QLabel, "columns")


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


# ── the child posture (the floating Tool band is retired) ───────────────────

def test_cluster_is_a_plain_child_panel(qtbot):
    window, cluster = _cluster(qtbot, _host())
    assert cluster.parent() is window
    assert cluster.isWindow() is False
    flags = cluster.windowFlags()
    assert not flags & Qt.WindowType.Tool
    assert not flags & Qt.WindowType.FramelessWindowHint
    assert not flags & Qt.WindowType.WindowStaysOnTopHint
    assert cluster.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating) is False
    # fixed height: sizeHint is the only height the layout may give the band
    assert cluster.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Fixed
    # The click channels are the cluster's whole outward contract; the
    # composition root decides what a desk click and a stop mean (main.py).
    assert cluster.desk_label.text() == cluster_caption(0)
    assert cluster.stop_button.text() == "Остановить стол"


# ── «показ только при поднятом столе», the band reserves nothing at rest ────

def test_band_shows_only_while_the_table_is_up_and_reserves_nothing_otherwise(qtbot):
    host = _host()
    window, cluster = _cluster(qtbot, host)
    search_row = window.findChild(QLabel, "search_row")
    columns = _columns(window)
    # built over a stopped service → hidden from the first sync (no flash),
    # and the hidden panel eats its row AND the adjacent spacing
    assert cluster.isHidden() is True
    assert columns.y() == search_row.y() + search_row.height() + _SPACING

    host.start_fake()
    cluster.sync_running()  # the start-side sync main.py performs
    QApplication.processEvents()
    assert cluster.isVisible()
    # the band appears between the row and the columns, pushing them down
    assert columns.y() == (
        search_row.y() + search_row.height() + _SPACING
        + cluster.height() + _SPACING
    )

    host.stop_fake()  # the real stop() fires an occupancy push — as here
    QApplication.processEvents()
    assert cluster.isHidden() is True
    assert columns.y() == search_row.y() + search_row.height() + _SPACING
    # a stray repaint after the stop never brings the band back
    cluster.sync_running()
    assert cluster.isHidden() is True


def test_fixed_height_survives_the_window_resize(qtbot):
    window, cluster = _cluster(qtbot, _host(started=True))
    assert cluster.isVisible()
    columns = _columns(window)
    height0 = cluster.height()
    columns_top0 = columns.y()
    columns_height0 = columns.height()

    window.resize(600, 800)
    QApplication.processEvents()
    # the band keeps its sizeHint height; the stretch-less sibling absorbs
    assert cluster.height() == height0 == cluster.sizeHint().height()
    assert columns.y() == columns_top0
    assert columns.height() > columns_height0


def test_controls_hug_the_right_edge_with_the_token_inset(qtbot):
    window, cluster = _cluster(qtbot, _host(started=True))
    margins = cluster.layout().contentsMargins()
    assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (
        _INSET, 2, _INSET, 2,
    )
    # the row spans the content width, the controls sit at its right end
    assert cluster.x() == _MARGIN
    assert cluster.x() + cluster.width() == window.width() - _MARGIN
    assert (
        cluster.stop_button.x() + cluster.stop_button.width()
        == cluster.width() - _INSET
    )
    # the leading stretch leaves the buttons at their natural widths
    assert cluster.stop_button.width() == cluster.stop_button.sizeHint().width()
    assert cluster.desk_label.x() + cluster.desk_label.width() <= cluster.stop_button.x()


# ── the real attach route: the row lives under the search bar, stretch 0 ────

def test_attach_places_the_cluster_between_search_row_and_splitter(qtbot):
    window = MainWindow(
        timeline_vm=MagicMock(), detail_vm=MagicMock(), search_vm=MagicMock(),
    )
    qtbot.addWidget(window)
    host = _host()
    cluster = TableCluster(host, window)
    window.attach_table_cluster(cluster)
    central = window.centralWidget()
    layout = central.layout()
    splitter = window.findChild(QSplitter)
    assert cluster.parent() is central  # the layout took over the parenting
    assert layout.indexOf(cluster) == layout.indexOf(window.search_bar) + 1
    assert layout.indexOf(cluster) < layout.indexOf(splitter)
    assert layout.stretch(layout.indexOf(cluster)) == 0

    window.resize(1024, 680)
    window.show()
    QApplication.processEvents()
    search_bar = window.search_bar
    # stopped table: hidden, the splitter sits directly under the search bar
    assert cluster.isHidden() is True
    assert splitter.y() == search_bar.y() + search_bar.height() + _SPACING

    host.start_fake()
    cluster.sync_running()  # the start-side sync main.py performs
    QApplication.processEvents()
    assert cluster.isVisible()
    # the band cost the columns exactly its height plus the one spacing
    assert splitter.y() == (
        search_bar.y() + search_bar.height() + _SPACING
        + cluster.height() + _SPACING
    )
    # a taller window stretches the splitter, never the band (stretch 0)
    splitter_height0 = splitter.height()
    band_height0 = cluster.height()
    window.resize(1024, 900)
    QApplication.processEvents()
    assert cluster.height() == band_height0
    assert splitter.height() > splitter_height0
    # right-aligned in the same band as the search row's right edge
    assert cluster.geometry().right() == search_bar.geometry().right()


# ── the caption count rides the occupancy pushes ────────────────────────────

def test_caption_count_rides_the_occupancy_pushes(qtbot):
    host = _host(started=True)
    window, cluster = _cluster(qtbot, host)  # __init__ sync → shown
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


# ── the accessibility contract (islands' convention, widget means) ──────────

def test_both_controls_are_pressable_buttons_named_by_their_captions(qtbot):
    window, cluster = _cluster(qtbot, _host(started=True))

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
    host = _host(started=True)
    window, cluster = _cluster(qtbot, host)
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

    # neither Press stopped the table or moved the panel itself — the tree
    # only emits; the composition root owns the consequences
    assert host.running is True
    assert cluster.isVisible()
    host.stop_fake()


def test_desk_caption_click_emits_the_desk_request(qtbot):
    host = _host(started=True)
    window, cluster = _cluster(qtbot, host)
    desks: list[int] = []
    cluster.desk_requested.connect(lambda: desks.append(1))

    cluster.desk_label.click()

    assert desks == [1]
    host.stop_fake()


def test_stop_button_click_emits_the_stop_request(qtbot):
    host = _host(started=True)
    window, cluster = _cluster(qtbot, host)
    stops: list[int] = []
    cluster.stop_requested.connect(lambda: stops.append(1))

    cluster.stop_button.click()

    assert stops == [1]
    host.stop_fake()
