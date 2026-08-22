"""Tests for application services — TDD: tests first."""
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.services.event_service import EventService
from app.application.services.search_service import SearchService
from app.application.services.entity_service import EntityService
from app.infrastructure.db.models import (
    DescriptionModel, EventModel, OrganizationModel,
    CharacterModel, ItemModel, LocationModel,
)


def _mock_event(id_=1, name="Battle"):
    e = MagicMock(spec=EventModel)
    e.id = id_
    e.name = name
    e.start_date = date(1200, 1, 1)
    e.end_date = date(1200, 12, 31)
    e.description_id = 1
    e.organizations = []
    e.characters = []
    e.items = []
    e.locations = []
    return e


def _mock_desc(id_=1):
    d = MagicMock(spec=DescriptionModel)
    d.id = id_
    d.characteristics = "x"
    d.backstory = "y"
    return d


# ── EventService ──────────────────────────────────────────────────────────

class TestEventService:
    def _make_service(self):
        event_repo = AsyncMock()
        desc_repo = AsyncMock()
        org_svc = AsyncMock()
        char_svc = AsyncMock()
        item_svc = AsyncMock()
        loc_svc = AsyncMock()
        svc = EventService(
            event_repo=event_repo,
            description_repo=desc_repo,
            organization_service=org_svc,
            character_service=char_svc,
            item_service=item_svc,
            location_service=loc_svc,
        )
        return svc, event_repo, desc_repo

    @pytest.mark.asyncio
    async def test_create_event(self):
        svc, event_repo, desc_repo = self._make_service()
        desc_repo.create.return_value = _mock_desc(1)
        event_repo.create.return_value = _mock_event(1, "Battle")

        result = await svc.create_event(
            name="Battle",
            characteristics="Big fight",
            backstory="Long ago",
            start_date=date(1200, 1, 1),
            end_date=date(1200, 12, 31),
        )
        desc_repo.create.assert_awaited_once_with(characteristics="Big fight", backstory="Long ago")
        event_repo.create.assert_awaited_once()
        assert result.name == "Battle"

    @pytest.mark.asyncio
    async def test_get_event(self):
        svc, event_repo, _ = self._make_service()
        event_repo.get_by_id.return_value = _mock_event(1)
        result = await svc.get_event(1)
        assert result.id == 1

    @pytest.mark.asyncio
    async def test_get_all_events_ordered(self):
        svc, event_repo, _ = self._make_service()
        event_repo.get_all_ordered.return_value = [_mock_event(1), _mock_event(2, "Siege")]
        result = await svc.get_all_events()
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_events_at_date(self):
        svc, event_repo, _ = self._make_service()
        event_repo.get_events_at_date.return_value = [_mock_event(1)]
        result = await svc.get_events_at_date(date(1200, 6, 15))
        event_repo.get_events_at_date.assert_awaited_once_with(date(1200, 6, 15))
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_update_event(self):
        svc, event_repo, _ = self._make_service()
        updated = _mock_event(1, "Updated")
        event_repo.update.return_value = updated
        result = await svc.update_event(1, name="Updated")
        event_repo.update.assert_awaited_once_with(1, name="Updated")
        assert result.name == "Updated"

    @pytest.mark.asyncio
    async def test_delete_event(self):
        svc, event_repo, _ = self._make_service()
        event_repo.delete.return_value = True
        result = await svc.delete_event(1)
        assert result is True


# ── SearchService ─────────────────────────────────────────────────────────

class TestSearchService:
    def _make_service(self):
        repos = {
            "event": AsyncMock(),
            "organization": AsyncMock(),
            "character": AsyncMock(),
            "item": AsyncMock(),
            "location": AsyncMock(),
        }
        return SearchService(**repos), repos

    @pytest.mark.asyncio
    async def test_global_search(self):
        svc, repos = self._make_service()
        repos["event"].search.return_value = [_mock_event(1, "Battle")]
        repos["organization"].search.return_value = []
        repos["character"].search.return_value = []
        repos["item"].search.return_value = []
        repos["location"].search.return_value = []

        results = await svc.search_all("Battle")
        assert len(results["events"]) == 1
        assert results["organizations"] == []

    @pytest.mark.asyncio
    async def test_global_search_empty(self):
        svc, repos = self._make_service()
        for r in repos.values():
            r.search.return_value = []
        results = await svc.search_all("nonexistent")
        assert all(len(v) == 0 for v in results.values())


# ── EntityService ─────────────────────────────────────────────────────────

class TestEntityService:
    def _make_service(self):
        repo = AsyncMock()
        desc_repo = AsyncMock()
        return EntityService(repo=repo, description_repo=desc_repo), repo, desc_repo

    @pytest.mark.asyncio
    async def test_create_entity(self):
        svc, repo, desc_repo = self._make_service()
        desc_repo.create.return_value = _mock_desc(1)
        mock_org = MagicMock(spec=OrganizationModel)
        mock_org.id = 1
        mock_org.name = "Guild"
        repo.create.return_value = mock_org

        result = await svc.create_entity(
            name="Guild",
            characteristics="Secret",
            backstory="Old",
            start_date=date(1000, 1, 1),
            end_date=date(1500, 12, 31),
        )
        assert result.name == "Guild"

    @pytest.mark.asyncio
    async def test_get_entity(self):
        svc, repo, _ = self._make_service()
        mock_obj = MagicMock()
        mock_obj.id = 5
        repo.get_by_id.return_value = mock_obj
        result = await svc.get_entity(5)
        assert result.id == 5

    @pytest.mark.asyncio
    async def test_update_entity(self):
        svc, repo, _ = self._make_service()
        mock_obj = MagicMock()
        mock_obj.id = 5
        repo.update.return_value = mock_obj
        result = await svc.update_entity(5, name="New")
        repo.update.assert_awaited_once_with(5, name="New")

    @pytest.mark.asyncio
    async def test_delete_entity(self):
        svc, repo, _ = self._make_service()
        repo.delete.return_value = True
        result = await svc.delete_entity(5)
        assert result is True

    @pytest.mark.asyncio
    async def test_get_all(self):
        svc, repo, _ = self._make_service()
        repo.get_all.return_value = [MagicMock(), MagicMock()]
        result = await svc.get_all()
        assert len(result) == 2
