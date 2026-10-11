"""Mention click routing: live event dialog, dead warning, scale stays silent.

The channel is textual end to end (add-dnd-game-face design Д4): the
tests emit exactly what the live host emits — the stored id as text;
the composition root converts kernel digits back to ints and routes
registered external keys through the source's resolve door."""
from __future__ import annotations

from datetime import date

from app.application.services.event_service import EventService
from app.domain import entity_registry
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
    dialog.mention_clicked.emit("event", str(target.id))
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
    dialog.mention_clicked.emit("character", str(char.id))
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
    dialog.mention_clicked.emit("character", "999999")
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
    dialog.mention_clicked.emit("event", "999999")
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
    dialog.mention_clicked.emit("planet", "1")
    await helpers.wait_until_settled()
    warnings = [b for b in message_boxes if b[0] == "warning"]
    assert len(warnings) == 1
    dead_text = warnings[0][2]
    message_boxes.clear()
    dialog.mention_clicked.emit("character", "999999")
    await helpers.wait_until_settled()
    again = [b for b in message_boxes if b[0] == "warning"]
    assert len(again) == 1
    assert again[0][2] == dead_text
    assert not any(b[0] == "critical" for b in message_boxes)
    message_boxes.clear()
    # A forged kernel marker with a non-numeric id (design Д4: the grammar
    # never writes one, so a hand-forge behaves exactly like a missing row)
    # rides the same one channel, not a crash and not a second message.
    dialog.mention_clicked.emit("character", "abc")
    await helpers.wait_until_settled()
    forged = [b for b in message_boxes if b[0] == "warning"]
    assert len(forged) == 1
    assert forged[0][2] == dead_text


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


# ── add-dnd-game-face task 5.2: the external chip at the real composition ───


def _ExtCardRec(name):
    """Настоящая протокольная карточка: коннектор штамповывает её через
    ``replace`` (task 6.1) — утка-класс под штамповку не ложится."""
    from app.presentation.modules.protocol import ExternalCardSource

    return ExternalCardSource(name=name, origin="SRD 5.1")


class _ExtSourceStub:
    """Duck of ExternalEntitySource with what the mention door reads."""

    def __init__(self, resolve_ok=True):
        self.visible = True
        self.type_descriptors = [entity_registry.ExternalTypeDescriptor(
            key="dd_feat", label="Черта", plural_label="Черты",
            icon_key="crosshair", reference=True,
        )]
        self.resolve_ok = resolve_ok

    async def warm(self):  # protocol task 6.2: греющему нечего
        return None

    def resolve_mention(self, key, source_id):
        if not self.resolve_ok:
            return None
        return _ExtCardRec("Тёмное зрение")

    def card_source(self, key, source_id):
        return self.resolve_mention(key, source_id)


async def _external_chip_setup(application, source):
    """The composition's enable-module posture without the dataset: the same
    two moves main.py makes when a module joins (registry + wiring carrier).
    The registry is process state — the kernel profile stays untouched."""
    saved = dict(entity_registry._EXTERNAL)
    entity_registry.register_external(source.type_descriptors)
    application._wiring.set_external_sources((source,))
    return saved


async def test_live_external_mention_seats_read_only_card(
    app, wait_for, message_boxes,
):
    """Spec «Клик по внешней записи»: an activated external chip seats the
    resolved record in the preview live area and opens NO editable dialog —
    no event dialog, no entity card, no warning."""
    application, window = app
    dialog, _target = await _host_event_dialog(application, window, wait_for)
    saved = await _external_chip_setup(application, _ExtSourceStub())
    try:
        dialog.mention_clicked.emit("dd_feat", "srd51/Darkvision")
        await helpers.wait_until_settled()
        assert application._wiring._preview_live == ("dd_feat", "srd51/Darkvision")
        assert message_boxes == []
        assert not any(
            d.isVisible() and d is not dialog
            for d in window.findChildren(EventDialog)
        )
        assert not any(
            d.isVisible() for d in window.findChildren(EntityCardDialog)
        )
    finally:
        entity_registry._EXTERNAL.clear()
        entity_registry._EXTERNAL.update(saved)
        application._wiring.set_external_sources(())


async def test_unavailable_external_mention_uses_the_dead_channel(
    app, wait_for, message_boxes,
):
    """Spec «Чип доживает до отключения датасета» as the user sees it: the
    record is gone (resolve answers None) — the SAME «Упоминание не найдено»
    warning the kernel dead chip produces, nothing else moves."""
    application, window = app
    dialog, _target = await _host_event_dialog(application, window, wait_for)
    saved = await _external_chip_setup(
        application, _ExtSourceStub(resolve_ok=False),
    )
    try:
        dialog.mention_clicked.emit("dd_feat", "srd51/Darkvision")
        await helpers.wait_until_settled()
        warnings = [b for b in message_boxes if b[0] == "warning"]
        assert len(warnings) == 1
        assert warnings[0][2] == "Упоминание не найдено."
        assert application._wiring._preview_live is None
    finally:
        entity_registry._EXTERNAL.clear()
        entity_registry._EXTERNAL.update(saved)
        application._wiring.set_external_sources(())
