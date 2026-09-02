"""Manual-smoke replacement for the W3b full-contour check (task 6.3).

Offscreen scripted pass of the scenarios the reviewer walks with a real mouse
in the GUI: the timeline at 220 px on a year-long sample; chip+popover live
window then reset; ``Alt+Up``/``Alt+Down`` jump over the empty-day corridor;
live theme toggle with an event selected keeps both the selection and the
scroll offset while repainting the tokens. Every assertion mirrors a click the
user sees, so this stands in for the manual smoke run in CI.
"""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from app.presentation.views.timeline_rows import EventRow, GapCollapsedRow
from app.presentation.views.timeline_widget import WINDOW_CHIP_ALL, window_chip_text

from tests.ui import helpers


def _press_alt(view, key: int) -> None:
    for etype in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
        QApplication.sendEvent(
            view, QKeyEvent(etype, key, Qt.KeyboardModifier.AltModifier)
        )


def _row_center_in_view(view, idx: int):
    rect = view.visualItemRect(view.item(idx))
    return 0 <= rect.top() and rect.bottom() <= view.viewport().height()


async def test_full_contour_smoke(app, wait_for, qtbot):
    application, window = app
    panel = window.timeline_widget
    view = panel.rows_view

    # ── narrow panel: 220 px stays functional (D9: popover is top-level, the
    # panel itself must render and take input even at the minimum width)
    panel.setFixedWidth(220)
    QApplication.processEvents()
    assert panel.width() == 220
    assert view.width() > 0 and view.viewport().width() > 0

    try:
        # ── year-long sample (~360 rows, three events half a year apart)
        await helpers.create_event_via_ui(
            window, wait_for, "Начало Года",
            start_date=QDate(1200, 1, 1), end_date=QDate(1200, 1, 2),
        )
        await helpers.create_event_via_ui(
            window, wait_for, "Середина Лета",
            start_date=QDate(1200, 7, 1), end_date=QDate(1200, 7, 15),
        )
        await helpers.create_event_via_ui(
            window, wait_for, "Конец Года",
            start_date=QDate(1200, 12, 31), end_date=QDate(1200, 12, 31),
        )
        # The year materializes as day rows with every >14-day run collapsed.
        assert len(view.rows) > 30
        assert any(isinstance(r, GapCollapsedRow) for r in view.rows)
        sticky = view.sticky_label
        assert sticky.isVisible() and sticky.text()  # sticky band shows the top-day date

        # ── chip + popover: two calendar taps apply live (no «Применить»)
        start, end = date(1200, 1, 1), date(1200, 3, 1)
        panel.window_popup.start_calendar.clicked.emit(QDate(start.year, start.month, start.day))
        panel.window_popup.start_calendar.clicked.emit(QDate(end.year, end.month, end.day))
        await wait_for(lambda: panel.window_chip.text() == window_chip_text(start, end))
        # The window keeps only the January event (tape re-modelled to it).
        await wait_for(lambda: len(view.events) == 1)
        assert view.events[0].name == "Начало Года"
        assert all(
            start <= r.date <= end for r in view.rows
        ), "every visible day stays inside the window"

        # ── reset inside the popover → «Все дни» and back to the full year
        panel.window_popup.reset_button.click()
        await wait_for(lambda: panel.window_chip.text() == WINDOW_CHIP_ALL)
        await wait_for(lambda: len(view.events) == 3)
        await wait_for(lambda: any(
            isinstance(r, GapCollapsedRow) for r in view.rows
        ) and len(view.rows) > 30)

        # ── Alt+Down jumps over the empty-days corridor to the next event row
        i_head = view.index_for_event(_event_id_named(view, "Начало Года"))
        i_mid = view.index_for_event(_event_id_named(view, "Середина Лета"))
        assert i_head is not None and i_mid is not None and i_mid > i_head
        assert any(
            isinstance(r, GapCollapsedRow) for r in view.rows[i_head:i_mid]
        ), 'the collapsed corridor sits between the two event cards'
        view.verticalScrollBar().setValue(0)
        view.setCurrentRow(i_head)
        # Panel-scoped Alt shortcuts (WidgetWithChildrenShortcut) need an
        # active window with focus inside the panel (dialogs stole both).
        window.activateWindow()
        view.setFocus()
        QApplication.processEvents()
        _press_alt(view, Qt.Key.Key_Down)
        QApplication.processEvents()
        assert view.currentRow() == i_mid, "Alt+Down must land on the next event row"
        assert _row_center_in_view(view, i_mid), "the reached row must be visible"
        # Selection alone was not implied by navigation (spec: jump ≠ select)
        assert view.selected_id is None

        _press_alt(view, Qt.Key.Key_Up)
        QApplication.processEvents()
        landed = view.rows[view.currentRow()]
        assert isinstance(landed, EventRow) and landed.event_id == _event_id_named(
            view, "Начало Года"
        ), "Alt+Up lands on a card of the previous event"

        # ── live theme toggle with a selection: palette rebuilds, selection and
        # scroll are preserved (spec «Живая ре-тема», «Выбранное событие в обеих темах»)
        event_id = helpers.click_timeline_event(window, "Середина Лета")
        qtbot.wait(1)
        await wait_for(lambda: view.selected_id == event_id)
        scroll_before = view.verticalScrollBar().value()
        fill_before = view.paint_palette().selected_fill.name()
        theme_before = application._theme.theme

        application._theme.toggle()
        QApplication.processEvents()

        assert application._theme.theme != theme_before
        assert view.selected_id == event_id, "selection survives the retheme"
        assert view.verticalScrollBar().value() == scroll_before, "scroll survives the retheme"
        assert view.paint_palette().selected_fill.name() != fill_before, (
            "the delegate palette must be rebuilt from the new theme tokens"
        )
        # The sticky band still reflects the token-derived surface, not the OS palette
        assert view.paint_palette().background.name()
    finally:
        # Release the fixed width so any later relayout in the same app
        # lifecycle (or teardown) sees a normally-sized panel.
        try:
            panel.setMinimumWidth(0)
            panel.setMaximumWidth(16777215)  # QWIDGETSIZE_MAX
        except RuntimeError:
            pass  # widget already torn down


def _event_id_named(view, name: str) -> int:
    return next(e.id for e in view.events if name in e.name)
