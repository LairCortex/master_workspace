"""E2E scenario 4: event creation + editing through the detail panel.

Covers the popup entity-creation spec (related-entity-creation):
«Создание персонажа из диалога события», «Сохранение события фиксирует
созданную сущность», «Привязка локации к новому персонажу»,
«Отмена диалога родителя», «Отвязание не удаляет сущность»,
«Смешанный состав секций».
"""
from __future__ import annotations

from datetime import date

from app.presentation.views.entity_card_dialog import EntityCardDialog
from app.presentation.views.event_dialog import EventDialog

from tests.ui import helpers
from tests.ui.conftest import query_db


async def _open_create_dialog(window, wait_for) -> EventDialog:
    """Open the event creation dialog and wait for the available-entities load."""
    window.timeline_widget.add_button.click()
    await wait_for(lambda: any(d.isVisible() for d in window.findChildren(EventDialog)))
    dialog = next(d for d in window.findChildren(EventDialog) if d.isVisible())
    loaded = helpers.watch_available_entity_load(dialog)
    await wait_for(lambda: len(loaded) == 4)
    return dialog


def _name_in_list(section, name: str) -> bool:
    return any(name in section.list_widget.item(i).text() for i in range(section.list_widget.count()))


async def test_event_creation_and_detail_panel_editing(app, wait_for, modal_qdialog):
    application, window = app
    db_path = application._db_path

    # A pre-existing character to link (service-layer seed, committed).
    await application._entity_services["character"].create_entity(
        name="Генерал Вард",
        characteristics="Опытный стратег",
        backstory="",
        start_date=date(1200, 1, 1),
        end_date=date(1200, 12, 31),
    )
    await application._session.commit()

    # Create the event and link the character through the dialog.
    window.timeline_widget.add_button.click()
    await wait_for(lambda: bool(window.findChildren(EventDialog)))
    dialog = window.findChildren(EventDialog)[0]
    loaded = helpers.watch_available_entity_load(dialog)
    await wait_for(lambda: len(loaded) == 4)
    dialog.name_input.setText("Битва у моста")
    dialog.characteristics_input.setContent("Решающее сражение")
    await helpers.link_existing_entity_in_tab(modal_qdialog, dialog.char_tab, "Генерал Вард")
    await wait_for(lambda: any(
        "Генерал Вард" in dialog.char_tab.list_widget.item(i).text()
        for i in range(dialog.char_tab.list_widget.count())
    ))
    dialog.save_button.click()

    timeline = window.timeline_widget.list_widget
    await wait_for(lambda: any("Битва у моста" in timeline.item(i).text() for i in range(timeline.count())))

    # Select on the timeline → detail panel loads the event.
    item = next(timeline.item(i) for i in range(timeline.count()) if "Битва у моста" in timeline.item(i).text())
    helpers.select_item(timeline, item)
    detail = window.detail_panel
    await wait_for(lambda: detail.title_label.text() == "Битва у моста")
    assert detail.date_label.text()
    await wait_for(lambda: "Генерал Вард" in helpers.detail_panel_names(detail.char_list))

    # Edit the linked character from the detail panel (its card).
    ent_item = detail.char_list.item(0)
    helpers.double_click_item(detail.char_list, ent_item)
    await wait_for(lambda: [
        d for d in window.findChildren(EntityCardDialog)
        if d.isVisible() and d.name_input.text() == "Генерал Вард"
    ])
    card = next(
        d for d in window.findChildren(EntityCardDialog)
        if d.isVisible() and d.name_input.text() == "Генерал Вард"
    )
    card.name_input.setText("Генерал Старый Вард")
    card.characteristics_input.setContent("Старый, но опытный")
    card.save_button.click()
    await wait_for(lambda: len(query_db(
        db_path, "SELECT id FROM characters WHERE name = ?", ("Генерал Старый Вард",),
    )) == 1)
    await helpers.wait_until_settled()
    # Detail panel refreshed with the updated entity
    await wait_for(lambda: "Генерал Старый Вард" in helpers.detail_panel_names(detail.char_list))

    # Edit the event itself (double-click on the timeline → renamed on the timeline and in the panel).
    item = next(timeline.item(i) for i in range(timeline.count()) if "Битва у моста" in timeline.item(i).text())
    helpers.double_click_item(timeline, item)
    # The original creation dialog is hidden (not destroyed) after accept — filter visible ones
    await wait_for(lambda: [d for d in window.findChildren(EventDialog) if d.isVisible()])
    edit_dialog = [d for d in window.findChildren(EventDialog) if d.isVisible()][0]
    assert edit_dialog.windowTitle() == "Редактировать событие"
    edit_dialog.name_input.setText("Битва у разрушенного моста")
    edit_dialog.save_button.click()
    await wait_for(lambda: any(
        "Битва у разрушенного моста" in timeline.item(i).text() for i in range(timeline.count())
    ))
    await wait_for(lambda: detail.title_label.text() == "Битва у разрушенного моста")


