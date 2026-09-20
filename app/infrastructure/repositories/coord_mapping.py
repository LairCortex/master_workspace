"""ORM ⟷ game-coordinate mapping at the repository boundary (C3a, D3/D4).

The six dated repositories are the only layer that knows the two storages
of a date — the legacy ``start_date``/``end_date`` columns and the C3a
``start_coord``/``end_coord`` slots.  Both directions go through the storage
resolver defined next to ``_sync_era_keys`` (design D3):

* write: :meth:`CoordMappingMixin.create`/:meth:`~CoordMappingMixin.update`
  keep the legacy payload/field names (design D4 — «дата = координата» is
  the project's vocabulary, renaming is cosmetics) but accept a
  :data:`GameCoord` there — a plain ``datetime.date`` stays its special
  case — and route every value via :func:`assign_coord`: rows whose
  coordinate slot is filled and games with an active custom calendar land
  in the coordinate columns, standard-preset games land in exactly the same
  date columns as before, and the coordinate columns of a standard game
  stay empty;
* read: :meth:`CoordMappingMixin.resolve_coord` hands the row's truth to
  the layers above as a :data:`GameCoord` (coord column first, date columns
  otherwise) without those layers ever branching on the storage shape.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.domain.game_calendar import DateField, GameCoord
from app.infrastructure.db.models import assign_coord, resolve_coord

#: Legacy payload/field names of the two domain date slots (design D4).
_DATE_PAYLOAD_KEYS = {"start_date": DateField.START, "end_date": DateField.END}

#: The ``start_date`` column is NOT NULL (no table rebuild in C3a), so a
#: fresh row the storage route wrote to the coordinate slot only must still
#: satisfy the schema.  This placeholder never leaves INSERT: it is not the
#: value (the value went to the coordinate columns), and nothing reads it
#: while the coordinate column holds the truth.
_INSERT_DATE_PLACEHOLDER = date(1, 1, 1)


class CoordMappingMixin:
    """Coordinate mapping for the repositories of the six dated tables.

    Mix into each dated repository before ``BaseRepository`` in the bases;
    it overrides only the two write entry points, everything else
    (ordering, search, M2M) is inherited unchanged.
    """

    # ── domain coordinate ⟶ storage (write direction of the mapping) ──────

    def assign_coord(
        self, row: Any, field: DateField | str, coord: GameCoord | date | None
    ) -> None:
        """Route one domain coordinate into the row's storage slot (D3)."""
        assign_coord(row, field, coord)

    async def create(self, **kwargs: Any) -> Any:
        dates = {key: kwargs.pop(key) for key in _DATE_PAYLOAD_KEYS if key in kwargs}
        obj = self._model(**kwargs)
        self._write_dates(obj, dates)
        self._session.add(obj)
        await self._session.flush()
        return obj

    async def update(self, entity_id: int, **kwargs: Any) -> Any:
        dates = {key: kwargs.pop(key) for key in _DATE_PAYLOAD_KEYS if key in kwargs}
        obj = await self.get_by_id(entity_id)
        if obj is None:
            return None
        for key, value in kwargs.items():
            setattr(obj, key, value)
        self._write_dates(obj, dates)
        await self._session.flush()
        return obj

    def _write_dates(self, obj: Any, dates: dict) -> None:
        """Push every supplied date payload value through the write route."""
        for payload_key, coord in dates.items():
            self.assign_coord(obj, _DATE_PAYLOAD_KEYS[payload_key], coord)
        if dates.get("start_date") is not None and obj.start_date_raw is None:
            # The route chose the coordinate slot for a fresh row: the NOT
            # NULL legacy preset column still needs its placeholder.  The
            # raw storage attribute is written directly on purpose — the
            # routed property would re-enter the branch and hit the slot
            # that just received the coordinate.
            obj.start_date_raw = _INSERT_DATE_PLACEHOLDER

    # ── storage ⟶ domain coordinate (read direction of the mapping) ───────

    def resolve_coord(self, row: Any, field: DateField | str) -> GameCoord | None:
        """The row's true date for the layers above, coord column first (D3)."""
        return resolve_coord(row, field)
