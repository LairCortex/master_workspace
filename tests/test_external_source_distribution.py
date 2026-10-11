"""The generic external-source mechanism in the kernel (add-dnd-game-face,
tasks 2.1/2.2, design Д1/Д2).

The kernel side of the seam, pinned without any D&D logic: the composition
root reads ``external_sources`` off the composed game-system module, registers
their type descriptors through the one ``register_external`` door and hands
the list to the three long-lived collaborators (the search service, the
connector, the preview column) — the connector then carries it to every dialog
it builds, and the dialogs pass it down to every mention host. A module with
no sources changes nothing: every collaborator keeps the empty tuple, which is
the byte-for-byte pre-change state (the zero-registrations themselves are
pinned in ``tests/test_dd_module_profile.py``; the composition below proves the
NON-empty path is wired end to end with a fake source — the real D&D sources
arrive in group 3+).
"""
from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QDialog

from app.application.services.search_service import SearchService
from app.domain import entity_registry as reg
from app.domain.enums.entity_type import EntityType
from app.main import DD_MODULE_PROFILE_DISABLE_ENV, Application
from app.presentation.viewmodels.entity_preview_view_model import (
    EntityPreviewViewModel,
)
from app.presentation.viewmodels.mention_field_host import MentionFieldHost
from app.presentation.views.calendar_wizard import CalendarWizardDialog
from app.presentation.views.entity_card_dialog import EntityCardDialog
from app.presentation.views.event_dialog import EventDialog
from app.presentation.wiring import ApplicationWiring
from tests.test_application_settings_errors import _install_modal_trap


@pytest.fixture(autouse=True)
def autoaccept_calendar_wizard(monkeypatch):
    """Freshly seeded games open the wizard inside ``start()``; offscreen must
    not block on a real modal loop (local copy of the profile-test convention).
    """
    monkeypatch.setattr(
        CalendarWizardDialog,
        "exec",
        lambda self, *args: QDialog.DialogCode.Rejected,
    )


@pytest.fixture(autouse=True)
def restore_external_section():
    """The registry's external section is process state; hand every test back
    the kernel-only shape it found (same discipline as the registry tests)."""
    saved = dict(reg._EXTERNAL)
    yield
    reg._EXTERNAL.clear()
    reg._EXTERNAL.update(saved)


def _spell() -> reg.ExternalTypeDescriptor:
    return reg.ExternalTypeDescriptor(
        key="spell", label="Заклинание", plural_label="Заклинания",
        icon_key="sparkles",
    )


def _race() -> reg.ExternalTypeDescriptor:
    return reg.ExternalTypeDescriptor(
        key="race", label="Раса", plural_label="Расы", icon_key="paw-print",
        searchable=False,
    )


class _FakeSource:
    """A duck of the ExternalEntitySource protocol — only the registration
    face (type_descriptors) matters to the mechanism under test."""

    def __init__(self, descriptors):
        self.type_descriptors = tuple(descriptors)

    @property
    def visible(self) -> bool:
        return True

    # протокольные двери rest of the surfaces (task 6.2 warm-up runs at the
    # composition's restore_preview_pins); this test only registers, but the
    # startup pass touches warm on every source
    async def warm(self) -> None:
        return None


class _FakeModule:
    """A duck of GameSystemModule contributing sources while attached; the
    composition calls only attach/detach/enabled/external_sources on it."""

    def __init__(self, sources):
        self._sources = tuple(sources)
        self.attached_with: tuple | None = None
        self.detached = False

    @property
    def enabled(self) -> bool:
        return self.attached_with is not None

    @property
    def external_sources(self):
        return self._sources

    def attach(self, main_window, wiring) -> None:
        self.attached_with = (main_window, wiring)

    def detach(self) -> None:
        self.detached = True
        self.attached_with = None


# ── the collaborators store and re-hand the list (design Д1) ───────────────


def test_search_service_stores_rehands_and_defaults_empty():
    """The service is inert until group 3.4 consults it — but the hand-out
    face is already the final one: constructor default empty, property reads
    the current tuple, the setter re-hands for a live-joined module."""
    service = SearchService(
        event=None, organization=None, character=None, item=None, location=None,
    )
    assert service.external_sources == ()
    source = _FakeSource([_spell()])
    SearchService(
        event=None, organization=None, character=None, item=None,
        location=None, external_sources=[source],
    )
    service.set_external_sources([source])
    assert service.external_sources == (source,)
    service.set_external_sources(())
    assert service.external_sources == ()


def test_mention_field_host_defaults_empty_and_carries_the_sources():
    """The host stores the list whole (the @-popup consults it in group 5);
    with no sources the host is the pre-change host."""
    plain = MentionFieldHost()
    assert plain.external_sources == ()
    source = _FakeSource([_spell()])
    host = MentionFieldHost(external_sources=[source])
    assert host.external_sources == (source,)


def test_preview_view_model_stores_and_rehands():
    """The preview column's VM: constructor default empty, in-place re-hand
    for the live-enable path (frames rebuild from the fresh list in group 6;
    no frames means no signal — the setter is silent state)."""
    vm = EntityPreviewViewModel()
    assert vm.external_sources == ()
    source = _FakeSource([_spell()])
    vm.set_external_sources([source])
    assert vm.external_sources == (source,)
    vm.set_external_sources(())
    assert vm.external_sources == ()


