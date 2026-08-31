"""Offscreen-interaction helpers for UI E2E tests.

Qt-level interaction patterns that work with the offscreen platform (no real
mouse/menus): the application's own signal handlers run in full, only the
platform event delivery (context-menu dispatch, double-click recognition) is
simulated.
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable

from PySide6.QtCore import QDate
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import QApplication, QLabel, QMenu, QListWidget, QWidget

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from app.presentation.views.event_dialog import EventDialog
from app.presentation.views.entity_card_dialog import EntityCardDialog

#: entity type → DB table (for query_db assertions)
ENTITY_TABLES: dict[str, str] = {
    "character": "characters",
    "organization": "organizations",
    "location": "locations",
    "item": "items",
}


# ── Qt interaction simulation ──────────────────────────────────────────────

def right_click(widget: QWidget) -> None:
    """Simulate a right-click (context menu request).

    Offscreen the platform does not dispatch the context menu event on the
    right-button release, so a QContextMenuEvent is delivered explicitly and
    the application's ``customContextMenuRequested`` handler then runs in full.
    """
    pos = widget.rect().center()
    QApplication.sendEvent(
        widget,
        QContextMenuEvent(QContextMenuEvent.Reason.Mouse, pos, widget.mapToGlobal(pos)),
    )


def pick_menu_action(menu_qmenu, text: str) -> None:
    """Register a chooser so the next stubbed QMenu.exec() returns ``text``'s action."""

    def chooser(menu: QMenu) -> Any:
        for action in menu.actions():
            if action.text() == text:
                return action
        return None

    menu_qmenu.choose(chooser)


# ── Timeline row interaction (W3b: events are list rows, not Gantt bars) ──

#: Left inset from the rail's right edge where a synthetic click lands — the
#: rail zone itself is decorative and its presses are swallowed by the view,
#: so a click must clear it to reach the row's text (row_center clamps this).
_ROW_HIT_INSET = 12


def timeline_view(window) -> QWidget:
    """The vertical day-scale ``QListWidget`` of the main window's timeline."""
    return window.timeline_widget.rows_view


def has_event_named(window, name: str) -> bool:
    """True when an event whose name contains ``name`` is on the scale."""
    return any(name in e.name for e in timeline_view(window).events)


def find_event_id(window, name: str) -> int:
    return next(e.id for e in timeline_view(window).events if name in e.name)


def row_center(view, event_id: int) -> QPoint:
    """Viewport point of the EVENT-row for ``event_id``, clear of the rail.

    Scroll-aware: the caller scrolls the row into view first, then this reads
    its laid-out (viewport) rect and lands inside the text zone — never on the
    decorative date rail, whose presses the view ignores (spec «Рейка … клики
    по ней не обрабатываются»).
    """
    idx = view.index_for_event(event_id)
    if idx is None:
        raise AssertionError(f"event {event_id} has no row in the current sample")
    rect = view.visualItemRect(view.item(idx))
    if not rect.isValid() or rect.isNull():
        raise AssertionError(f"row {idx} for event {event_id} is not laid out")
    x = max(view.rail_width() + _ROW_HIT_INSET, 0)
    x = min(x, max(view.viewport().width() - 1, 0))
    return QPoint(x, rect.center().y())


def _mouse(vp, point, etype, button, buttons):
    QApplication.sendEvent(vp, QMouseEvent(
        etype, QPointF(point), vp.mapToGlobal(point),
        button, buttons, Qt.KeyboardModifier.NoModifier))


def _press_and_release(view, point: QPoint) -> None:
    """A full left click on the list viewport (drives the ``clicked`` signal)."""
    left, none = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton
    vp = view.viewport()
    _mouse(vp, point, QEvent.Type.MouseButtonPress, left, left)
    _mouse(vp, point, QEvent.Type.MouseButtonRelease, left, none)


def _double_click_at(view, point: QPoint) -> None:
    """A full left double-click (press/release/DblClick/release) on the viewport."""
    left, none = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton
    vp = view.viewport()
    _mouse(vp, point, QEvent.Type.MouseButtonPress, left, left)
    _mouse(vp, point, QEvent.Type.MouseButtonRelease, left, none)
    _mouse(vp, point, QEvent.Type.MouseButtonDblClick, left, left)
    _mouse(vp, point, QEvent.Type.MouseButtonRelease, left, none)


def click_timeline_event(window, name: str) -> int:
    """Single-click the EVENT row of ``name``; returns the event id."""
    view = timeline_view(window)
    event_id = find_event_id(window, name)
    view.scroll_to_event(event_id)
    _press_and_release(view, row_center(view, event_id))
    return event_id


def double_click_timeline_event(window, name: str) -> int:
    """Double-click the EVENT row of ``name`` (edit dialog trigger)."""
    view = timeline_view(window)
    event_id = find_event_id(window, name)
    view.scroll_to_event(event_id)
    _double_click_at(view, row_center(view, event_id))
    return event_id


