"""The ONE declaration of the card grouping tabs (dd-card-redesign Д1).

Owner norm («ядро 0.19.1 неизменно, табы приносит модуль»): the kernel card —
the event dialog and every entity-card type — is the single-screen 0.19.1
view, so the kernel declares EXACTLY ONE group, «Основное», carrying that
whole screen. The tab mechanism stays in the card dormant: the strip shows
only when an external source (protocol ``CardTabSpec``) adds a tab, and those
join AFTER the kernel entry, in source order — a disabled module contributes
nothing and the card returns to the one-screen view with no strip at all
(spec entity-card-tabs «Ядро рисует карточки одним экраном, табы приносит
модуль»).

``GROUP_TEXTS``/``GROUP_RELATIONS`` stay declared as reserved seats of the
grouping mechanism (a future external source may claim them); the kernel
itself never puts either on a strip — in the single-screen view the texts
ride the one grid and the relations sit at the scroll end (or, with external
tabs, in the stitched bottom band).

Validation reveal: when a save is refused because of a field, the group of
that field opens itself (spec «Ошибка указывает дорогу»). Every kernel field
lives in the single group, so the reveal lands on the kernel tab and marks
the field — and for a field owned by an external tab the map answers None:
the external mechanism reveals its own seat. A field name unknown to the map
opens nothing (absent-safe by construction).
"""
from __future__ import annotations

#: Group keys — stable ids (QML page switching, tests, future module seats).
GROUP_OVERVIEW = "overview"
GROUP_TEXTS = "texts"
GROUP_RELATIONS = "relations"

#: The one place the group captions are written (design reference: no icons,
#: the caption and the underline carry the meaning). Only «Основное» reaches
#: a strip today; the other two are the reserved seats' captions.
GROUP_TITLES: dict[str, str] = {
    GROUP_OVERVIEW: "Основное",
    GROUP_TEXTS: "Тексты",
    GROUP_RELATIONS: "Связи",
}

#: Kernel field name → the group that hosts it. The keys are the VM-facing
#: field names used by the reveal rule (the names the validation checks and
#: the highlight bindings read), not the QML object names. The single screen
#: hosts every kernel field, so every entry names the one group. Extra
#: mention fields of a type never appear here: the event dialog validates no
#: extra field, and the card's only validated field is the name — an unknown
#: name simply reveals no group (the rule is absent-safe by construction).
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
    "characteristics": GROUP_OVERVIEW,
    "backstory": GROUP_OVERVIEW,
}


def kernel_card_groups() -> list[dict[str, str]]:
    """The kernel's single «Основное» entry as a QML-ready row (Д1).

    One declaration for every card type and the event: the whole 0.19.1
    screen is this one group, so the kernel strip alone never shows a strip
    (a single tab hides it).
    """
    return [{"key": GROUP_OVERVIEW, "title": GROUP_TITLES[GROUP_OVERVIEW]}]


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
