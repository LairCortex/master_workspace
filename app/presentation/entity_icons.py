"""The one map: entity type → Lucide glyph name (Lucide pass 2026-09-30).

One knowledge, one place (AGENTS coding principle 2): every surface that
paints an entity type with a glyph — the world-snapshot sections, the entity
tabs, the search section headers — reads it here and nowhere else. The names
are keys of the generated ``icons.js`` map drawn by the library ``ThemeIcon``
(kept in sync with the vendored SVGs by ``scripts/vendor_lucide.py``); the
guard tests pin that every registry type is covered and that no second
type→icon dictionary appears under ``app/``.
"""
from __future__ import annotations

from app.domain import entity_registry
from app.domain.enums.entity_type import EntityType

#: The whole registry, one glyph per type — the coverage guard walks this map.
ENTITY_ICONS: dict[EntityType, str] = {
    EntityType.EVENT: "calendar-days",
    EntityType.LOCATION: "map-pin",
    EntityType.ORGANIZATION: "building",
    EntityType.CHARACTER: "user-round",
    EntityType.ITEM: "sword",
    # Ratings show no search/snapshot section today; the ranked-list glyph
    # stands ready so the coverage guard never forces a second dictionary.
    EntityType.RATING: "list",
}


def icon_for(entity_type: str | EntityType) -> str:
    """The Lucide name of an entity type, by enum or by registry key.

    Strict like the registry itself: a key outside it is a programming error
    (``KeyError``), never a silently missing glyph."""
    etype = (
        entity_type
        if isinstance(entity_type, EntityType)
        else entity_registry.resolve(entity_type)
    )
    if etype is None:
        raise KeyError(f"unknown entity type {entity_type!r}")
    return ENTITY_ICONS[etype]
