"""The ONE declaration of the card grouping tabs (add-dnd-game-face Д10).

Design Д10: the card of an event and the card of every entity type lay their
fields out over grouping tabs; the composition of the groups is declared in
ONE place of the presentation layer, and this module is that place. The
groups themselves (design reference 2026-10-10, «Табы карточек»):

* «Обзор»    — the short fields: image, name, rating, dates + «Бессрочно»,
  age, music; for an event also the hour, minute, type and parent;
* «Тексты»   — every mention field with its AI button (characteristics,
  backstory, and the type's extra fields ride here as a group by construction);
* «Связи»    — the whole existing relations strip, only where the type has
  relations at all (the rating type has none, so its strip has no such tab).

Additional tabs registered by external sources (protocol ``CardTabSpec``)
join AFTER the kernel ones, in source order — a disabled module simply
contributes nothing and never shifts the kernel strip (spec entity-card-tabs
«Таб модуля живёт с модулем»).

Validation reveal: when a save is refused because of a field, the group of
that field opens itself (spec «Ошибка указывает дорогу»). The field→group
map lives here, beside the groups; a field name unknown to it opens nothing.
"""
from __future__ import annotations

#: Group keys — stable ids (QML page switching, tests, future module seats).
GROUP_OVERVIEW = "overview"
GROUP_TEXTS = "texts"
GROUP_RELATIONS = "relations"

#: The one place the group captions are written (design reference: no icons,
#: the caption and the underline carry the meaning).
GROUP_TITLES: dict[str, str] = {
    GROUP_OVERVIEW: "Обзор",
    GROUP_TEXTS: "Тексты",
    GROUP_RELATIONS: "Связи",
}

#: Kernel field name → the group that hosts it. The keys are the VM-facing
#: field names used by the reveal rule (the names the validation checks and
#: the highlight bindings read), not the QML object names. Extra mention
#: fields of a type never appear here: the event dialog validates no extra
#: field, and the card's only validated field is the name — an unknown name
#: simply reveals no group (the rule is absent-safe by construction).
FIELD_GROUP_BY_NAME: dict[str, str] = {
    "name": GROUP_OVERVIEW,
    "rating": GROUP_OVERVIEW,
    "start_date": GROUP_OVERVIEW,
    "end_date": GROUP_OVERVIEW,
    "no_end": GROUP_OVERVIEW,
    "image": GROUP_OVERVIEW,
    "age": GROUP_OVERVIEW,
    "music_url": GROUP_OVERVIEW,
    "hour": GROUP_OVERVIEW,
    "minute": GROUP_OVERVIEW,
    "event_type": GROUP_OVERVIEW,
    "parent": GROUP_OVERVIEW,
    "characteristics": GROUP_TEXTS,
    "backstory": GROUP_TEXTS,
}


def kernel_card_groups(*, has_relations: bool) -> list[dict[str, str]]:
    """The kernel entries «Обзор · Тексты [· Связи]» as QML-ready rows.

    One composition for every card type (design reference, «общая тройка»);
    the relations tab exists exactly when the card has relation sections.
    """
    keys = [GROUP_OVERVIEW, GROUP_TEXTS]
    if has_relations:
        keys.append(GROUP_RELATIONS)
    return [{"key": key, "title": GROUP_TITLES[key]} for key in keys]


def group_key_for_field(field: str) -> str | None:
    """The group key hosting ``field``, or None when the name is unknown."""
    return FIELD_GROUP_BY_NAME.get(field)


class CardGroupState:
    """Qt-free bookkeeping of one card's tab strip (shared by both islands).

    Holds the kernel entries plus the external ones contributed since the
    card's target id became known, and the active index. Every mutator
    reports what changed so the owning ViewModel can raise exactly the
    signals its ``Property`` notifications need (the PySide rule keeps a
    notify signal and its property in the same class — the state stays a
    plain object, the VMs own the Qt face)."""

    def __init__(self, kernel_groups: list[dict[str, str]]) -> None:
        self._kernel = [dict(entry) for entry in kernel_groups]
        self._entries = [dict(entry) for entry in kernel_groups]
        self._active = 0

    def entries(self) -> list[dict[str, str]]:
        """A fresh copy for the QML model (callers never alias the state)."""
        return [dict(entry) for entry in self._entries]

    @property
    def active(self) -> int:
        return self._active

    def key_at(self, index: int) -> str | None:
        if 0 <= index < len(self._entries):
            return str(self._entries[index]["key"])
        return None

    def set_active(self, index: int) -> bool:
        """Select a tab; out-of-range indices change nothing (absent-safe:
        a stale QML write must never move the strip off the strip)."""
        if not 0 <= index < len(self._entries) or index == self._active:
            return False
        self._active = index
        return True

    def set_external_groups(self, external: list[dict[str, str]]) -> tuple[bool, bool]:
        """Replace the module tail; returns (entries_changed, active_changed).

        Kernel entries always come first and in their declared order, so an
        emptied module tail can only SHRINK the strip back onto the kernel
        half — exactly the «выключенный модуль не сдвигает ядерную полосу»
        guarantee. An active index past the shortened strip falls back to 0.
        """
        entries_changed = self._entries != self._kernel + external
        self._entries = [dict(entry) for entry in self._kernel + external]
        if self._active >= len(self._entries):
            self._active = 0
            return entries_changed, True
        return entries_changed, False

    def group_index_for_field(self, field: str) -> int | None:
        """The tab index whose group hosts ``field`` (None = no reveal)."""
        key = group_key_for_field(field)
        if key is None:
            return None
        for index, entry in enumerate(self._entries):
            if entry["key"] == key:
                return index
        return None

    def kernel_count(self) -> int:
        return len(self._kernel)
