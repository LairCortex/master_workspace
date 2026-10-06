"""The related-create popup card hides its own «Создать нового» (design claim
2026-10-06: a shown button must work — at depth = 1 the nested create signal
has no receiver, so the popup's sections show only the pair that works:
«Привязать существующего» and «Отвязать»).

Two pins, offscreen, on the stub-connector pattern of
``test_sheet_stack_scrim`` (the open paths touch no session, the lock only
satisfies the constructor):

* ``_open_related_create_dialog`` threads ``related_create_enabled=False``
  through the shared card factory — every popup section state answers
  ``canCreate`` False, the island carries no visible create button (the
  hidden item leaves the accessibility tree, as expected), and the current
  tab's link/unlink pair stays visible;
* the same factory builds every other card with the default True — the
  popup is the one and only False consumer.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from PySide6.QtWidgets import QWidget

from app.domain import entity_registry
from app.presentation.views.entity_card_dialog import EntityCardDialog
from app.presentation.views.event_dialog import EventDialog
from app.presentation.wiring import ApplicationWiring
from tests.presentation.qml_helpers import find_item, find_items


class _StubEntityService:
    async def get_all(self):
        return []

    async def get_options(self):
        return []


def _make_wiring() -> ApplicationWiring:
    """The connector with exactly what the related-create path touches."""
    app = SimpleNamespace(
        _image_store=None,
        _theme=None,
        _wire_mentions_for_dialog=lambda dialog, handler: None,
        _wire_ai_buttons=lambda dialog: None,
        _get_entity_service=lambda entity_type: _StubEntityService(),
    )
    return ApplicationWiring(
        app, None, None, None, None, None, None,
        SimpleNamespace(lock=asyncio.Lock()),
    )


async def test_related_create_popup_hides_its_own_create_buttons(qtbot):
    parent = EventDialog(None)
    qtbot.addWidget(parent)
    wiring = _make_wiring()

    await wiring._open_related_create_dialog(parent, "items", "item")
    popup = next(
        d for d in parent.findChildren(EntityCardDialog) if d.isVisible()
    )
    assert popup._entity_type == "item"

    # Every popup section: state False, island paints no «Создать нового».
    assert popup.vm.sections  # item cards do carry relation sections
    assert not any(state.canCreate for state in popup.vm.sections.values())
    for attr in popup.vm.sections:
        hidden = find_items(popup.quick, f"entityRelated_{attr}CreateButton")
        assert hidden, f"no create button under {attr}"
        assert all(bool(i.property("visible")) is False for i in hidden)

    # The pair that works stays, on the currently visible tab.
    first_attr = entity_registry.related_refs_for_key("item")[0].attr
    for suffix in ("LinkButton", "UnlinkButton"):
        pair = find_item(popup.quick, f"entityRelated_{first_attr}{suffix}")
        assert bool(pair.property("visible")) is True

    popup.reject()


async def test_plain_factory_card_keeps_the_create_buttons(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    host.show()
    wiring = _make_wiring()

    dialog = await wiring._open_entity_card(
        "item", parent=host, on_saved=lambda result: None
    )
    qtbot.addWidget(dialog)
    assert dialog.vm.sections
    assert all(state.canCreate for state in dialog.vm.sections.values())
    first_attr = entity_registry.related_refs_for_key("item")[0].attr
    create = find_item(dialog.quick, f"entityRelated_{first_attr}CreateButton")
    assert bool(create.property("visible")) is True
