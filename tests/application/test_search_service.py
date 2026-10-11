"""Characterization tests for SearchService against a real in-memory DB.

Pins current behavior: search by name / characteristics / backstory across
all 5 entity types, case-insensitivity (ASCII + unicode via registered
SQLite lower()), de-duplication, and search_names() result shape.
"""
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.search_service import SearchService
from app.domain import entity_registry
from app.infrastructure.db.models import (
    CharacterModel,
    DescriptionModel,
    EventModel,
    ItemModel,
    LocationModel,
    OrganizationModel,
)
from app.infrastructure.repositories.character_repository import CharacterRepository
from app.infrastructure.repositories.event_repository import EventRepository
from app.infrastructure.repositories.item_repository import ItemRepository
from app.infrastructure.repositories.location_repository import LocationRepository
from app.infrastructure.repositories.organization_repository import OrganizationRepository


async def _add(session: AsyncSession, model, name: str, **kw):
    """Insert an entity with an optional shared description row."""
    desc_id = None
    characteristics = kw.pop("characteristics", None)
    backstory = kw.pop("backstory", None)
    if characteristics is not None or backstory is not None:
        desc = DescriptionModel(characteristics=characteristics, backstory=backstory)
        session.add(desc)
        await session.flush()
        desc_id = desc.id
    obj = model(
        name=name,
        start_date=date(1200, 1, 1),
        description_id=desc_id,
        end_date=kw.pop("end_date", None),
    )
    session.add(obj)
    await session.flush()
    return obj


def _make_service(session: AsyncSession) -> SearchService:
    return SearchService(
        event=EventRepository(session),
        organization=OrganizationRepository(session),
        character=CharacterRepository(session),
        item=ItemRepository(session),
        location=LocationRepository(session),
    )


class _Db:
    """Fixtured fixture data: one row per entity type."""

    async def setup(self, session: AsyncSession) -> None:
        self.event = await _add(
            session, EventModel, "Siege of the Capital",
            characteristics="Great battle", backstory="Ancient feud",
        )
        self.org = await _add(
            session, OrganizationModel, "Orda",
            characteristics="Military power", backstory="Dark alliance",
        )
        self.char = await _add(
            session, CharacterModel, "Arthas",
            characteristics="Dark knight", backstory="Fallen prince",
        )
        self.item = await _add(
            session, ItemModel, "Sword",
            characteristics="Steel blade", backstory="Forged long ago",
        )
        self.loc = await _add(session, LocationModel, "Стормград")
        # Entity without any description row (outerjoin null-safety)
        self.descless = await _add(session, OrganizationModel, "Lonely Guild")


class TestSearchAll:
    async def test_search_by_name(self, async_session):
        await _Db().setup(async_session)
        svc = _make_service(async_session)
        results = await svc.search_all("siege")
        assert [e.name for e in results["events"]] == ["Siege of the Capital"]
        assert results["organizations"] == []
        assert results["characters"] == []
        assert results["items"] == []
        assert results["locations"] == []

    async def test_search_by_characteristics(self, async_session):
        await _Db().setup(async_session)
        svc = _make_service(async_session)
        results = await svc.search_all("dark knight")
        assert [c.name for c in results["characters"]] == ["Arthas"]
        assert results["events"] == []
        assert results["organizations"] == []

    async def test_search_by_backstory(self, async_session):
        await _Db().setup(async_session)
        svc = _make_service(async_session)
        results = await svc.search_all("ancient feud")
        assert [e.name for e in results["events"]] == ["Siege of the Capital"]
        assert results["organizations"] == []

    async def test_search_case_insensitive_ascii(self, async_session):
        await _Db().setup(async_session)
        svc = _make_service(async_session)
        results = await svc.search_all("ORDA")
        assert [o.name for o in results["organizations"]] == ["Orda"]
        results = await svc.search_all("sWORD")
        assert [i.name for i in results["items"]] == ["Sword"]

    async def test_search_case_insensitive_unicode(self, async_session):
        await _Db().setup(async_session)
        svc = _make_service(async_session)
        results = await svc.search_all("стормград")
        assert [loc.name for loc in results["locations"]] == ["Стормград"]

    async def test_search_entity_without_description(self, async_session):
        await _Db().setup(async_session)
        svc = _make_service(async_session)
        results = await svc.search_all("lonely guild")
        assert [o.name for o in results["organizations"]] == ["Lonely Guild"]

    async def test_search_no_match(self, async_session):
        await _Db().setup(async_session)
        svc = _make_service(async_session)
        results = await svc.search_all("zzz-no-such-thing")
        for key, value in results.items():
            assert value == [], key

    async def test_search_no_duplicates_when_name_and_text_match(self, async_session):
        await _add(
            async_session, CharacterModel, "Phoenix Blade",
            characteristics="Phoenix blade relic",
        )
        svc = _make_service(async_session)
        # Matches by name AND characteristics — must appear exactly once.
        results = await svc.search_all("phoenix")
        names = [c.name for c in results["characters"]]
        assert names.count("Phoenix Blade") == 1


