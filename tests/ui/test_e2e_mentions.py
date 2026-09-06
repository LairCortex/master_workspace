"""Mention click routing: live event dialog, dead warning, scale stays silent."""
from __future__ import annotations

from datetime import date

from app.application.services.event_service import EventService
from app.presentation.views.entity_card_dialog import EntityCardDialog
from app.presentation.views.event_dialog import EventDialog

from tests.ui import helpers

D1 = date(1200, 1, 1)
D2 = date(1200, 12, 31)


async def _host_event_dialog(application, window, wait_for) -> tuple[EventDialog, object]:
    ev_svc = application._wiring._event_service
    target = await ev_svc.create_event_with_relations("Цель", D1, D2, "", "", {})
    host = await ev_svc.create_event_with_relations("Хост", D1, D2, "", "", {})
    window.timeline_widget.event_double_clicked.emit(host.id)
    await wait_for(lambda: any(d.isVisible() for d in window.findChildren(EventDialog)))
    dialog = next(d for d in window.findChildren(EventDialog) if d.isVisible())
    return dialog, target


async def test_live_event_mention_opens_event_dialog(app, wait_for):
    application, window = app
    dialog, target = await _host_event_dialog(application, window, wait_for)
    dialog.mention_clicked.emit("event", target.id)
    await wait_for(
        lambda: any(
            d.isVisible() and d.name_input.text() == "Цель" and d is not dialog
            for d in window.findChildren(EventDialog)
        )
    )
    opened = next(
        d for d in window.findChildren(EventDialog)
        if d.isVisible() and d.name_input.text() == "Цель"
    )
    assert opened.parent() is window


async def test_live_entity_mention_opens_card(app, wait_for):
    application, window = app
    char = await application._entity_services["character"].create_entity(
        "Герой", "", "", D1, D2,
    )
    await application._session.commit()
    dialog, _target = await _host_event_dialog(application, window, wait_for)
    dialog.mention_clicked.emit("character", char.id)
    await wait_for(
        lambda: any(
            d.isVisible() and d.name_input.text() == "Герой"
            for d in window.findChildren(EntityCardDialog)
        )
    )


async def test_dead_mention_id_shows_one_warning(app, wait_for, message_boxes):
    application, window = app
    dialog, _target = await _host_event_dialog(application, window, wait_for)
    before = window.statusBar().currentMessage()
    dialog.mention_clicked.emit("character", 999_999)
    await helpers.wait_until_settled()
    warnings = [b for b in message_boxes if b[0] == "warning"]
    assert len(warnings) == 1
    assert warnings[0][2]
    assert not any(b[0] == "critical" for b in message_boxes)
    assert window.statusBar().currentMessage() == before
    assert not any(
        d.isVisible() for d in window.findChildren(EntityCardDialog)
    )
    message_boxes.clear()
    dialog.mention_clicked.emit("event", 999_999)
    await helpers.wait_until_settled()
    event_warnings = [b for b in message_boxes if b[0] == "warning"]
    assert len(event_warnings) == 1
    assert event_warnings[0][2] == warnings[0][2]
    assert not any(
        d.isVisible() and d.name_input.text() == ""
        for d in window.findChildren(EventDialog)
        if d is not dialog
    )


async def test_unknown_mention_type_same_warning(app, wait_for, message_boxes):
    application, window = app
    dialog, _target = await _host_event_dialog(application, window, wait_for)
    dialog.mention_clicked.emit("planet", 1)
    await helpers.wait_until_settled()
    warnings = [b for b in message_boxes if b[0] == "warning"]
    assert len(warnings) == 1
    dead_text = warnings[0][2]
    message_boxes.clear()
    dialog.mention_clicked.emit("character", 999_999)
    await helpers.wait_until_settled()
    again = [b for b in message_boxes if b[0] == "warning"]
    assert len(again) == 1
    assert again[0][2] == dead_text
    assert not any(b[0] == "critical" for b in message_boxes)


async def test_scale_dblclick_empty_get_event_is_silent(
    app, wait_for, message_boxes, monkeypatch,
):
    application, window = app

    async def empty_get(self, event_id):
        return None

    monkeypatch.setattr(EventService, "get_event", empty_get)
    window.timeline_widget.event_double_clicked.emit(1)
    await helpers.wait_until_settled()
    assert message_boxes == []
    assert not any(d.isVisible() for d in window.findChildren(EventDialog))
