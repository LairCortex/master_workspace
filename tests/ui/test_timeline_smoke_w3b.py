"""Manual-smoke replacement for the W3b full-contour check (task 6.3, ported
to the QML island by Q2.5a).

Offscreen scripted pass of the scenarios the reviewer walks with a real mouse
in the GUI: the island tape at 220 px on a year-long sample (the QQuickWidget
clips — every header control stays inside at the minimum width); chip+popover
live window then reset; ``Alt+Up``/``Alt+Down`` jump over the empty-day
corridor without selecting; live theme toggle with an event selected keeps
both the selection and the scroll offset while repainting the tokens. Every
assertion mirrors a click the user sees, so this stands in for the manual
smoke run in CI.
"""
from __future__ import annotations

import asyncio
from datetime import date

from PySide6.QtCore import QDate, QEvent, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.presentation.views.timeline_date_popup import WINDOW_CHIP_ALL, window_chip_text
from app.presentation.views.timeline_rows import GapCollapsedRow
from tests.ui import helpers, timeline_probe


def _press_alt(widget, key: int) -> None:
    # QTest (not a raw sendEvent): QShortcut only matches key events that
    # carry the spontaneous flag, and QTest's key helpers synthesize them.
    QTest.keyClick(widget, key, Qt.KeyboardModifier.AltModifier)


def _row_visible_rows(window, idx: int) -> bool:
    """True when row ``idx``'s delegate sits inside the tape viewport."""
    delegate = timeline_probe.row_delegate(window, idx)
    if delegate is None:
        return False
    scene_y = delegate.mapToScene(QPointF(0, 0)).y()
    list_top = timeline_probe.event_list(window).mapToScene(QPointF(0, 0)).y()
    return list_top <= scene_y         and scene_y + delegate.height() <= timeline_probe.quick(window).height()


