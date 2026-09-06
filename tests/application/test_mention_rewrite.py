"""Mention rewrite helper and rename hooks on update-with-relations."""
from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock

import pytest
from openpyxl import Workbook

from app.application.services.entity_service import EntityService
from app.application.services.event_service import EventService
from app.application.services.mention_rewrite import rewrite_mentions
from app.application.services.xlsx_import_service import XlsxImportService
from app.infrastructure.db.models import (
    CharacterModel,
    DescriptionModel,
    EventModel,
    LocationModel,
    OrganizationModel,
)
from app.infrastructure.repositories.base_repository import BaseRepository
from app.infrastructure.repositories.character_repository import CharacterRepository
from app.infrastructure.repositories.event_repository import EventRepository
from app.infrastructure.repositories.item_repository import ItemRepository
from app.infrastructure.repositories.location_repository import LocationRepository
from app.infrastructure.repositories.organization_repository import OrganizationRepository

D1 = date(1200, 1, 1)
D2 = date(1200, 12, 31)


async def _svcs(session):
    desc_repo = BaseRepository(session, DescriptionModel)
    char_svc = EntityService(CharacterRepository(session), desc_repo)
    org_svc = EntityService(OrganizationRepository(session), desc_repo)
    loc_svc = EntityService(LocationRepository(session), desc_repo)
    item_svc = EntityService(ItemRepository(session), desc_repo)
    event_svc = EventService(
        EventRepository(session),
        desc_repo,
        org_svc,
        char_svc,
        item_svc,
        loc_svc,
    )
    return char_svc, org_svc, loc_svc, item_svc, event_svc


async def _seed_six_columns(session, target_type: str, target_id: int, display: str):
    marker = f"@[{display}]({target_type}:{target_id})"
    desc = DescriptionModel(
        characteristics=f"{marker} and ( {target_type}:{target_id} )",
        backstory=f"bs {marker}",
    )
    session.add(desc)
    await session.flush()
    char = CharacterModel(
        name="Holder",
        start_date=D1,
        personality=marker,
        tasks=marker,
        music_url=marker,
        description_id=desc.id,
    )
    org = OrganizationModel(name="Org", start_date=D1, tasks=marker, music_url=marker)
    loc = LocationModel(name="Loc", start_date=D1, tasks=marker, music_url=marker)
    session.add_all([char, org, loc])
    await session.flush()
    return desc, char, org, loc, marker


async def test_helper_rewrites_in_session_without_commit(async_session):
    desc = DescriptionModel(characteristics="@[Old](character:1)", backstory="plain")
    async_session.add(desc)
    char = CharacterModel(
        name="A", start_date=D1, personality="@[Old](character:1)", tasks=None,
    )
    org = OrganizationModel(name="O", start_date=D1, tasks="@[Old](character:1)")
    loc = LocationModel(name="L", start_date=D1, tasks="@[Old](character:1)")
    async_session.add_all([char, org, loc])
    await async_session.flush()

    commits = []
    real_commit = async_session.commit

    async def counting_commit():
        commits.append(1)
        return await real_commit()

    async_session.commit = counting_commit
    await rewrite_mentions(async_session, "character", 1, "New")
    assert commits == []
    assert desc.characteristics == "@[New](character:1)"
    assert desc.backstory == "plain"
    assert char.personality == "@[New](character:1)"
    assert org.tasks == "@[New](character:1)"
    assert loc.tasks == "@[New](character:1)"


async def test_rename_entity_rewrites_all_six_columns_same_commit(async_session):
    char_svc, org_svc, loc_svc, item_svc, event_svc = await _svcs(async_session)
    alice_desc = DescriptionModel(characteristics="ch", backstory="bs")
    async_session.add(alice_desc)
    await async_session.flush()
    alice = CharacterModel(name="Alice", start_date=D1, description_id=alice_desc.id)
    async_session.add(alice)
    await async_session.flush()

    desc, holder, org, loc, marker = await _seed_six_columns(
        async_session, "character", alice.id, "Alice",
    )
    await async_session.commit()

    await char_svc.update_entity_with_relations(
        alice.id, {"name": "Alicia"}, "ch", "bs", {},
    )

    await async_session.refresh(desc)
    await async_session.refresh(holder)
    await async_session.refresh(org)
    await async_session.refresh(loc)
    expected = f"@[Alicia](character:{alice.id})"
    assert expected in desc.characteristics
    assert desc.backstory == f"bs {expected}"
    assert holder.personality == expected
    assert holder.tasks == expected
    assert org.tasks == expected
    assert loc.tasks == expected
    assert holder.music_url == marker
    assert org.music_url == marker
    assert loc.music_url == marker
    assert f"( character:{alice.id} )" in desc.characteristics