class TestSearchNames:
    async def test_returns_type_id_name_dicts(self, async_session):
        await _add(async_session, EventModel, "Arthas Appears")
        await _add(async_session, CharacterModel, "Arthas Menethil")
        await _add(async_session, OrganizationModel, "Menethil Court")
        svc = _make_service(async_session)
        results = await svc.search_names("arthas")
        by_type = {r["type"]: r for r in results}
        assert by_type["event"]["name"] == "Arthas Appears"
        assert by_type["character"]["name"] == "Arthas Menethil"
        assert isinstance(by_type["event"]["id"], int)
        assert isinstance(by_type["character"]["id"], int)
        assert "organization" not in by_type

    async def test_returns_all_six_type_strings(self, async_session):
        await _add(async_session, EventModel, "Probe")
        await _add(async_session, OrganizationModel, "Probe Guild")
        await _add(async_session, CharacterModel, "Probe Hero")
        await _add(async_session, ItemModel, "Probe Sword")
        await _add(async_session, LocationModel, "Probe City")
        svc = _make_service(async_session)
        results = await svc.search_names("probe")
        types = sorted(r["type"] for r in results)
        assert types == ["character", "event", "item", "location", "organization"]
        for r in results:
            assert set(r) == {"type", "id", "name"}

    async def test_empty_query_result(self, async_session):
        await _Db().setup(async_session)
        svc = _make_service(async_session)
        assert await svc.search_names("zzz-no-such-name") == []


# ── add-dnd-game-face task 3.4: the external half of search_all ─────────────

_KERNEL_KEYS = {"events", "organizations", "characters", "items", "locations"}


class _ExternalHit:
    def __init__(self, key, source_id, name, origin=""):
        self.key = key
        self.source_id = source_id
        self.name = name
        self.origin = origin


class _ExternalSource:
    """Duck of ``ExternalEntitySource.search``/``mention_candidates``/
    ``visible``: records that a hidden source is never asked."""

    def __init__(self, hits, visible=True, mentions=None):
        self._hits = hits
        self._mentions = hits if mentions is None else mentions
        self.visible = visible
        self.queries = []
        self.mention_queries = []

    async def search(self, query):
        self.queries.append(query)
        return [h for h in self._hits if query.lower() in h.name.lower()]

    async def mention_candidates(self, query):
        self.mention_queries.append(query)
        return [h for h in self._mentions if query.lower() in h.name.lower()]


@pytest.fixture()
def restore_external_section():
    """The registry's external section is process state (same discipline as
    tests/test_external_source_distribution.py)."""
    saved = dict(entity_registry._EXTERNAL)
    yield
    entity_registry._EXTERNAL.clear()
    entity_registry._EXTERNAL.update(saved)


def _descriptor(key, **kw):
    return entity_registry.ExternalTypeDescriptor(
        key=key, label=key, plural_label=key, icon_key="book", **kw
    )


class TestExternalSearchPass:
    async def test_groups_follow_registry_order_after_kernel(
        self, async_session, restore_external_section
    ):
        """Spec «записи… участвуют в том же проходе после типов ядра»: groups
        are appended under their keys in the REGISTRY's external order — not
        the order the source emitted them — after all kernel keys."""
        entity_registry.register_external(
            [_descriptor("dd_spell"), _descriptor("dd_feat")]
        )
        source = _ExternalSource(
            [
                _ExternalHit("dd_feat", "pack/lucky", "Lucky"),
                _ExternalHit("dd_spell", "srd/fire-ball", "Fire ball"),
            ]
        )
        service = SearchService(
            event=EventRepository(async_session),
            organization=OrganizationRepository(async_session),
            character=CharacterRepository(async_session),
            item=ItemRepository(async_session),
            location=LocationRepository(async_session),
            external_sources=(source,),
        )
        results = await service.search_all("")
        keys = list(results)
        assert keys[:5] == ["events", "organizations", "characters", "items", "locations"]
        assert keys[5:] == ["dd_spell", "dd_feat"]  # registry order, not hit order
        assert [h.source_id for h in results["dd_spell"]] == ["srd/fire-ball"]
        assert [h.source_id for h in results["dd_feat"]] == ["pack/lucky"]

    async def test_invisible_source_is_never_asked(
        self, async_session, restore_external_section
    ):
        """Visibility is the SOURCE's own condition (spec «условия видимости…
        задаётся самим источником»): a hidden source is skipped outright —
        not even consulted, no group, empty or not."""
        entity_registry.register_external([_descriptor("dd_feat")])
        hidden = _ExternalSource([_ExternalHit("dd_feat", "p/l", "Lucky")], visible=False)
        service = SearchService(
            event=EventRepository(async_session),
            organization=OrganizationRepository(async_session),
            character=CharacterRepository(async_session),
            item=ItemRepository(async_session),
            location=LocationRepository(async_session),
            external_sources=(hidden,),
        )
        results = await service.search_all("lucky")
        assert hidden.queries == []
        assert "dd_feat" not in results

    async def test_unregistered_and_unsearchable_keys_are_dropped(
        self, async_session, restore_external_section
    ):
        """The registry is the single signature source: a hit under a key it
        does not know, or under a registered but non-searchable key, earns no
        group; healthy keys of the same source still pass."""
        entity_registry.register_external(
            [_descriptor("dd_feat"), _descriptor("dd_hidden", searchable=False)]
        )
        source = _ExternalSource(
            [
                _ExternalHit("bogus", "x", "Bogus"),
                _ExternalHit("dd_hidden", "h", "Hidden kind"),
                _ExternalHit("dd_feat", "p/l", "Lucky"),
            ]
        )
        service = SearchService(
            event=EventRepository(async_session),
            organization=OrganizationRepository(async_session),
            character=CharacterRepository(async_session),
            item=ItemRepository(async_session),
            location=LocationRepository(async_session),
            external_sources=(source,),
        )
        results = await service.search_all("")
        assert [k for k in results if k not in _KERNEL_KEYS] == ["dd_feat"]

    async def test_two_sources_same_key_concatenate_in_source_order(
        self, async_session, restore_external_section
    ):
        """Same key, two sources (two games' worth of packs in one pass):
        hits concatenate in source order — the kernel never interleaves."""
        entity_registry.register_external([_descriptor("dd_feat")])
        first = _ExternalSource([_ExternalHit("dd_feat", "a/l", "Lucky")])
        second = _ExternalSource([_ExternalHit("dd_feat", "b/l", "Lucky")])
        service = SearchService(
            event=EventRepository(async_session),
            organization=OrganizationRepository(async_session),
            character=CharacterRepository(async_session),
            item=ItemRepository(async_session),
            location=LocationRepository(async_session),
            external_sources=(first, second),
        )
        results = await service.search_all("lucky")
        assert [h.source_id for h in results["dd_feat"]] == ["a/l", "b/l"]