async def test_full_contour_smoke(app, wait_for, qtbot):
    application, window = app
    panel = window.timeline_widget

    # ── narrow island: 220 px stays functional (the QQuickWidget CLIPS, so
    # this pins what the old widgets resize merely degraded: at the minimum
    # every header control sits fully inside the island, nothing the user
    # must reach falls off the tape)
    panel.setFixedWidth(220)
    QApplication.processEvents()
    timeline_probe.pump(4)
    assert panel.width() == 220
    event_list = timeline_probe.event_list(window)
    assert event_list.width() > 0
    for name in ("addButton", "jumpPrev", "jumpNext", "windowChip",
                 "hideEmptyToggle"):
        it = timeline_probe.item(window, name)
        left = it.mapToScene(QPointF(0, 0)).x()
        right = it.mapToScene(QPointF(it.width(), 0)).x()
        assert 0 <= left and right <= panel.quick.width(), name

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
        tape = timeline_probe.tape(window)
        # The year materializes as day rows with every >14-day run collapsed.
        assert len(tape.rows) > 30
        assert any(isinstance(r, GapCollapsedRow) for r in tape.rows)
        timeline_probe.pump(4)
        assert timeline_probe.sticky_text(window)  # band shows the top-day date

        # ── chip + popover: two calendar taps apply live (no «Применить»)
        start, end = date(1200, 1, 1), date(1200, 3, 1)
        panel.window_popup.start_calendar.clicked.emit(QDate(start.year, start.month, start.day))
        panel.window_popup.start_calendar.clicked.emit(QDate(end.year, end.month, end.day))
        await wait_for(
            lambda: timeline_probe.chip_caption(window) == window_chip_text(start, end)
        )
        # The window keeps only the January event (tape re-modelled to it).
        await wait_for(lambda: len(tape.events) == 1)
        assert tape.events[0].name == "Начало Года"
        assert all(
            start <= r.date <= end for r in tape.rows if getattr(r, "date", None)
        ), "every visible day stays inside the window"

        # ── reset inside the popover → «Все дни» and back to the full year
        panel.window_popup.reset_button.click()
        await wait_for(lambda: timeline_probe.chip_caption(window) == WINDOW_CHIP_ALL)
        await wait_for(lambda: len(tape.events) == 3)
        await wait_for(lambda: any(
            isinstance(r, GapCollapsedRow) for r in tape.rows
        ) and len(tape.rows) > 30)

        # ── Alt+Down jumps over the empty-days corridor to the next event row
        i_head = timeline_probe.index_for_event(
            window, _event_id_named(window, "Начало Года"))
        i_mid = timeline_probe.index_for_event(
            window, _event_id_named(window, "Середина Лета"))
        assert i_head is not None and i_mid is not None and i_mid > i_head
        assert any(
            isinstance(r, GapCollapsedRow) for r in tape.rows[i_head:i_mid]
        ), 'the collapsed corridor sits between the two event cards'
        timeline_probe.set_content_y(window, 0)
        # Prime the reading position exactly like the old smoke primed the
        # list cursor (view.setCurrentRow(i_head) without a selection): the
        # landing index of a scroll_to_event is the VM's jump anchor.
        panel.scroll_to_event(_event_id_named(window, "Начало Года"))
        QApplication.processEvents()
        # Panel-scoped Alt shortcuts (WidgetWithChildrenShortcut) need an
        # active window with focus inside the panel (dialogs stole both).
        window.activateWindow()
        timeline_probe.quick(window).setFocus()
        QApplication.processEvents()
        _press_alt(timeline_probe.quick(window), Qt.Key.Key_Down)
        # The island answers with a scroll reveal (D7: the VM owns no
        # geometry): the walked-to card materializes and sits in view (in a
        # tall island the corridor's end may already be visible — the reveal
        # is then a no-op, exactly like the widgets-era PositionAtCenter),
        # and navigation implied no selection (spec: jump ≠ select).
        await wait_for(lambda: _row_visible_rows(window, i_mid), timeout_s=3.0)
        mid_delegate = timeline_probe.row_delegate(window, i_mid)
        assert mid_delegate is not None, "Alt+Down must land on the next event row"
        assert timeline_probe.selected_id(window) is None

        _press_alt(timeline_probe.quick(window), Qt.Key.Key_Up)
        await wait_for(
            lambda: _row_visible_rows(window, i_head),
            timeout_s=3.0,
        )
        head = timeline_probe.row_delegate(window, i_head)
        assert head is not None and head.property("kind") == "event" \
            and int(head.property("eventId")) == _event_id_named(window, "Начало Года"), \
            "Alt+Up lands on a card of the previous event"

        # ── live theme toggle with a selection: palette rebuilds, selection
        # and scroll are preserved (spec «Живая ре-тема», «Выбранное событие
        # в обеих темах»)
        event_id = helpers.click_timeline_event(window, "Середина Лета")
        qtbot.wait(1)
        await wait_for(lambda: timeline_probe.selected_id(window) == event_id)
        scroll_before = timeline_probe.content_y(window)
        theme_before = application._theme.theme

        application._theme.toggle()
        QApplication.processEvents()
        timeline_probe.pump(4)

        assert application._theme.theme != theme_before
        assert timeline_probe.selected_id(window) == event_id, "selection survives"
        assert timeline_probe.content_y(window) == scroll_before, "scroll survives"
        # the delegate washed in the NEW theme's accent (token-derivative
        # repaint with no screen code touched, spec «Живая ре-тема»)
        washed = [it for it in timeline_probe.visual_items(window)
                  if it.property("kind") == "event"
                  and int(it.property("eventId") or -1) == event_id
                  and it.property("selectedRow") is True]
        assert washed, "the card stays washed through the retheme"
        assert washed[0].property("accentColor").name() == \
            _accent_token(application._theme.theme)
        # the band surface rode the same bridge (never an OS palette):
        assert timeline_probe.sticky_text(window)
    finally:
        # Release the fixed width so any later relayout in the same app
        # lifecycle (or teardown) sees a normally-sized panel.
        try:
            panel.setMinimumWidth(0)
            panel.setMaximumWidth(16777215)  # QWIDGETSIZE_MAX
        except RuntimeError:
            pass  # widget already torn down


def _accent_token(theme: str) -> str:
    from tests.ui.test_theme_grab import token_color
    return token_color("color.accent", theme).name()


def _event_id_named(window, name: str) -> int:
    return next(e.id for e in timeline_probe.events(window) if name in e.name)