# ── Popup entity creation (related-entity-creation spec) ─────────────────

async def _seed_entity(app, entity_type: str, name: str) -> int:
    """Create + commit an entity at the service layer; return its id."""
    application, _ = app
    await application._entity_services[entity_type].create_entity(
        name=name, characteristics="", backstory="",
        start_date=date(1200, 1, 1), end_date=date(1200, 12, 31),
    )
    await application._session.commit()
    table = helpers.ENTITY_TABLES[entity_type]
    return query_db(application._db_path, f"SELECT id FROM {table} WHERE name = ?", (name,))[0][0]


def _unlink_in_section(section, name: str) -> None:
    """Select ``name`` in the section list and click «Отвязать»."""
    entry = next(
        section.list_widget.item(i) for i in range(section.list_widget.count())
        if name in section.list_widget.item(i).text()
    )
    helpers.select_item(section.list_widget, entry)
    section.remove_button.click()


async def test_create_character_from_event_dialog(app, wait_for, modal_qdialog):
    """4.2 «Создание персонажа из диалога события» + «Сохранение события фиксирует созданную сущность»."""
    application, window = app
    db_path = application._db_path

    dialog = await _open_create_dialog(window, wait_for)
    dialog.name_input.setText("Битва героев")
    dialog.characteristics_input.setContent("Создаём персонажа в поппапе")

    await helpers.create_related_via_popup(
        window, wait_for, modal_qdialog, dialog, "characters", "character", "Рыцарь",
    )
    await helpers.wait_until_settled()
    assert _name_in_list(dialog.char_tab, "Рыцарь")  # entity appears in the parent section

    dialog.save_button.click()
    timeline = window.timeline_widget.list_widget
    await wait_for(lambda: any(
        "Битва героев" in timeline.item(i).text() for i in range(timeline.count())
    ))
    await helpers.wait_until_settled()

    # Character persisted and linked to the event.
    char_id = query_db(db_path, "SELECT id FROM characters WHERE name = 'Рыцарь'")[0][0]
    event_id = query_db(db_path, "SELECT id FROM events WHERE name = 'Битва героев'")[0][0]
    linked = query_db(
        db_path,
        "SELECT 1 FROM event_character WHERE event_id = ? AND character_id = ?",
        (event_id, char_id),
    )
    assert len(linked) == 1


async def test_link_location_in_character_popup(app, wait_for, modal_qdialog):
    """4.3 «Привязка локации к новому персонажу».

    A pre-existing location is linked inside the creation popup; after saving
    the event the new character carries the location relation in the DB.
    """
    application, window = app
    db_path = application._db_path
    loc_id = await _seed_entity(app, "location", "Деревня")

    dialog = await _open_create_dialog(window, wait_for)
    dialog.name_input.setText("В деревне")
    dialog.characteristics_input.setContent("Персонаж привязан к локации из поппапа")

    await helpers.create_related_via_popup(
        window, wait_for, modal_qdialog, dialog, "characters", "character", "Местный",
        links=[("locations", "Деревня")],
    )
    await helpers.wait_until_settled()
    # The location is linked inside the popup's own related section.
    assert _name_in_list(dialog.char_tab, "Местный")

    dialog.save_button.click()
    timeline = window.timeline_widget.list_widget
    await wait_for(lambda: any(
        "В деревне" in timeline.item(i).text() for i in range(timeline.count())
    ))
    await helpers.wait_until_settled()

    char_id = query_db(db_path, "SELECT id FROM characters WHERE name = 'Местный'")[0][0]
    linked = query_db(
        db_path,
        "SELECT 1 FROM character_location WHERE character_id = ? AND location_id = ?",
        (char_id, loc_id),
    )
    assert len(linked) == 1


async def test_cancel_parent_dialog_after_popup_create(app, wait_for, modal_qdialog):
    """4.4 «Отмена диалога родителя» — flushed entity is not committed.

    An entity created in the popup (with a link made inside the popup) and a
    never-saved event leave the DB untouched — including after a later
    commit in the same session: on reject the pending rows are explicitly
    deleted, so no subsequent save can persist the cancelled entity.
    """
    application, window = app
    db_path = application._db_path
    await _seed_entity(app, "location", "Деревня")

    # A dialog rejected without any popup exercises the empty cleanup path.
    window.timeline_widget.add_button.click()
    await wait_for(lambda: any(d.isVisible() for d in window.findChildren(EventDialog)))
    empty_dialog = next(d for d in window.findChildren(EventDialog) if d.isVisible())
    empty_dialog.reject()
    await helpers.wait_until_settled()  # its fire-and-forget load finishes here

    dialog = await _open_create_dialog(window, wait_for)
    dialog.name_input.setText("Мимолётное")
    dialog.characteristics_input.setContent("Будет отменено")

    await helpers.create_related_via_popup(
        window, wait_for, modal_qdialog, dialog, "characters", "character", "Фантом",
        links=[("locations", "Деревня")],
    )
    await helpers.wait_until_settled()
    assert _name_in_list(dialog.char_tab, "Фантом")

    # Cancel the parent (reject). The flush stayed uncommitted and the
    # pending rows (entity, description, M2M link) are deleted on reject.
    dialog.reject()
    await helpers.wait_until_settled()

    # Any later commit must not persist the cancelled entity or its links.
    await application._session.commit()
    await helpers.wait_until_settled()

    assert query_db(db_path, "SELECT COUNT(*) FROM characters")[0][0] == 0
    assert query_db(db_path, "SELECT COUNT(*) FROM events")[0][0] == 0
    assert query_db(db_path, "SELECT COUNT(*) FROM character_location")[0][0] == 0
    # Only the seeded location's description survives.
    assert query_db(db_path, "SELECT COUNT(*) FROM descriptions")[0][0] == 1


