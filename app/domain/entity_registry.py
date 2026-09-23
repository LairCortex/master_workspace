"""Single source of knowledge about entity types (audit A4, design D2).

Keyed by ``EntityType`` (the enum that used to be declared but unused), this
registry holds the display names, the plural forms (the morphology that used
to be hand-rolled at ``f"{type}s" if type != "character"``), the per-type M2M
link sets and the per-use flags (search / LLM). Before wave 3 the same facts
lived in roughly fifteen parallel text dicts across the app.

Deliberately NOT here (design D2): ORM models and repositories. The
type↔model map lives in ``app/infrastructure/repositories/__init__.py``, the
type↔repository map lives in the composition root (``main.py``), so the
domain layer stays ignorant of the storage layer.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.domain.enums.entity_type import EntityType


@dataclass(frozen=True)
class EntityDescriptor:
    """Everything type-generic the app needs to know about one entity type."""

    entity_type: EntityType
    #: stable string identifier used at service, dialog and payload boundaries
    key: str
    #: singular display name, e.g. "Персонаж"
    label: str
    #: plural display name, e.g. "Персонажи"
    plural_label: str
    #: plural form of the key — the M2M collection attribute name, e.g. "characters"
    plural: str
    #: link target types in entity-card display order
    related: tuple[EntityType, ...]
    #: LLM-generated fields in generation order; empty = the type is not generated
    llm_fields: tuple[str, ...]
    #: the type participates in global search
    searchable: bool


def _descriptors() -> dict[EntityType, EntityDescriptor]:
    return {
        d.entity_type: d
        for d in (
            EntityDescriptor(
                EntityType.EVENT, "event", "Событие", "События", "events",
                # the event dialog's / detail panel's related lists
                (EntityType.ORGANIZATION, EntityType.CHARACTER,
                 EntityType.ITEM, EntityType.LOCATION),
                ("name", "characteristics", "backstory"), True,
            ),
            EntityDescriptor(
                EntityType.ORGANIZATION, "organization", "Организация", "Организации",
                "organizations",
                # order pinned by the entity card's relation sections
                (EntityType.CHARACTER, EntityType.ITEM, EntityType.LOCATION),
                ("name", "characteristics", "backstory", "tasks"), True,
            ),
            EntityDescriptor(
                EntityType.CHARACTER, "character", "Персонаж", "Персонажи", "characters",
                (EntityType.ITEM, EntityType.LOCATION, EntityType.ORGANIZATION),
                ("name", "characteristics", "backstory", "personality", "tasks"), True,
            ),
            EntityDescriptor(
                EntityType.ITEM, "item", "Предмет", "Предметы", "items",
                (EntityType.LOCATION, EntityType.CHARACTER, EntityType.ORGANIZATION),
                ("name", "characteristics", "backstory"), True,
            ),
            EntityDescriptor(
                EntityType.LOCATION, "location", "Локация", "Локации", "locations",
                (EntityType.CHARACTER, EntityType.ORGANIZATION, EntityType.ITEM),
                ("name", "characteristics", "backstory", "tasks"), True,
            ),
            EntityDescriptor(
                EntityType.RATING, "rating", "Рейтинг", "Рейтинги", "ratings",
                (),  # rating cards show no relation sections
                (), False,
            ),
        )
    }


_DESCRIPTORS: dict[EntityType, EntityDescriptor] = _descriptors()

#: canonical type order (the enum declaration order) — the order all derived
#: application-wide sequences (search collections, LLM pages) are built in
ORDER: tuple[EntityType, ...] = tuple(_DESCRIPTORS)

_BY_KEY: dict[str, EntityType] = {d.key: t for t, d in _DESCRIPTORS.items()}
_BY_COLLECTION: dict[str, EntityDescriptor] = {d.plural: d for d in _DESCRIPTORS.values()}


def descriptor(entity_type: EntityType) -> EntityDescriptor:
    """Descriptor of a registered type; strict on missing types."""
    return _DESCRIPTORS[entity_type]


def resolve(key: str) -> EntityType | None:
    """Resolve a string type key (``"character"``); ``None`` when unknown."""
    return _BY_KEY.get(key)


def by_collection(name: str) -> EntityDescriptor | None:
    """Descriptor of a collection name (``"characters"``); ``None`` when unknown."""
    return _BY_COLLECTION.get(name)


def type_for_collection(name: str) -> EntityType | None:
    """Entity type owning a collection attribute name; ``None`` when unknown."""
    desc = _BY_COLLECTION.get(name)
    return desc.entity_type if desc is not None else None


def collection(key: str) -> str:
    """Plural form of a type key: ``"character"`` → ``"characters"`` (A4: the
    only place the plural morphology lives). Raises ``KeyError`` for keys the
    registry does not know, like the text dicts it replaced."""
    return _DESCRIPTORS[_BY_KEY[key]].plural


def display_label(key: str) -> str:
    """Singular display name for a type key, falling back to the raw key."""
    etype = _BY_KEY.get(key)
    return _DESCRIPTORS[etype].label if etype is not None else key


@dataclass(frozen=True)
class RelatedRef:
    """One relation section of an entity card: which type, which collection
    attribute on the host, and the section caption (the entry shape the card
    dialog's private ``_RELATED_CONFIG`` used to carry, C5)."""

    entity_type: EntityType
    attr: str
    label: str


RELATED_CONFIG: dict[EntityType, tuple[RelatedRef, ...]] = {
    etype: tuple(
        RelatedRef(target, descriptor(target).plural, descriptor(target).plural_label)
        for target in desc.related
    )
    for etype, desc in _DESCRIPTORS.items()
}

#: types covered by global search, in canonical order (the search service and
#: its view model build their collection keys from these)
SEARCH_TYPES: tuple[EntityType, ...] = tuple(
    t for t in ORDER if _DESCRIPTORS[t].searchable
)

#: types with LLM-generated fields, in canonical page order
LLM_TYPES: tuple[EntityType, ...] = tuple(
    t for t in ORDER if _DESCRIPTORS[t].llm_fields
)


def related_refs(entity_type: EntityType) -> tuple[RelatedRef, ...]:
    """Relation sections of a card-type host; strict on missing types."""
    return RELATED_CONFIG[entity_type]


def related_refs_for_key(key: str) -> tuple[RelatedRef, ...]:
    """Relation sections addressed by a string type key.

    Wave 3.3: a key outside the registry is a bug and raises ``KeyError``
    instead of silently rendering empty sections (the audit's «тихо выходят
    из if rel_type is None: return» class of misses). Registered types that
    simply have no card relations (``rating``) legitimately show none."""
    etype = resolve(key)
    if etype is None:
        raise KeyError(f"unknown entity type {key!r}")
    return RELATED_CONFIG[etype]
