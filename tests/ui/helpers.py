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


async def wait_until_settled(timeout_s: float = 10.0) -> None:
    """Wait until every app-scheduled asyncio task has completed.

    All session work inside the app happens within those tasks (Qt signal
    handlers spawn them via ``ensure_future``). Waiting on the task set —
    rather than probing the shared session — cannot race with a task's own
    continuation (a probe query on the shared session raises "concurrent
    operations are not permitted" when it overlaps the task's next query).
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
            raise TimeoutError("wait_until_settled: app tasks still pending")
        await asyncio.sleep(0)


def find_child(parent: QWidget, cls) -> Any | None:
    """First visible child of ``cls`` (a dialog opened via open())."""
    for child in parent.findChildren(cls):
        if child.isVisible():
            return child
    return parent.findChildren(cls)[0] if parent.findChildren(cls) else None


# ── E2E drivers (full user path through the wiring) ───────────────────────

def watch_available_entity_load(dialog) -> list:
    """Count per-tab ``set_available_entities`` calls.

    The dialog's available-entities load is a fire-and-forget task started in
    the same step the dialog opens; for the creation dialog it is still in
    flight when the test would save or link, racing the shared session.
    Spying each tab instance makes completion deterministic (install
    synchronously after the dialog becomes visible — the load task cannot
    have run yet).
    """
    done: list = []
    for tab in (dialog.org_tab, dialog.char_tab, dialog.item_tab, dialog.loc_tab):
        original = tab.set_available_entities

        def spy(entities, _tab=tab, _orig=original):
            _orig(entities)
            done.append(_tab)

        tab.set_available_entities = spy  # type: ignore[method-assign]
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
    timeline = window.timeline_widget.list_widget
    await wait_for(lambda: any(name in timeline.item(i).text() for i in range(timeline.count())))
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