async def test_rename_event_rewrites_markers_same_commit(async_session):
    char_svc, org_svc, loc_svc, item_svc, event_svc = await _svcs(async_session)
    ev_desc = DescriptionModel(characteristics="ch", backstory="bs")
    async_session.add(ev_desc)
    await async_session.flush()
    ev = EventModel(name="Battle", start_date=D1, end_date=D2, description_id=ev_desc.id)
    async_session.add(ev)
    await async_session.flush()
    desc, holder, org, loc, marker = await _seed_six_columns(
        async_session, "event", ev.id, "Battle",
    )
    await async_session.commit()

    await event_svc.update_event_with_relations(
        ev.id, "War", D1, D2, "ch", "bs", {},
    )
    await async_session.refresh(desc)
    await async_session.refresh(holder)
    expected = f"@[War](event:{ev.id})"
    assert expected in desc.characteristics
    assert holder.personality == expected
    assert org.tasks == expected
    assert loc.tasks == expected
    assert holder.music_url == marker


async def test_same_name_does_not_call_rewrite(async_session, monkeypatch):
    import app.application.services.entity_service as es_mod
    import app.application.services.event_service as ev_mod

    spy = AsyncMock()
    monkeypatch.setattr(es_mod, "rewrite_mentions", spy)
    monkeypatch.setattr(ev_mod, "rewrite_mentions", spy)

    char_svc, org_svc, loc_svc, item_svc, event_svc = await _svcs(async_session)
    alice_desc = DescriptionModel(characteristics="ch", backstory="bs")
    async_session.add(alice_desc)
    await async_session.flush()
    alice = CharacterModel(name="Alice", start_date=D1, description_id=alice_desc.id)
    ev_desc = DescriptionModel(characteristics="ch", backstory="bs")
    async_session.add(ev_desc)
    await async_session.flush()
    ev = EventModel(name="Battle", start_date=D1, end_date=D2, description_id=ev_desc.id)
    async_session.add_all([alice, ev])
    await async_session.flush()
    desc, holder, org, loc, marker = await _seed_six_columns(
        async_session, "character", alice.id, "Alice",
    )
    like_junk = f"see (character:{alice.id}) not a marker"
    desc.characteristics = like_junk
    await async_session.commit()

    await char_svc.update_entity_with_relations(
        alice.id, {"name": "Alice"}, "ch", "bs", {},
    )
    await event_svc.update_event_with_relations(
        ev.id, "Battle", D1, D2, "ch", "bs", {},
    )
    spy.assert_not_called()
    await async_session.refresh(desc)
    await async_session.refresh(holder)
    assert desc.characteristics == like_junk
    assert holder.personality == marker


async def test_commit_failure_rolls_back_markers(async_session, monkeypatch):
    char_svc, *_ = await _svcs(async_session)
    alice_desc = DescriptionModel(characteristics="ch", backstory="bs")
    async_session.add(alice_desc)
    await async_session.flush()
    alice = CharacterModel(name="Alice", start_date=D1, description_id=alice_desc.id)
    async_session.add(alice)
    await async_session.flush()
    desc, holder, org, loc, marker = await _seed_six_columns(
        async_session, "character", alice.id, "Alice",
    )
    await async_session.commit()

    async def boom():
        raise RuntimeError("commit failed")

    monkeypatch.setattr(async_session, "commit", boom)
    with pytest.raises(RuntimeError, match="commit failed"):
        await char_svc.update_entity_with_relations(
            alice.id, {"name": "Alicia"}, "ch", "bs", {},
        )

    await async_session.refresh(alice)
    await async_session.refresh(holder)
    assert alice.name == "Alice"
    assert holder.personality == marker


async def test_create_and_xlsx_do_not_rewrite(async_session, tmp_path, monkeypatch):
    import app.application.services.entity_service as es_mod
    import app.application.services.event_service as ev_mod

    spy = AsyncMock()
    monkeypatch.setattr(es_mod, "rewrite_mentions", spy)
    monkeypatch.setattr(ev_mod, "rewrite_mentions", spy)

    char_svc, org_svc, loc_svc, item_svc, event_svc = await _svcs(async_session)
    alice_desc = DescriptionModel(characteristics="ch", backstory="bs")
    async_session.add(alice_desc)
    await async_session.flush()
    alice = CharacterModel(name="Alice", start_date=D1, description_id=alice_desc.id)
    async_session.add(alice)
    await async_session.flush()
    desc, holder, org, loc, marker = await _seed_six_columns(
        async_session, "character", alice.id, "Alice",
    )
    await async_session.commit()

    await char_svc.create_entity("Bob", "c", "b", D1, D2)
    await event_svc.create_event_with_relations("Skirmish", D1, D2, "c", "b", {})

    wb = Workbook()
    ws = wb.active
    ws.append(["name", "start_date", "end_date", "characteristics", "backstory"])
    ws.append(["Imported", D1, D2, "c", "b"])
    path = tmp_path / "in.xlsx"
    wb.save(path)
    xlsx = XlsxImportService(event_svc, char_svc, loc_svc, org_svc, item_svc)
    result = await xlsx.import_file("character", path)
    assert result.created == 1
    spy.assert_not_called()
    await async_session.refresh(holder)
    assert holder.personality == marker