def double_click_item(list_widget: QListWidget, item) -> None:
    """Simulate a double-click on a list item (item widgets swallow raw dblclicks offscreen)."""
    list_widget.itemDoubleClicked.emit(item)


def select_item(list_widget: QListWidget, item) -> None:
    """Simulate a single-click selection on a list item."""
    list_widget.setCurrentItem(item)


def detail_panel_names(detail_list: QListWidget) -> list[str]:
    """Names shown in a DetailPanel entity list (first label of each item widget)."""
    names: list[str] = []
    for i in range(detail_list.count()):
        item = detail_list.item(i)
        w = detail_list.itemWidget(item)
        if w is None:
            continue
        labels = w.findChildren(QLabel)
        names.append(labels[0].text() if labels else "")
    return names


async def wait_until_settled(timeout_s: float = 90.0) -> None:
    """Wait until every app-scheduled asyncio task has completed.

    All session work inside the app happens within those tasks (Qt signal
    handlers spawn them via ``ensure_future``). Waiting on the task set —
    rather than probing the shared session — cannot race with a task's own
    continuation (a probe query on the shared session raises "concurrent
    operations are not permitted" when it overlaps the task's next query).

    90s (not 10s): on Linux CI, under ``coverage``'s tracing overhead,
    qasync's cross-thread ``call_soon_threadsafe`` bridge (an aiosqlite
    worker thread emitting a Qt signal that re-arms a zero-delay QTimer on
    the GUI thread) has been observed to starve for tens of seconds — with
    a heavy tail — under sustained event-loop load before firing. Confirmed
    via repeated Docker/ubuntu-24.04 repro of the exact CI command: a ~80%
    full-suite failure rate at 10s, still occasional failures at 30s, and
    reliably clean at 90s. The task is never actually stuck forever (the DB
    call itself completes almost instantly; only the completion callback's
    delivery is delayed), so a generous timeout absorbs the delay instead
    of flaking the build.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s

    def _pending() -> bool:
        return any(
            t is not asyncio.current_task() and not t.done()
            for t in asyncio.all_tasks(loop)
        )

    while True:
        if not _pending():
            await asyncio.sleep(0)  # drain trailing callbacks of finished tasks
            if not _pending():
                return
        if loop.time() >= deadline:
            pending = [
                t for t in asyncio.all_tasks(loop)
                if t is not asyncio.current_task() and not t.done()
            ]
            raise TimeoutError(
                f"wait_until_settled({timeout_s}s): "
                f"{len(pending)} app task(s) still pending:\n"
                + "".join(_describe_task(t) for t in pending[:5])
            )
        await asyncio.sleep(0)


def _describe_task(t: asyncio.Task) -> str:
    """One line: the stuck coroutine and where it is suspended."""
    coro = t.get_coro()
    name = getattr(coro, "__qualname__", type(coro).__name__)
    try:
        frame = t.get_stack()[0]
        loc = f"{frame.filename}:{frame.lineno} in {frame.name}"
    except Exception as e:
        loc = f"unknown frame ({type(e).__name__})"
    try:
        import sys
        cr_frame = coro.cr_frame
        cr_await = coro.cr_await
        await_info = type(cr_await).__name__ if cr_await is not None else "None"
        if cr_await is not None and hasattr(cr_await, "get_loop"):
            await_info += f"(loop_closed={cr_await.get_loop().is_closed()})"
        import threading
        frames = sys._current_frames()
        parts = []
        for th in threading.enumerate():
            f = frames.get(th.ident)
            top = f"{f.f_code.co_filename}:{f.f_lineno} in {f.f_code.co_name}" if f else "?"
            parts.append(f"{th.name}[{top}]")
        threads = " | ".join(parts)
        loc += (
            f" | cr_frame={cr_frame} cr_await={await_info}"
            f" | task_loop_closed={t.get_loop().is_closed()}"
            f" | threads=[{threads}]"
        )
        # Full thread dump to stderr for post-mortem analysis.
        import faulthandler
        import sys as _sys
        faulthandler.dump_traceback(file=_sys.stderr, all_threads=True)
    except Exception as diag_exc:  # diagnostics must never mask the timeout
        loc += f" | diag failed: {diag_exc!r}"
    return f"  - {name} stuck at {loc}\n  - repr: {t!r}\n"


def find_child(parent: QWidget, cls) -> Any | None:
    """First visible child of ``cls`` (a dialog opened via open())."""
    for child in parent.findChildren(cls):
        if child.isVisible():
            return child
    return parent.findChildren(cls)[0] if parent.findChildren(cls) else None


# ── E2E drivers (full user path through the wiring) ───────────────────────

def watch_available_entity_load(dialog) -> list:
    """Count the dialog's ``set_available_entities`` calls (attr-API).

    The dialog's available-entities load is a fire-and-forget task started in
    the same step the dialog opens; for the creation dialog it is still in
    flight when the test would save or link, racing the shared session.
    Spying the dialog method makes completion deterministic (install
    synchronously after the dialog becomes visible — the load task cannot
    have run yet). Returns the attr names as they get filled (4 for
    EventDialog: organizations, characters, items, locations).
    """
    done: list = []
    original = dialog.set_available_entities

    def spy(attr, entities, _orig=original):
        _orig(attr, entities)
        done.append(attr)

    dialog.set_available_entities = spy
    return done


async def create_event_via_ui(
    window,
    wait_for: Callable,
    name: str,
    characteristics: str = "Описание события",
    backstory: str = "",
    start_date: QDate | None = None,
    end_date: QDate | None = None,
) -> EventDialog:
    """Create an event through the timeline '+' button → EventDialog → save.

    Waits until the fire-and-forget available-entities load has finished and
    the event is visible on the timeline.
    """
    window.timeline_widget.add_button.click()
    # A dialog accepted earlier stays in the child list: resolve the visible one.
    await wait_for(
        lambda: any(d.isVisible() for d in window.findChildren(EventDialog))
    )
    dialog = next(d for d in window.findChildren(EventDialog) if d.isVisible())
    load_done = watch_available_entity_load(dialog)
    await wait_for(lambda: len(load_done) == 4)
    dialog.name_input.setText(name)
    dialog.characteristics_input.setContent(characteristics)
    if backstory:
        dialog.backstory_input.setContent(backstory)
    if start_date is not None:
        dialog.start_date_input.setDate(start_date)
    if end_date is not None:
        dialog.end_date_input.setDate(end_date)
    assert dialog.save_button.isEnabled()
    dialog.save_button.click()
    await wait_for(lambda: has_event_named(window, name))
    return dialog


async def create_entity_via_context_menu(
    window,
    wait_for: Callable,
    menu_qmenu,
    entity_type: str,
    name: str,
    characteristics: str = "",
) -> EntityCardDialog:
    """Create an entity through the timeline '+' context menu → card → save.

    Menu labels live in TimelineWidget (RU): map entity type to the item text.
    Returns the dialog used for creation (already accepted/closed).
    """
    menu_labels = {
        "character": "Новый персонаж",
        "location": "Новая локация",
        "organization": "Новая организация",
        "item": "Новый предмет",
    }
    pick_menu_action(menu_qmenu, menu_labels[entity_type])
    right_click(window.timeline_widget.add_button)
    # A card accepted earlier stays in the child list: resolve the visible one.
    await wait_for(
        lambda: any(d.isVisible() for d in window.findChildren(EntityCardDialog))
    )
    dialog = next(d for d in window.findChildren(EntityCardDialog) if d.isVisible())
    dialog.name_input.setText(name)
    if characteristics:
        dialog.characteristics_input.setContent(characteristics)
    dialog.save_button.click()
    return dialog


async def link_existing_entity_in_tab(
    modal_qdialog,
    tab,
    name: str,
) -> None:
    """Pre-select ``name`` in the next 'Привязать существующего' picker and accept it."""

    def preselect(dlg) -> None:
        for lst in dlg.findChildren(QListWidget):
            for i in range(lst.count()):
                if name in lst.item(i).text():
                    lst.item(i).setSelected(True)

    modal_qdialog.on_exec(preselect)
    tab.link_button.click()


_EVENT_TAB_ATTR = {
    "organizations": "org_tab",
    "characters": "char_tab",
    "items": "item_tab",
    "locations": "loc_tab",
}


def _parent_section(parent_dialog, attr: str):
    """The parent dialog's RelatedSection for ``attr`` (card or event dialog)."""
    sections = getattr(parent_dialog, "_related_sections", None)
    if sections and attr in sections:
        return sections[attr]
    return getattr(parent_dialog, _EVENT_TAB_ATTR[attr])