async def test_unlink_popup_entity_keeps_entity(app, wait_for, modal_qdialog):
    """4.5 «Отвязание не удаляет сущность».

    Create in popup → unlink in the section → save the event. The entity row
    was flushed with the popup save and rides the event commit, so it exists
    in the DB but is not linked to the event.
    """
    application, window = app
    db_path = application._db_path

    dialog = await _open_create_dialog(window, wait_for)
    dialog.name_input.setText("Отвязка")
    dialog.characteristics_input.setContent("Сущность отвязана до сохранения")

    await helpers.create_related_via_popup(
        window, wait_for, modal_qdialog, dialog, "characters", "character", "Странник",
    )
    await helpers.wait_until_settled()
    assert _name_in_list(dialog.char_tab, "Странник")

    _unlink_in_section(dialog.char_tab, "Странник")
    assert dialog.char_tab.list_widget.count() == 0

    dialog.save_button.click()
    timeline = window.timeline_widget.list_widget
    await wait_for(lambda: any(
        "Отвязка" in timeline.item(i).text() for i in range(timeline.count())
    ))
    await helpers.wait_until_settled()

    char_id = query_db(db_path, "SELECT id FROM characters WHERE name = 'Странник'")[0][0]
    event_id = query_db(db_path, "SELECT id FROM events WHERE name = 'Отвязка'")[0][0]
    linked = query_db(
        db_path,
        "SELECT 1 FROM event_character WHERE event_id = ? AND character_id = ?",
        (event_id, char_id),
    )
    assert len(linked) == 0  # entity exists, but not linked


async def _open_event_edit_dialog(window, wait_for, event_name: str) -> EventDialog:
    timeline = window.timeline_widget.list_widget
    item = next(
        timeline.item(i) for i in range(timeline.count())
        if event_name in timeline.item(i).text()
    )
    helpers.double_click_item(timeline, item)
    await wait_for(lambda: [d for d in window.findChildren(EventDialog) if d.isVisible()])
    return next(d for d in window.findChildren(EventDialog) if d.isVisible())


async def test_edit_event_mixed_section_composition(app, wait_for, modal_qdialog):
    """4.7 «Смешанный состав секций».

    The character is first linked to the event (committed). Then in the edit
    dialog the section holds the previously linked entity plus a new
    popup-created one, while the previously linked one gets unlinked. After
    saving, only the entities still present in the list remain linked.
    """
    application, window = app
    db_path = application._db_path
    await _seed_entity(app, "character", "Знакомец")

    # Create the event, then link the pre-existing character (committed).
    await helpers.create_event_via_ui(window, wait_for, "Смешанное", characteristics="Состав")
    setup = await _open_event_edit_dialog(window, wait_for, "Смешанное")

    await helpers.link_existing_entity_in_tab(modal_qdialog, setup.char_tab, "Знакомец")
    await wait_for(lambda: _name_in_list(setup.char_tab, "Знакомец"))
    setup.save_button.click()
    await helpers.wait_until_settled()
    event_id = query_db(db_path, "SELECT id FROM events WHERE name = 'Смешанное'")[0][0]
    assert len(query_db(
        db_path, "SELECT 1 FROM event_character WHERE event_id = ?", (event_id,)
    )) == 1

    # Second edit: section pre-filled with the linked character.
    edit = await _open_event_edit_dialog(window, wait_for, "Смешанное")
    assert _name_in_list(edit.char_tab, "Знакомец")

    # Add a new character via the popup, then unlink the previously linked one.
    await helpers.create_related_via_popup(
        window, wait_for, modal_qdialog, edit, "characters", "character", "Новичок",
    )
    await helpers.wait_until_settled()
    assert _name_in_list(edit.char_tab, "Новичок")
    _unlink_in_section(edit.char_tab, "Знакомец")

    edit.save_button.click()
    await helpers.wait_until_settled()

    new_id = query_db(db_path, "SELECT id FROM characters WHERE name = 'Новичок'")[0][0]
    linked = query_db(
        db_path, "SELECT character_id FROM event_character WHERE event_id = ?", (event_id,)
    )
    # Only the still-present entity remains linked; the pre-linked one is unlinked.
    assert [row[0] for row in linked] == [new_id]
