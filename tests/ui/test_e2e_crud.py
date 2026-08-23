"""E2E scenario 3: CRUD of each of the four entity types.

Path: timeline context menu → entity card → link to an event → detail panel →
edit in the card → unlink (the only UI-level "delete" for standalone entities).
"""
from __future__ import annotations

import pytest

from app.presentation.views.entity_card_dialog import EntityCardDialog
from app.presentation.views.event_dialog import EventDialog

from tests.ui import helpers
from tests.ui.conftest import query_db

_TAB_ATTR = {
    "character": "char_tab",
    "organization": "org_tab",
    "item": "item_tab",
    "location": "loc_tab",
}
_DETAIL_LIST_ATTR = {
    "character": "char_list",
    "organization": "org_list",
    "item": "item_list",
    "location": "loc_list",
}
_REL_TABLE = {
    "character": ("event_character", "character_id"),
    "organization": ("event_organization", "organization_id"),
    "item": ("event_item", "item_id"),
    "location": ("event_location", "location_id"),
}


def _event_dialogs(window) -> list[EventDialog]:
    return [d for d in window.findChildren(EventDialog) if d.isVisible()]


@pytest.mark.parametrize("entity_type", ["character", "organization", "location", "item"])
async def test_entity_crud_via_timeline_context_menu(app, wait_for, menu_qmenu, modal_qdialog, entity_type):
    application, window = app
    db_path = application._db_path
    table = helpers.ENTITY_TABLES[entity_type]
    rel_table, rel_col = _REL_TABLE[entity_type]
    name, new_name = "Сущность-Исход", "Сущность-Новая"
    event_name = "Событие Связки"

    # 1. Create from the timeline context menu (+ button → menu item → card)
    await helpers.create_entity_via_context_menu(
        window, wait_for, menu_qmenu, entity_type, name, characteristics="Первоначальный образ",
    )
    await wait_for(lambda: len(query_db(db_path, f"SELECT id FROM {table} WHERE name = ?", (name,))) == 1)
    await helpers.wait_until_settled()
    entity_id = query_db(db_path, f"SELECT id FROM {table} WHERE name = ?", (name,))[0][0]

    # 2. Link the entity to a new event (event edit dialog → tab → "Привязать существующего")
    await helpers.create_event_via_ui(window, wait_for, event_name, characteristics="Связь")
    timeline = window.timeline_widget.list_widget

    def open_event_edit_dialog() -> EventDialog:
        item = next(timeline.item(i) for i in range(timeline.count()) if event_name in timeline.item(i).text())
        helpers.double_click_item(timeline, item)
        return None

    open_event_edit_dialog()
    await wait_for(lambda: _event_dialogs(window))
    edit_dialog = _event_dialogs(window)[0]
    tab = getattr(edit_dialog, _TAB_ATTR[entity_type])
    await helpers.link_existing_entity_in_tab(modal_qdialog, tab, name)
    await wait_for(lambda: any(name in tab.list_widget.item(i).text() for i in range(tab.list_widget.count())))
    edit_dialog.save_button.click()
    await wait_for(lambda: len(query_db(db_path, f"SELECT 1 FROM {rel_table} WHERE {rel_col} = ?", (entity_id,))) == 1)
    await helpers.wait_until_settled()

    # 3. The entity is displayed in the detail panel after selecting the event
    item = next(timeline.item(i) for i in range(timeline.count()) if event_name in timeline.item(i).text())
    helpers.select_item(timeline, item)
    detail_list = getattr(window.detail_panel, _DETAIL_LIST_ATTR[entity_type])
    await wait_for(lambda: name in helpers.detail_panel_names(detail_list))

    # 4. Edit in the card (double-click in the detail panel)
    item = next(
        detail_list.item(i) for i in range(detail_list.count())
        if name in helpers.detail_panel_names(detail_list)
    )
    helpers.double_click_item(detail_list, item)
    await wait_for(lambda: [
        d for d in window.findChildren(EntityCardDialog)
        if d.isVisible() and d.name_input.text() == name
    ])
    card = next(
        d for d in window.findChildren(EntityCardDialog)
        if d.isVisible() and d.name_input.text() == name
    )
    card.name_input.setText(new_name)
    card.save_button.click()
    await wait_for(lambda: len(query_db(db_path, f"SELECT id FROM {table} WHERE name = ?", (new_name,))) == 1)
    await helpers.wait_until_settled()
    # Detail panel refreshed with the new name
    await wait_for(lambda: new_name in helpers.detail_panel_names(detail_list))

    # 5. Unlink (UI-level delete): event edit → tab → "Удалить" → save
    item = next(timeline.item(i) for i in range(timeline.count()) if event_name in timeline.item(i).text())
    helpers.double_click_item(timeline, item)
    await wait_for(lambda: _event_dialogs(window))
    edit_dialog2 = _event_dialogs(window)[0]
    tab2 = getattr(edit_dialog2, _TAB_ATTR[entity_type])
    entry = next(
        tab2.list_widget.item(i) for i in range(tab2.list_widget.count())
        if new_name in tab2.list_widget.item(i).text()
    )
    helpers.select_item(tab2.list_widget, entry)
    tab2.remove_button.click()
    edit_dialog2.save_button.click()  # relations are persisted by the event dialog
    await wait_for(lambda: len(query_db(db_path, f"SELECT 1 FROM {rel_table} WHERE {rel_col} = ?", (entity_id,))) == 0)
    await helpers.wait_until_settled()
    await wait_for(lambda: new_name not in helpers.detail_panel_names(detail_list))
