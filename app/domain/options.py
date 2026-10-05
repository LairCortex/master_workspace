"""Flat read-options the application hands to the presentation layer.

The dialogs used to receive raw ORM rows (event types, the parent-event pool,
the linkable-entity census) and hold them in viewmodels while the user kept
editing.  A failed save ends in the shared session's ``rollback()``, which
expires EVERY instance it holds — and the next QML metacall of a property
lambda re-reading a lazy ORM attribute then emits SQL outside the greenlet:
``sqlalchemy.exc.MissingGreenlet`` storms stderr and the binding delivers
nothing (PR-032: the «Тип» list of the live dialog emptied itself while 14
tracebacks a session hit the log).

These options are the boundary the fix moves the projection behind: the
application flattens the rows while they are loaded, and the presentation
layer stores and re-reads only frozen, session-less values — an expired
identity map can no longer reach them.  Like the rest of the domain's value
objects they are frozen dataclasses; equality is by fields, so a rebuilt
option compares equal to the one the dialog already shows.

Each class also carries a tolerant ``coerce``: the presentation entrance
points copy whatever duck arrives (a service option, an ORM row handed by a
legacy caller, a test double) into the frozen shape immediately, so a
viewmodel never STORES an object whose attributes could later go lazy.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EventTypeOption:
    """One entry of the event dialog's «Тип» list: the saved ``id`` (None =
    «Без типа» owns no id), its caption and the palette index of its dot."""

    id: int | None
    name: str
    color_index: int

    @classmethod
    def coerce(cls, carrier: Any) -> "EventTypeOption":
        """Flatten any row-shaped carrier (service option, ORM row, duck)."""
        return cls(
            id=getattr(carrier, "id", None),
            name=getattr(carrier, "name", ""),
            color_index=int(getattr(carrier, "color_index", 1)),
        )


@dataclass(frozen=True)
class EventOption:
    """One entry of the dialog's «Родительское событие» pool; ``parent_id``
    rides along because the main-only filtering is the ViewModel's read-time
    rule (spec «Чужих детей в списке нет»), not the loader's."""

    id: int | None
    name: str
    parent_id: int | None

    @classmethod
    def coerce(cls, carrier: Any) -> "EventOption":
        return cls(
            id=getattr(carrier, "id", None),
            name=getattr(carrier, "name", ""),
            parent_id=getattr(carrier, "parent_id", None),
        )


@dataclass(frozen=True)
class EntityOption:
    """One entity named by a dialog section row or a picker candidate."""

    id: int | None
    name: str

    @classmethod
    def coerce(cls, carrier: Any) -> "EntityOption":
        return cls(
            id=getattr(carrier, "id", None),
            name=getattr(carrier, "name", str(carrier)),
        )