def _duck_wiring(**over) -> ApplicationWiring:
    """The connector with exactly what the accessors touch (the duck pattern
    of the preview-slot wiring tests)."""
    return ApplicationWiring(
        SimpleNamespace(_image_store=None),
        SimpleNamespace(),
        None, None, None, None, None,
        SimpleNamespace(lock=asyncio.Lock()),
        **over,
    )


def test_wiring_carries_the_sources_and_rehands_in_place():
    """The connector is the carrier to the dialogs it builds; the setter is
    the live-enable channel — after it, every dialog opening reads the CURRENT
    list (no rebuilt connector), pinned by the composition test below."""
    wiring = _duck_wiring()
    assert wiring.external_sources == ()
    source = _FakeSource([_spell()])
    _duck_wiring(external_sources=[source])
    wiring.set_external_sources([source])
    assert wiring.external_sources == (source,)


def test_dialogs_pass_the_sources_to_every_mention_host(qtbot):
    """Both dialog facades forward the list down to their island VMs, and the
    VMs to EVERY MentionFieldHost — no field silently loses the seam."""
    source = _FakeSource([_spell()])

    card = EntityCardDialog(None, "character", external_sources=[source])
    qtbot.addWidget(card)
    assert card.vm._hosts["characteristics"].external_sources == (source,)
    assert card.vm._hosts["backstory"].external_sources == (source,)

    event = EventDialog(SimpleNamespace(), external_sources=[source])
    qtbot.addWidget(event)
    assert event.vm.characteristicsHost.external_sources == (source,)
    assert event.vm.backstoryHost.external_sources == (source,)

    # without sources both dialogs keep the pre-change, empty-handed hosts
    plain_card = EntityCardDialog(None, "character")
    qtbot.addWidget(plain_card)
    assert plain_card.vm._hosts["characteristics"].external_sources == ()
    plain_event = EventDialog(SimpleNamespace())
    qtbot.addWidget(plain_event)
    assert plain_event.vm.characteristicsHost.external_sources == ()


# ── the composition registers and distributes (task 2.2) ────────────────────


def _make_game_db(tmp_path) -> sqlite3.Connection:
    db_path = tmp_path / "game" / "game.db"
    db_path.parent.mkdir(parents=True)
    (db_path.parent / "images").mkdir()
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE game_settings "
            "(key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '')"
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


async def test_composition_registers_and_distributes_the_module_sources(
    qapp, tmp_path, monkeypatch
):
    """The non-empty path end to end: a module contributing two sources makes
    the open game register their descriptors (registry union, kernel-first)
    and hand the list to the search service, the connector and the preview
    column; closing the game resets the registry section and the hand-out."""
    monkeypatch.delenv(DD_MODULE_PROFILE_DISABLE_ENV, raising=False)
    spell, race = _spell(), _race()
    source = _FakeSource([spell, race])
    module = _FakeModule([source])
    monkeypatch.setattr(
        "app.main._compose_game_system_module",
        lambda flag, uow=None, **kw: (module, None),
    )
    _install_modal_trap(monkeypatch)

    db_path = _make_game_db(tmp_path)
    application = Application(qapp)
    window = await application.start(str(db_path))
    try:
        # the registry learned the types through the one door, in order
        assert reg.external_types() == (spell, race)
        assert reg.resolve("spell") is spell
        assert reg.resolve("character") is EntityType.CHARACTER
        # the search union: kernel first, searchable externals in order
        assert reg.search_types() == reg.SEARCH_TYPES + (spell,)
        # the hand-out: all three long-lived collaborators hold the sources
        assert application._external_sources == (source,)
        assert application._search_service.external_sources == (source,)
        assert application._wiring.external_sources == (source,)
        assert window.entity_preview.vm.external_sources == (source,)
        assert module.attached_with is not None
    finally:
        window.close()
        await application.shutdown()
    # the section and the hand-out leave with the game (no stale types)
    assert reg.external_types() == ()
    assert application._external_sources == ()


async def test_wiring_factory_builds_a_card_with_the_current_sources(
    qapp, qtbot
):
    """The connector builds each card from the CURRENT list — the exact
    mechanism that makes the live-enable setter enough (no rebuilt connector):
    set the list, and the very next card of the factory carries it."""
    spell = _spell()
    source = _FakeSource([spell])
    wiring = _duck_wiring()
    # the factory's mention/AI ceremony reaches into the app helpers — give
    # the duck the two no-op doors it calls (the card itself is genuine QML)
    wiring._app._theme = None
    wiring._app._wire_mentions_for_dialog = lambda dialog, on_click: None
    wiring._app._wire_ai_buttons = lambda dialog: None
    wiring.set_external_sources([source])
    dialog = await wiring._open_entity_card(
        "character", parent=None, on_saved=lambda result: None,
        load_available=False,
    )
    qtbot.addWidget(dialog)
    assert dialog.vm._hosts["characteristics"].external_sources == (source,)
    assert dialog.vm._hosts["backstory"].external_sources == (source,)
