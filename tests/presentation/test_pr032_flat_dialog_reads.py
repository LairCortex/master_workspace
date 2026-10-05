"""PR-032 red pins — the event-dialog island survives a failed save.

Mechanism (docs/qa/test-plan-2026-10-03.md «### PR-032»): a save that fails
ends in the unit of work rolling the shared session back, and a
``Session.rollback()`` expires EVERY instance the session holds — even under
the app's ``expire_on_commit=False``. The dialog's island ViewModel had kept
the ORM rows handed over by the connector RAW, and its QML-facing properties
re-read the lazy ``name``/``color_index``/``parent_id`` attributes through
the typeNames/parentNames/rows lambdas. An expired attribute read from the
Qt side tries to emit SQL without a greenlet: every metacall dumped a
``sqlalchemy.exc.MissingGreenlet`` traceback into stderr (the live storm:
14 hits per session) and delivered nothing — the «Тип» list of the open
dialog stayed empty.

Each pin replays the exact sequence offscreen on the real in-memory schema:
load rows through a real service, hand them to the dialog surface the way
the connector does, let a later save FAIL the way GameSessionUoW fails one
(flush + rollback), then re-read the property exactly as the QML metacall
does. Before the fix the read raises MissingGreenlet; after the fix the
ViewModel keeps flat frozen options (domain/options.py), the reads are pure
memory, the storm class is gone and the lists keep their content.
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.exc import MissingGreenlet

from app.application.services.entity_service import EntityService
from app.application.services.event_service import EventService
from app.domain.options import EntityOption, EventTypeOption
from app.infrastructure.db.models import (
    DescriptionModel,
    EventModel,
    EventTypeModel,
)
from app.infrastructure.repositories.base_repository import BaseRepository
from app.infrastructure.repositories.character_repository import CharacterRepository
from app.infrastructure.repositories.event_repository import EventRepository
from app.infrastructure.repositories.event_type_repository import EventTypeRepository
from app.infrastructure.repositories.item_repository import ItemRepository
from app.infrastructure.repositories.location_repository import LocationRepository
from app.infrastructure.repositories.organization_repository import OrganizationRepository
from app.presentation.viewmodels.event_dialog_island_view_model import (
    EventDialogIslandViewModel,
)

D1 = date(1200, 1, 1)
D2 = date(1200, 12, 31)


async def _make_event_service(session) -> EventService:
    desc_repo = BaseRepository(session, DescriptionModel)
    return EventService(
        event_repo=EventRepository(session),
        description_repo=desc_repo,
        organization_service=EntityService(OrganizationRepository(session), desc_repo),
        character_service=EntityService(CharacterRepository(session), desc_repo),
        item_service=EntityService(ItemRepository(session), desc_repo),
        location_service=EntityService(LocationRepository(session), desc_repo),
        event_type_repo=EventTypeRepository(session),
    )


async def _make_org_service(session) -> EntityService:
    return EntityService(OrganizationRepository(session),
                         BaseRepository(session, DescriptionModel))


async def _failed_save(session) -> None:
    """The shape of a failing user save: work reaches the flush, the unit of
    work rolls back (PR-032: this is what expires the whole identity map)."""
    session.add(EventTypeModel(name="Обречённый тип", color_index=1, sort_order=99))
    await session.flush()
    await session.rollback()


async def _seed_types(session) -> None:
    session.add_all([
        EventTypeModel(name="Сюжет", color_index=1, sort_order=0),
        EventTypeModel(name="Слух", color_index=3, sort_order=1),
    ])
    await session.commit()


async def _seed_events(session) -> tuple[EventModel, EventModel]:
    desc = DescriptionModel(characteristics="ev", backstory="ev")
    session.add(desc)
    await session.flush()
    main = EventModel(name="Поход", description_id=desc.id,
                      start_date=D1, end_date=D2)
    session.add(main)
    await session.flush()
    child = EventModel(name="Совет", description_id=desc.id,
                       start_date=D1, end_date=D2, parent_id=main.id)
    session.add(child)
    await session.commit()
    return main, child


async def test_type_names_survive_a_failed_save(async_session):
    """The PR-032 storm itself: «Тип» stays filled and silent after rollback."""
    service = await _make_event_service(async_session)
    await _seed_types(async_session)

    vm = EventDialogIslandViewModel()
    vm.set_event_types(list(await service.get_event_types()))
    assert list(vm.typeNames) == ["Без типа", "Сюжет", "Слух"]
    vm.selectType(2)
    assert vm.selectedColorIndex == 3
    assert vm.selected_type_id == 2

    await _failed_save(async_session)

    # The metacall the storm died in (EventDialogRoot.qml:211 → typeNames).
    assert list(vm.typeNames) == ["Без типа", "Сюжет", "Слух"]
    assert vm.selectedColorIndex == 3
    assert vm.selected_type_id == 2


async def test_type_option_handed_over_becomes_a_plain_value(async_session):
    """The dialog stores NO ORM object: whatever arrives, the VM caches flat
    frozen options, so no later rollback can reach a lazy attribute through
    the property lambdas (the layer rule: presentation stores plain data)."""
    service = await _make_event_service(async_session)
    await _seed_types(async_session)
    rows = list(await service.get_event_types())

    vm = EventDialogIslandViewModel()
    vm.set_event_types(rows)
    assert all(isinstance(item, EventTypeOption) for item in vm._types)
    assert not any(item in rows for item in vm._types)


async def test_parent_names_survive_a_failed_save(async_session):
    """«Родительское событие» (the same storm class, NRI-0023 surface)."""
    service = await _make_event_service(async_session)
    main, _child = await _seed_events(async_session)

    vm = EventDialogIslandViewModel()
    vm.set_parent_options(list(await service.get_all_events()), exclude_id=None)
    assert list(vm.parentNames) == ["—", "Поход"]
    main_id = main.id  # plain value taken while the row is still loaded
    vm.parent_id = main_id
    assert vm.selectedParentIndex == 1

    await _failed_save(async_session)

    assert list(vm.parentNames) == ["—", "Поход"]
    assert vm.selectedParentIndex == 1
    vm.selectParent(1)
    assert vm.parent_id == main_id


async def test_section_rows_survive_a_failed_save(async_session):
    """RelatedSectionState (shared by the event dialog and the entity card):
    the section rows and the picker candidates must stay readable, too."""
    org_service = await _make_org_service(async_session)
    org = await org_service.create_entity(
        name="Гильдия", characteristics="ch", backstory="bs",
        start_date=D1, end_date=None,
    )
    other = await org_service.create_entity(
        name="Башня", characteristics="ch", backstory="bs",
        start_date=D1, end_date=None,
    )

    vm = EventDialogIslandViewModel()
    vm.organizations.set_entities([org])
    vm.organizations.set_available([org, other])
    assert vm.organizations.rows == [{"id": org.id, "name": "Гильдия"}]
    assert [c.name for c in vm.organizations.candidates()] == ["Башня"]

    await _failed_save(async_session)

    assert vm.organizations.rows == [{"id": org.id, "name": "Гильдия"}]
    assert [c.name for c in vm.organizations.candidates()] == ["Башня"]
    assert all(isinstance(item, EntityOption) for item in vm.organizations._entities)
    vm.organizations.add_entity(org)  # a re-link of the same row stays a no-op
    assert vm.organizations.get_current_ids() == [org.id]


async def test_missing_greenlet_is_the_red_mechanism(async_session):
    """The pin proves the storm's mechanism itself against the real session:
    an ORM row read after the failed-save rollback DOES raise MissingGreenlet
    outside the greenlet — so the flat copy above is what removes the failure,
    not a swallowed exception. (This assertion stays green in both states: it
    documents the hazard the dialog must never expose.)"""
    service = await _make_event_service(async_session)
    await _seed_types(async_session)
    row = (await service.get_event_types())[0]
    await _failed_save(async_session)
    with pytest.raises(MissingGreenlet):
        _ = row.name
