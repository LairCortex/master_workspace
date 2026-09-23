"""One M2M relation synchronizer for every save trajectory (audit C3, D3).

Three hand-written variations of «add the missing / drop the extra» used to
diverge silently (``entity_service.sync_related`` link-only, ``event_service
._process_items`` create-and-link, the wiring popup loop). This is the single
implementation; callers pick a trajectory with the ``create_missing`` flag:

* ``create_missing=False`` — link-only: a desired id that resolves to no
  stored entity is skipped (an entry already in the collection under that id
  is *kept* — a desired id never unlinks what it could not re-fetch);
* ``create_missing=True`` — desired items without ``_existing_id`` are
  create-entity payloads handed to the service and linked.

``collection`` is the live ORM relationship list; ``desired`` items are the
dialog item dicts: either they carry ``_existing_id`` (link an existing
entity) or the keyword arguments to create one.
"""
from __future__ import annotations

from typing import Any, Iterable, Protocol


class _EntityGateway(Protocol):
    """The slice of ``EntityService`` the synchronizer needs."""

    async def get_entity(self, entity_id: int) -> Any: ...

    async def create_entity(self, **kwargs: Any) -> Any: ...


async def sync_related(
    service: _EntityGateway,
    collection: Any,
    desired: Iterable[dict[str, Any]],
    *,
    create_missing: bool,
) -> None:
    """Sync one M2M collection with the dialog's desired item list."""
    existing_ids = {obj.id for obj in collection}
    new_ids: set = set()

    for item in desired:
        eid = item.get("_existing_id")
        if eid:
            new_ids.add(eid)
            if eid not in existing_ids:
                obj = await service.get_entity(eid)
                if obj:
                    collection.append(obj)
        elif create_missing:
            obj = await service.create_entity(**item)
            collection.append(obj)
            new_ids.add(obj.id)

    # Remove what the desired list no longer names (were linked before).
    to_remove = [obj for obj in collection if obj.id not in new_ids]
    for obj in to_remove:
        collection.remove(obj)
