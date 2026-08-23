"""E2E scenario 4: event creation + editing through the detail panel."""
from __future__ import annotations

from datetime import date

from app.presentation.views.entity_card_dialog import EntityCardDialog
from app.presentation.views.event_dialog import EventDialog

from tests.ui import helpers
from tests.ui.conftest import query_db


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
