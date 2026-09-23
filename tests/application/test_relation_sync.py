"""The single synchronizer's flag semantics (audit C3, task 2.5).

``sync_related`` owns every «add missing / drop extra» trajectory; these
cases pin what the ``create_missing`` flag decides and what is identical on
both trajectories (link/drop rules, missing-entity tolerance).
"""
from __future__ import annotations

from types import SimpleNamespace

from app.application.services.relation_sync import sync_related


class _StubService:
    """EntityService slice: fetch by id, create from kwargs."""

    def __init__(self, known: dict[int, object], created_names: list[str]) -> None:
        self._known = known
        self.created_names = created_names
        self.next_id = 100

    async def get_entity(self, entity_id):
        return self._known.get(entity_id)

    async def create_entity(self, **kwargs):
        obj = SimpleNamespace(id=self.next_id, name=kwargs["name"])
        self.next_id += 1
        self.created_names.append(kwargs["name"])
        return obj


def _ent(object_id: int):
    return SimpleNamespace(id=object_id, name=f"e{object_id}")


def _collection(*objs):
    return list(objs)


class TestLinkOnlyFlag:
    async def test_link_only_never_creates_from_kwargs_items(self):
        svc = _StubService({1: _ent(1)}, created_names=[])
        collection = _collection()
        await sync_related(
            svc,
            collection,
            [{"name": "fresh"}, {"_existing_id": 1}],
            create_missing=False,
        )
        assert svc.created_names == []  # the payload item was not a creation order
        assert [o.id for o in collection] == [1]  # only the existing id linked

    async def test_create_missing_creates_links_and_keeps_through_sync(self):
        svc = _StubService({}, created_names=[])
        collection = _collection()
        await sync_related(
            svc, collection, [{"name": "fresh"}], create_missing=True
        )
        assert svc.created_names == ["fresh"]
        assert [o.id for o in collection] == [100]  # created row stays linked


class TestSharedTrajectory:
    async def test_link_adds_fetches_removes_extras_on_both_flags(self):
        for flag in (False, True):
            a, b = _ent(1), _ent(2)
            svc = _StubService({2: _ent(2), 3: _ent(3)}, created_names=[])
            collection = _collection(a, b)
            await sync_related(
                svc,
                collection,
                [{"_existing_id": 2}, {"_existing_id": 3}],
                create_missing=flag,
            )
            # 2 kept without refetch, 3 fetched and added, 1 unlinked.
            assert [o.id for o in collection] == [2, 3]

    async def test_desired_id_without_stored_entity_keeps_local_row(self):
        # A desired id that no longer resolves must not blank the collection:
        # the id was named, so its previously linked row is not an extra.
        keep = _ent(7)
        svc = _StubService({}, created_names=[])
        collection = _collection(keep)
        await sync_related(
            svc, collection, [{"_existing_id": 7}], create_missing=False
        )
        assert [o.id for o in collection] == [7]