async def create_related_via_popup(
    window,
    wait_for: Callable,
    modal_qdialog,
    parent_dialog,
    attr: str,
    entity_type: str,
    name: str,
    links: tuple[tuple[str, str], ...] = (),
) -> EntityCardDialog:
    """Create a related entity through the section's «Создать нового» popup.

    Clicks the create button of the parent's section for ``attr``, fills the
    popup card — optionally linking pre-existing entities in its own related
    sections (``links`` = [(related_attr, name), ...]) — and saves it.
    Returns the popup dialog (already accepted).
    """
    _parent_section(parent_dialog, attr).create_button.click()
    await wait_for(
        lambda: any(
            d.isVisible() and d._entity_type == entity_type
            for d in window.findChildren(EntityCardDialog)
        )
    )
    sub = next(
        d for d in window.findChildren(EntityCardDialog)
        if d.isVisible() and d._entity_type == entity_type
    )
    for rel_attr, link_name in links:
        await link_existing_entity_in_tab(
            modal_qdialog, sub._related_sections[rel_attr], link_name
        )
        section = sub._related_sections[rel_attr]
        await wait_for(
            lambda ln=link_name, s=section: any(
                ln in s.list_widget.item(i).text() for i in range(s.list_widget.count())
            )
        )
    sub.name_input.setText(name)
    sub.save_button.click()
    await wait_for(lambda: not sub.isVisible())
    return sub
