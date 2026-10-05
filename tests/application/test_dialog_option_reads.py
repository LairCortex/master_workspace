"""PR-032 layer-boundary pins: the dialog-list reads are FLAT and survive a
session rollback (application returns frozen dataclasses, not ORM rows).

The event/entity dialogs used to receive the connector's raw ORM rows
(get_event_types/get_all_events/get_all) and keep them alive in viewmodels —
after a failed save (uow rollback) every held row is expired and the next QML
metacall of typeNames/parentNames/rows reads an expired lazy attribute
outside the greenlet (docs/qa/test-plan-2026-10-03.md «### PR-032»). The fix
moves the projection into the application layer: the services answer these
three dialog needs with plain frozen options (domain/options.py), built
while the rows are still loaded. These pins freeze that contract — values,
order, frozenness — and prove the returned objects need no session at all:
every attribute read still answers after the exact failed-save rollback that
expired the identity map underneath.
"""
from __future__ import annotations

from dataclasses import is_dataclass
from datetime import date

from app.application.services.entity_service import EntityService
from app.application.services.event_service import EventService
from app.domain.options import EntityOption, EventOption, EventTypeOption
from app.infrastructure.db.models import DescriptionModel, EventModel, EventTypeModel
from app.infrastructure.repositories.base_repository import BaseRepository
from app.infrastructure.repositories.character_repository import CharacterRepository
from app.infrastructure.repositories.event_repository import EventRepository
from app.infrastructure.repositories.event_type_repository import EventTypeRepository
from app.infrastructure.repositories.item_repository import ItemRepository
from app.infrastructure.repositories.location_repository import LocationRepository
from app.infrastructure.repositories.organization_repository import OrganizationRepository

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
    """flush + rollback — the GameSessionUoW failure shape that expires the
    whole identity map (the PR-032 storm's trigger)."""
    session.add(EventTypeModel(name="Обречённый", color_index=1, sort_order=99))
    await session.flush()
    await session.rollback()


async def test_event_type_options_are_flat_ordered_and_session_free(async_session):
    service = await _make_event_service(async_session)
    async_session.add_all([
        EventTypeModel(name="Слух", color_index=3, sort_order=1),
        EventTypeModel(name="Сюжет", color_index=1, sort_order=0),
    ])
    await async_session.commit()

    options = await service.get_event_type_options()
    assert options == [
        EventTypeOption(id=options[0].id, name="Сюжет", color_index=1),
        EventTypeOption(id=options[1].id, name="Слух", color_index=3),
    ]
    assert all(is_dataclass(option) for option in options)

    await _failed_save(async_session)
    # The expired identity map can no longer reach these values.
    assert [option.name for option in options] == ["Сюжет", "Слух"]
    assert [option.color_index for option in options] == [1, 3]


async def test_parent_options_cover_every_event_with_its_link(async_session):
    """The «Родительское событие» pool arrives flat; the main-only filtering
    stays the ViewModel's read-time rule (spec «Чужих детей в списке нет»)."""
    service = await _make_event_service(async_session)
    desc = DescriptionModel(characteristics="ev", backstory="ev")
    async_session.add(desc)
    await async_session.flush()
    main = EventModel(name="Поход", description_id=desc.id,
                      start_date=D1, end_date=D2)
    async_session.add(main)
    await async_session.flush()
    async_session.add(EventModel(name="Совет", description_id=desc.id,
                                 start_date=D1, end_date=D2, parent_id=main.id))
    await async_session.commit()

    options = await service.get_parent_options()
    by_name = {option.name: option for option in options}
    assert set(by_name) == {"Поход", "Совет"}
    assert by_name["Поход"].parent_id is None
    assert by_name["Совет"].parent_id == by_name["Поход"].id
    assert all(isinstance(option, EventOption) for option in options)

    await _failed_save(async_session)
    assert by_name["Совет"].name == "Совет"
    assert by_name["Совет"].parent_id == by_name["Поход"].id


async def test_entity_options_carry_id_and_name_without_the_row(async_session):
    service = await _make_org_service(async_session)
    org = await service.create_entity(
        name="Гильдия", characteristics="ch", backstory="bs",
        start_date=D1, end_date=None,
    )
    await async_session.commit()

    org_id = org.id  # plain value taken while the row is still loaded
    options = await service.get_options()
    assert options == [EntityOption(id=org_id, name="Гильдия")]

    await _failed_save(async_session)
    assert options[0].name == "Гильдия"
    assert options[0].id == org_id
