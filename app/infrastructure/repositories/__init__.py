"""Repository-layer package.

Type↔ORM map (design D2): the domain registry must not reference ORM models,
so the ``EntityType`` → model association is owned here and read by the
application services that store entities (xlsx import, mention rewrite).
The type↔repository map intentionally stays in the composition root
(``app/main.py``, ``_build_entity_services``).
"""
from __future__ import annotations

from app.domain.enums.entity_type import EntityType
from app.infrastructure.db.models import (
    CharacterModel,
    EventModel,
    ItemModel,
    LocationModel,
    OrganizationModel,
)

#: storage model per entity type (the same five types the app can persist
#: as cards; ratings are managed through their own dialog, not this map)
ORM_MODEL_BY_ENTITY_TYPE: dict[EntityType, type] = {
    EntityType.EVENT: EventModel,
    EntityType.ORGANIZATION: OrganizationModel,
    EntityType.CHARACTER: CharacterModel,
    EntityType.ITEM: ItemModel,
    EntityType.LOCATION: LocationModel,
}

_MODEL_TO_ENTITY_TYPE: dict[type, EntityType] = {
    model: etype for etype, model in ORM_MODEL_BY_ENTITY_TYPE.items()
}


def entity_type_for_model(model: type) -> EntityType:
    """Entity type stored by an ORM model class; raises ``KeyError`` for
    models outside the map (same contract as the dict it replaced)."""
    return _MODEL_TO_ENTITY_TYPE[model]