# ── add-dnd-game-face task 5.2: the external half of the @-candidates ───────


def _mention_service(session, sources):
    return SearchService(
        event=EventRepository(session),
        organization=OrganizationRepository(session),
        character=CharacterRepository(session),
        item=ItemRepository(session),
        location=LocationRepository(session),
        external_sources=sources,
    )


class TestExternalMentionCandidates:
    async def test_external_rows_ride_after_the_kernel_half(
        self, async_session, restore_external_section
    ):
        """Spec mentions «кандидаты… из зарегистрированных источников» +
        design Д4: the kernel rows keep their exact {type, id, name} shape
        first, the external rows append behind them with the source's STRING
        id whole (never a numeric surrogate) and the ``origin`` sign; a same-
        named pair from two sets stays two distinguishable rows."""
        entity_registry.register_external([_descriptor("dd_feat")])
        await _add(async_session, CharacterModel, "Банн")
        source = _ExternalSource(
            [],
            mentions=[
                _ExternalHit("dd_feat", "srd51/Darkvision", "Тёмное зрение",
                             origin="SRD 5.1"),
                _ExternalHit("dd_feat", "srd52/Darkvision", "Тёмное зрение",
                             origin="SRD 5.2"),
            ],
        )
        service = _mention_service(async_session, (source,))
        rows = await service.search_names("ёмное")
        assert rows == [
            {"type": "dd_feat", "id": "srd51/Darkvision",
             "name": "Тёмное зрение", "origin": "SRD 5.1"},
            {"type": "dd_feat", "id": "srd52/Darkvision",
             "name": "Тёмное зрение", "origin": "SRD 5.2"},
        ]
        assert source.mention_queries == ["ёмное"]

        rows = await service.search_names("бан")
        assert rows == [{"type": "character", "id": 1, "name": "Банн"}]

    async def test_invisible_source_contributes_no_candidates(
        self, async_session, restore_external_section
    ):
        """Spec mentions (visibility is the source's own condition): a hidden
        source is not even consulted for candidates — its records simply
        never reach the popup, and the kernel half is untouched."""
        entity_registry.register_external([_descriptor("dd_feat")])
        hidden = _ExternalSource([], mentions=[
            _ExternalHit("dd_feat", "p/l", "Lucky"),
        ], visible=False)
        service = _mention_service(async_session, (hidden,))
        assert await service.search_names("lucky") == []
        assert hidden.mention_queries == []

    async def test_unregistered_and_unmentionable_keys_are_dropped(
        self, async_session, restore_external_section
    ):
        """The descriptor is the veto (design Д1): a hit under an unknown key
        or under a registered-but-non-mentionable key earns no row, while a
        healthy key of the same source still passes."""
        entity_registry.register_external(
            [_descriptor("dd_feat"), _descriptor("dd_hidden", mentionable=False)]
        )
        source = _ExternalSource([], mentions=[
            _ExternalHit("bogus", "x", "Bogus"),
            _ExternalHit("dd_hidden", "h", "Hidden kind"),
            _ExternalHit("dd_feat", "p/l", "Lucky"),
        ])
        service = _mention_service(async_session, (source,))
        # the empty query lets every row reach the descriptor veto itself —
        # the filter is not what drops the two unhealthy rows
        rows = await service.search_names("")
        assert [r["id"] for r in rows] == ["p/l"]
