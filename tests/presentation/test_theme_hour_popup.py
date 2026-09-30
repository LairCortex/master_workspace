"""Offscreen contract of the hour-list bridge window (task 12.6, A1 host half
of design Д14.1, spec current-date «Все значения часов достижимы»).

The live re-audit (docs/qa/2026-09-29-now-hour-chip-fixes.md, A1) proved the
``ThemeComboBox`` pop-up itself is full and scrollable but the fixed-height
search-island host clips any QQuickPopup to its own bottom — hours 18…23 were
neither visible nor clickable there. The fix bridges the list out of the host
exactly like the date chip of the same row: a parent-less top level whose
height no host can clip. Pinned here: the full 25-row list capped at the
Д14.1 eight visible rows, the highlighted current row scrolled into view at
open, wheel to the end + the mouse clicking exactly the last hour, Enter on
an arrowed-to row, the index the pick carries back, the content-column width
contract (2026-09-30: never the anchor width, the window hugs the list), the
geometry clamp — and the popup-sheet pair guards of the new
style-facing class names (the GameCalendarEraCheck recipe).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import app.presentation.views.theme_hour_popup as hour_popup_module
from app.presentation.theme.compiler import compile_popup_qss, load_tokens, tokens_file_path
from app.presentation.views import theme_hour_popup as hour_popup_source_module
from app.presentation.views.theme_hour_popup import (
    MAX_VISIBLE_ROWS,
    ROW_BAND,
    ROW_SIDE,
    WIDTH_BAND,
    ThemeHourListView,
    ThemeHourPopup,
)

#: The shape the NowDateViewModel serves for the default 24-hour day.
OPTIONS = ["—"] + [str(h) for h in range(24)]


@pytest.fixture
def tokens():
    parsed = load_tokens(tokens_file_path())
    assert parsed is not None
    return parsed


def _row_texts(popup: ThemeHourPopup) -> list[str]:
    return [popup.list.item(i).text() for i in range(popup.list.count())]


def _row_center_in_viewport(popup: ThemeHourPopup, index: int) -> QPoint | None:
    """The centre of row ``index`` in viewport coordinates, or None when the
    row currently lives outside the viewport (below/above the eight rows)."""
    rect = popup.list.visualItemRect(popup.list.item(index))
    if not popup.list.viewport().rect().contains(rect.center()):
        return None
    return rect.center()


def _wheel_down(popup: ThemeHourPopup) -> None:
    """One real wheel notch over the list viewport, delivered to the widget."""
    event = QWheelEvent(
        QPointF(10, 10), popup.mapToGlobal(QPoint(10, 10)),
        QPoint(0, 0), QPoint(0, -120),
        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False,
    )
    QApplication.sendEvent(popup.list.viewport(), event)
    QTest.qWait(10)


# ── the window: a top level the host cannot clip ─────────────────────────────


def test_popup_is_a_parent_less_top_level(qtbot):
    popup = ThemeHourPopup()
    qtbot.addWidget(popup)
    # The A1 root: a widget inside the island can be cut by the island; this
    # window is not — parent-less like every widgets-bridge popup here.
    assert popup.parent() is None
    assert popup.windowFlags() & Qt.WindowType.Popup
    assert isinstance(popup.list, ThemeHourListView)


def test_open_lists_every_hour_capped_at_eight_visible_rows(qtbot):
    popup = ThemeHourPopup()
    qtbot.addWidget(popup)
    popup.open_at(QRect(20, 30, 70, 24), OPTIONS, 0)
    try:
        assert _row_texts(popup) == OPTIONS  # «—» + 0…23, nothing realized-short
        row_height = popup.list.fontMetrics().height() + 2 * ROW_BAND
        assert popup.list.height() == MAX_VISIBLE_ROWS * row_height
        # The list overflow scrolls inside the window: the last row exists
        # outside the viewport until the wheel brings it up (the A1 trap was
        # it never existing visibly at all).
        assert _row_center_in_viewport(popup, 24) is None
        assert popup.height() > MAX_VISIBLE_ROWS * row_height // 2
    finally:
        popup.close()


def test_open_highlights_the_current_row_and_scrolls_it_into_view(qtbot):
    """A2's rule for the bridge window: opening with hour 23 shows the
    highlighted row without any manual scrolling."""
    popup = ThemeHourPopup()
    qtbot.addWidget(popup)
    popup.open_at(QRect(20, 30, 70, 24), OPTIONS, 24)
    try:
        assert popup.list.currentRow() == 24
        item = popup.list.item(24)
        assert bool(item.isSelected()) is True
        rect = popup.list.visualItemRect(item)
        viewport = popup.list.viewport().rect()
        assert viewport.top() <= rect.center().y() <= viewport.bottom()
    finally:
        popup.close()


def test_open_clamps_an_unhostable_current_index(qtbot):
    """A narrowed day (design Д5): a stale index highlights the closest row,
    never crashes and never leaves nothing selected."""
    popup = ThemeHourPopup()
    qtbot.addWidget(popup)
    popup.open_at(QRect(20, 30, 70, 24), ["—", "0", "1", "2"], 99)
    assert popup.list.currentRow() == 3
    popup.open_at(QRect(20, 30, 70, 24), ["—", "0", "1", "2"], -5)
    assert popup.list.currentRow() == 0
    popup.close()


def test_width_is_the_content_column_never_the_anchor(qtbot):
    """User report 2026-09-30: the window painted host-wide with the rows a
    narrow column — an enormous empty band right of the scrollbar. The bridge
    width is the CONTENT worst-case (widest row + insets + the overflow
    scrollbar + the A11 rounding band), the anchor width is not a floor, and
    the window hugs the list: min == max via SetFixedSize, so no inflate step
    can widen it again (adjustSize leaves a scroll-area top level at 200 px
    around a fixed 70 px list on this Qt)."""
    popup = ThemeHourPopup()
    qtbot.addWidget(popup)
    fm = popup.list.fontMetrics()
    widest = max(fm.horizontalAdvance(text) for text in OPTIONS)
    scrollbar = popup.list.verticalScrollBar().sizeHint().width()
    content = widest + 2 * ROW_SIDE + WIDTH_BAND + scrollbar

    popup.open_at(QRect(20, 30, 400, 24), OPTIONS, 0)
    assert popup.list.width() == content  # a wide host grows nothing
    assert popup.width() == content + 2  # one pixel of window frame each side
    assert popup.sizeHint().width() == popup.width()  # no inflation left
    popup.close()

    popup.open_at(QRect(20, 30, 10, 24), OPTIONS, 0)
    assert popup.list.width() == content  # a narrow host shrinks nothing
    popup.close()


def test_short_list_width_keeps_no_scrollbar_allowance(qtbot):
    """The scrollbar allowance belongs to the overflow only: ≤ 8 rows never
    pay for a bar that will not paint."""
    popup = ThemeHourPopup()
    qtbot.addWidget(popup)
    options = ["—", "0", "1", "2", "3"]
    fm = popup.list.fontMetrics()
    widest = max(fm.horizontalAdvance(text) for text in options)
    popup.open_at(QRect(20, 30, 400, 24), options, 0)
    assert popup.list.width() == widest + 2 * ROW_SIDE + WIDTH_BAND
    assert popup.width() == popup.list.width() + 2
    popup.close()


# ── the reachability half — the A1 acceptance itself ─────────────────────────


def test_wheel_reaches_the_last_hour_and_the_mouse_clicks_exactly_it(qtbot):
    popup = ThemeHourPopup()
    qtbot.addWidget(popup)
    received: list = []
    popup.hour_selected.connect(received.append)
    popup.open_at(QRect(20, 30, 70, 24), OPTIONS, 0)
    qtbot.addWidget(popup)  # keeps the top level registered for teardown

    # «колесо до конца»: the real wheel through the viewport, no test-side
    # scrolling shortcuts — the rows must arrive by scrolling alone.
    deadline = 60
    center = None
    while center is None and deadline > 0:
        center = _row_center_in_viewport(popup, 24)
        if center is None:
            _wheel_down(popup)
            deadline -= 1
    assert center is not None, "row «23» never scrolled into the viewport"
    QTest.mouseClick(popup.list.viewport(), Qt.LeftButton, Qt.NoModifier, center)
    assert received == [24]  # hour 23 — index H + 1 of the VM list
    assert not popup.isVisible()  # the pick closes the window


def test_mouse_click_applies_a_visible_row_immediately(qtbot):
    popup = ThemeHourPopup()
    qtbot.addWidget(popup)
    received: list = []
    popup.hour_selected.connect(received.append)
    popup.open_at(QRect(20, 30, 70, 24), ["—", "0", "1", "2", "3"], 0)
    center = _row_center_in_viewport(popup, 3)
    QTest.mouseClick(popup.list.viewport(), Qt.LeftButton, Qt.NoModifier, center)
    assert received == [3]
    assert not popup.isVisible()


def test_enter_activates_the_arrowed_row(qtbot):
    """Keyboard half of «Все значения часов достижимы»: arrows move the
    highlight, Enter applies it (QAbstractItemView emits activated from the
    return key only by this class's own override — pinned)."""
    popup = ThemeHourPopup()
    qtbot.addWidget(popup)
    received: list = []
    popup.hour_selected.connect(received.append)
    popup.open_at(QRect(20, 30, 70, 24), OPTIONS, 0)
    popup.list.setFocus(Qt.OtherFocusReason)
    for _ in range(5):
        QTest.keyClick(popup.list.viewport(), Qt.Key.Key_Down)
    QTest.qWait(20)
    assert popup.list.currentRow() == 5
    QTest.keyClick(popup.list.viewport(), Qt.Key.Key_Return)
    assert received == [5]
    assert not popup.isVisible()


# ── placement: the ThemeDatePopup rule kept line-for-line ────────────────────


def test_open_clamps_both_axes_to_available_geometry(qtbot, monkeypatch):
    popup = ThemeHourPopup()
    qtbot.addWidget(popup)
    geometry = QRect(100, 200, 640, 480)

    class Screen:
        def availableGeometry(self):
            return QRect(geometry)

    class App:
        @staticmethod
        def screenAt(_position):
            return Screen()

        @staticmethod
        def primaryScreen():
            return Screen()

    monkeypatch.setattr(hour_popup_module, "QApplication", App)
    popup.open_at(QRect(1000, 1000, 50, 20), OPTIONS, 0)
    assert geometry.left() <= popup.x()
    assert popup.x() + popup.width() - 1 <= geometry.right()
    assert geometry.top() <= popup.y()
    assert popup.y() + popup.height() - 1 <= geometry.bottom()
    popup.close()


# ── popup-sheet pair guards (the GameCalendarEraCheck recipe) ────────────────


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_popup_sheet_themes_the_hour_list_from_tokens(tokens, theme):
    sheet = compile_popup_qss(tokens, theme)

    frame = re.search(r"ThemeHourPopup\s*\{([^}]*)\}", sheet)
    assert frame, "в листе попапов нет правила рамки окна часов"
    assert f"background: {tokens['color.bg.surface'][theme]};" in frame.group(1)
    assert f"border: 1px solid {tokens['color.border'][theme]};" in frame.group(1)

    lst = re.search(r"ThemeHourListView\s*\{([^}]*)\}", sheet)
    assert lst, "в листе попапов нет правила списка часов"
    rule = lst.group(1)
    assert f"selection-background-color: {tokens['color.accent'][theme]};" in rule
    assert f"selection-color: {tokens['color.accent.fg'][theme]};" in rule


def test_style_facing_hour_list_names_survive_only_in_synchronized_edits():
    # Both directions like the grid's pair test: each name is a class in the
    # module AND a selector in the generated popup sheet.
    source = Path(hour_popup_source_module.__file__).read_text(encoding="utf-8")
    sheet = compile_popup_qss(load_tokens(tokens_file_path()), "dark")
    for name in ("ThemeHourPopup", "ThemeHourListView"):
        assert f"class {name}(" in source, f"класс {name} переименован в модуле"
        assert re.search(rf"\b{name}\s*(\{{|::item)", sheet), (
            f"селектор {name} пропал из листа попапов"
        )
