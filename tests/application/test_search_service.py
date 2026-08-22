"""Characterization tests for SearchService against a real in-memory DB.

Pins current behavior: search by name / characteristics / backstory across
all 5 entity types, case-insensitivity (ASCII + unicode via registered
SQLite lower()), de-duplication, and search_names() result shape.
"""
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.search_service import SearchService
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
