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

Since add-dnd-game-face (design Д2) the registry also carries a section of
ADDITIONAL (external) type descriptors supplied by game-system modules:
``register_external`` is the ONLY door through which a type outside the
closed kernel enum enters (the composition root is its only legal caller,
guard tests/test_architecture_layers.py + tests/test_dd_module_isolation.py).
With the section empty every answer is exactly the pre-change behavior;
the kernel's own literals above are never touched by a registration.
"""
from __future__ import annotations

from collections.abc import Sequence
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
    #: plural display name, e.g. "Персонажи" — since NRI-0018 (Д5) also the
    #: detail tab's visible caption, accessibility name and tooltip at once
    #: (the short-caption ``tab_label`` field of NRI-0015 retired: full names
    #: read better at the wider 1280×800 start and no longer need clipping)
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
                EntityType.CHARACTER, "character", "Персонаж", "Персонажи",
                "characters",
                (EntityType.ITEM, EntityType.LOCATION, EntityType.ORGANIZATION),
                ("name", "characteristics", "backstory", "personality", "tasks"), True,
            ),
            EntityDescriptor(
                EntityType.ITEM, "item", "Предмет", "Предметы", "items",
                (EntityType.LOCATION, EntityType.CHARACTER, EntityType.ORGANIZATION),
                ("name", "characteristics", "backstory"), True,
            ),
            EntityDescriptor(
                EntityType.LOCATION, "location", "Локация", "Локации",
                "locations",
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


def resolve(key: str) -> EntityType | ExternalTypeDescriptor | None:
    """Resolve a string type key (``"character"``); ``None`` when unknown.

    add-dnd-game-face (design Д2): with the external section non-empty a
    registered external key resolves to its :class:`ExternalTypeDescriptor`;
    kernel types keep answering the enum, so the kernel write paths never
    meet an external key by accident of an unregistered section."""
    etype = _BY_KEY.get(key)
    if etype is not None:
        return etype
    return _EXTERNAL.get(key)


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
    """Singular display name for a type key, falling back to the raw key —
    registered external types answer their descriptor's label (design Д2)."""
    etype = _BY_KEY.get(key)
    if etype is not None:
        return _DESCRIPTORS[etype].label
    external = _EXTERNAL.get(key)
    return external.label if external is not None else key


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
#: its view model build their collection keys from these). The kernel half —
#: the union with registered external types is what surfaces read through
#: :func:`search_types` (design Д2).
SEARCH_TYPES: tuple[EntityType, ...] = tuple(
    t for t in ORDER if _DESCRIPTORS[t].searchable
)


def search_types() -> tuple[EntityType | ExternalTypeDescriptor, ...]:
    """Global-search scope as the union of the kernel types and the
    registered, ``searchable`` external types (design Д2: the search groups
    are signed by registry entries, kernel first, externals in registration
    order). With the external section empty this is SEARCH_TYPES itself —
    the byte-for-byte pre-change answer (task 2.2 pin)."""
    return SEARCH_TYPES + tuple(d for d in _EXTERNAL.values() if d.searchable)

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
    simply have no card relations (``rating``) legitimately show none.

    add-dnd-game-face (design Д3): an EXTERNAL type key is known to the
    registry but owns no kernel M2M sets — its card's relations come from the
    source provider, so the descriptor closes the KeyError with none."""
    etype = resolve(key)
    if isinstance(etype, ExternalTypeDescriptor):
        return ()
    if etype is None:
        raise KeyError(f"unknown entity type {key!r}")
    return RELATED_CONFIG[etype]


# ── external type section (add-dnd-game-face, design Д2) ──────────────────


@dataclass(frozen=True)
class ExternalTypeDescriptor:
    """What the kernel needs to know about one type a source contributes.

    The signature mirror of :class:`EntityDescriptor` minus everything the
    kernel owns alone (enum identity, ORM plural, LLM fields): an external
    type is addressed by its ``key`` forever and its records are read-only,
    so no collection attribute and no generation config exist for it. The
    flags decide the surfaces the type may appear in; ``reference`` marks
    the lookup records the search toggle may hide (spec external-entity-sources)."""

    #: stable string identifier, unique against the kernel keys and the rest
    #: of the external section (the kernel never rewrites it)
    key: str
    #: singular display name, e.g. "Заклинание"
    label: str
    #: plural display name — the section/tab caption mirror of EntityDescriptor
    plural_label: str
    #: Lucide glyph name (a key of the island icons.js map, same contract as
    #: presentation/entity_icons.ENTITY_ICONS values)
    icon_key: str
    #: the type participates in global search
    searchable: bool = True
    #: the type may be inserted as an @mention
    mentionable: bool = True
    #: its card may be pinned in the preview column
    pinnable: bool = True
    #: lookup record: visibility additionally follows the reference toggle
    reference: bool = False


#: the one mutable section of the registry — external descriptors keyed by
#: their key, kept in registration order (the order search groups derive in).
#: Written ONLY through :func:`register_external`; every other function here
#: only reads it.
_EXTERNAL: dict[str, ExternalTypeDescriptor] = {}


def register_external(descriptors: Sequence[ExternalTypeDescriptor]) -> None:
    """Replace the external type section (design Д2: the one registration door).

    Idempotent: registering the same descriptors again leaves the registry in
    the same state; registering ``()`` returns it to the kernel-only shape.
    The section is replaced wholesale because the composition root registers
    exactly once per game open, BEFORE the first window — a stale type from a
    previous game must never survive the hand-out.

    Refused (``ValueError``): an empty key, a key colliding with a kernel
    type (the enum and the kernel literals are closed — spec
    «Ни один модуль SHALL NOT регистрировать типы в обход этого механизма»
    covers shape, this guard covers the shadowing), and a duplicate key
    inside one batch."""
    seen: set[str] = set()
    for desc in descriptors:
        if not desc.key:
            raise ValueError("an external type descriptor needs a non-empty key")
        if desc.key in _BY_KEY:
            raise ValueError(
                f"external key {desc.key!r} collides with a kernel entity type"
            )
        if desc.key in seen:
            raise ValueError(f"duplicate external key {desc.key!r} in one batch")
        seen.add(desc.key)
    _EXTERNAL.clear()
    for desc in descriptors:
        _EXTERNAL[desc.key] = desc


def external_types() -> tuple[ExternalTypeDescriptor, ...]:
    """The registered external descriptors, in registration order.

    Public read of the section — the profile pins (task 2.2) and later
    surfaces enumerate it without touching the private dict."""
    return tuple(_EXTERNAL.values())


def external_descriptor(key: str) -> ExternalTypeDescriptor | None:
    """Descriptor of a registered external type; ``None`` for any other key."""
    return _EXTERNAL.get(key)


def is_external_key(key: str) -> bool:
    """Whether the key names a REGISTERED external type.

    The mention grammar (domain/mentions.py, design Д4) reads the id shape
    off exactly this fact: external types admit string ids, kernel keys do
    not. One registry read, no second type-kind dictionary (principle 2)."""
    return key in _EXTERNAL
