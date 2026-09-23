"""One dated-repository class per model — the clone factory (audit C4, D3).

The character/item/location/organization repositories were byte-identical
class bodies differing only by the model. ``dated_repository(model)`` builds
that body once; the composition root (``main.py``) calls the factory, and
the four former modules are thin aliases onto it so the bare-session test
constructors (``XRepository(session)``) stay untouched (D4: repository
constructor contracts do not change).
"""
from __future__ import annotations

from typing import TypeVar

from app.infrastructure.repositories.base_repository import BaseRepository
from app.infrastructure.repositories.coord_mapping import CoordMappingMixin

T = TypeVar("T")

# model → its generated dated-repository class (stable identity per model).
_BY_MODEL: dict[type, type] = {}


def dated_repository(model: type[T]) -> type[BaseRepository[T]]:
    """Return the dated-repository class bound to ``model`` (created once).

    The result is constructed exactly like the old hand-written classes —
    ``dated_repository(Model)(session)`` — because D4 froze the repository
    constructor contracts until the unit-of-work wave. Each model maps to
    one and the same class (``is``-stable), so isinstance identity across
    alias modules and factory callers never splits.
    """
    cls = _BY_MODEL.get(model)
    if cls is None:
        def __init__(self, session) -> None:  # noqa: ANN001 - BaseRepository signature
            BaseRepository.__init__(self, session, model)

        cls = type(
            f"{model.__name__}Repository",
            (CoordMappingMixin, BaseRepository),
            {"__init__": __init__,
             "__doc__": "Dated table: dates map through the coordinate "
                        "resolver (C3a, D3). Built by dated_repository()."},
        )
        _BY_MODEL[model] = cls
    return cls  # type: ignore[return-value]
