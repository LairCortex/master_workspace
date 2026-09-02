"""Timeline ViewModel — event sample, selection and the day-ladder view state.

redesign-timeline-day-ladder (design D7): the panel's view knobs are the
ladder ``level`` (DAY/MONTH/YEAR), the «Выбор даты» ``window`` — a
navigation range over the tape days, OVERLAP-visible ((None, None) = «Все
дни») — and the ``hide_empty`` toggle. Their setters re-model ``rows``
through the Qt-free ladder core (:func:`build_rows`); the re-model is memoized
on the version key (:meth:`_version_of`) so an identical slice at identical
knobs never rebuilds. All three are plain session state, never persisted, and
``level`` re-defaults to DAY on every load (spec «Вид не переживает
перезапуск»). Selecting an id the ladder does not currently picture descends
to DAY (and resets the window when the event sits outside it) before the
selection lands (spec «Внешний выбор с крупной ступени спускает лестницу»).
"""
from __future__ import annotations

from datetime import date
from typing import Any

from PySide6.QtCore import QObject, Signal

from app.presentation.views.timeline_rows import (
    EventRow,
    LadderRow,
    Level,
    build_rows,
    content_bottom,
)


class TimelineViewModel(QObject):
    events_changed = Signal()
    selected_event_changed = Signal()

    def __init__(self, event_service, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._event_service = event_service
        self._all_events: list[Any] = []
        self.events: list[Any] = []
        self.rows: list[LadderRow] = []
        self.selected_event: Any | None = None
        # Day-ladder view state (design D7) — session-only, never persisted
        # (spec «Вид не переживает перезапуск»): every fresh ViewModel opens
        # «сутки · Все дни · тумблер выключен».
        self._window: tuple[date | None, date | None] | None = None
        self._level: Level = Level.DAY
        self._hide_empty: bool = False
        # Memo key behind the ``rows`` re-model (the widget-level
        # ``_version_of`` fast path mirrored here so VM and list skip the
        # identical sample the same way — design «update_events no-op при том
        # же срезе»); any knob or content move invalidates it.
        self._rows_version: tuple | None = None

    @property
    def all_events(self) -> tuple[Any, ...]:
        """The whole loaded sample, BEFORE the «Выбор даты» window cuts it.

        External selection callers (the search wiring) must ask whether an id
        exists at all — a window-excluded event is exactly the case the
        descent in :meth:`select_event_by_id` exists for, so gating on the
        windowed ``events`` would make «Внешний выбор с крупной ступени
        спускает лестницу» unreachable (spec «Выбор и взаимодействие»)."""
        return tuple(self._all_events)

    # ── ladder knobs (design D7) ─────────────────────────────────────────────

    @property
    def level(self) -> Level:
        """Current ladder rung: DAY / MONTH / YEAR (default :attr:`Level.DAY`)."""
        return self._level

    @level.setter
    def level(self, value: Level) -> None:
        # Changing the rung re-models ``rows`` only: the window, the sample
        # and the selection survive untouched (spec events themselves), an
        # unchanged rung is a no-op.
        if value is self._level:
            return
        self._level = value
        self._rebuild_rows()
        self.events_changed.emit()

    @property
    def window(self) -> tuple[date | None, date | None] | None:
        """«Выбор даты» window — the day span the tape paints, ``None``/
        ``(None, None)`` = «Все дни» (content span instead)."""
        return self._window

    @window.setter
    def window(self, value: tuple[date | None, date | None] | None) -> None:
        # The window is navigation, not a property predicate: visibility rides
        # on overlap with it (design D7), so the visible sample itself is
        # recomputed — and a selection the new window excludes is pruned.
        if value == self._window:
            return
        self._window = value
        self._reproject_window()

    @property
    def hide_empty(self) -> bool:
        """«Скрыть даты без событий» toggle (default off, session-only)."""
        return self._hide_empty

    @hide_empty.setter
    def hide_empty(self, value: bool) -> None:
        # Cuts only empty positions: no event ever leaves the tape because
        # of the toggle, so neither the sample nor the selection moves.
        value = bool(value)
        if value is self._hide_empty:
            return
        self._hide_empty = value
        self._rebuild_rows()
        self.events_changed.emit()

    # ── rows projection (Qt-free core, memoized) ─────────────────────────────

    @staticmethod
    def _version_of(
        events: Any,
        level: Level,
        window: tuple[date | None, date | None] | None,
        hide_empty: bool,
    ) -> tuple:
        """The rebuild key: the ``(id, start, end, name, color)`` set plus
        ``(level, window, hide_empty, bottom)`` (design D7).

        The knobs join the key so a ladder/window/toggle change is never
        swallowed by the identical-sample fast path; ``content_bottom`` is
        derived from the events but pinned explicitly — the day the tape
        bottoms out is exactly what the DAY-level row count depends on. A
        rename or recolor moves the key too: rows carry names and type-dot
        tokens, so the tape must repaint even when no date moved.
        """
        return (
            tuple(
                (
                    e.id, e.start_date, e.end_date, e.name,
                    getattr(getattr(e, "event_type", None), "color_index", None),
                )
                for e in events
            ),
            level,
            window,
            hide_empty,
            content_bottom(events),
        )

    def _rebuild_rows(self) -> None:
        """Re-project the visible sample into ``rows`` via the ladder core.

        The ladder enumerates the window's days (or the content span from
        the earliest start to :func:`content_bottom` without a window),
        duplicates every visible event card per day and rolls the coarser
        rungs up to per-period counter cards (design D2).
        """
        version = self._version_of(self.events, self._level, self._window, self._hide_empty)
        if version == self._rows_version:
            return  # identical sample at identical knobs — same tape
        self._rows_version = version
        self.rows = build_rows(self.events, self._window, self._level, self._hide_empty)

    # ── data loading and the date window ─────────────────────────────────────

    async def load_events(self) -> None:
        self._all_events = list(await self._event_service.get_all_events())
        # The rung re-defaults to «сутки» on every load (design D7); the
        # window and the hide-empty toggle keep living for the session.
        self._level = Level.DAY
        self._reproject_window()

    def _in_window(self, event: Any) -> bool:
        """OVERLAP visibility of ``event`` under the current window (D7).

        An open end crosses every upper bound; a partial window (one ``None``
        bound) only constrains the side it pins, like the core's
        ``_range_for`` fallback.
        """
        if self._window is None:
            return True
        win_start, win_end = self._window
        if win_start is not None and event.end_date is not None \
                and event.end_date < win_start:
            return False
        if win_end is not None and event.start_date > win_end:
            return False
        return True

    def _reproject_window(self) -> None:
        """Recompute the visible set from the window and re-derive its rows.

        Events are OVERLAP-visible (``start <= win_end and (end is None or
        end >= win_start)``, spec «Пересекающее событие видно в окне»);
        without a window the whole sample is visible. ``rows`` is recomputed
        before ``events_changed`` so any consumer reading it from the signal
        sees data consistent with ``events``.

        A selected event the new window excludes is dropped here (and
        ``selected_event_changed`` fires), so the ViewModel, the list and the
        detail panel never disagree about what is selected (spec «Окно
        исключило выбранное событие»). The internal revalidation never drags
        the ladder down — only an external selection descends.
        """
        self.events = [e for e in self._all_events if self._in_window(e)]
        self._rebuild_rows()
        self.events_changed.emit()
        if self.selected_event is not None:
            self._select_from_visible(self.selected_event.id)

    # ── selection and the ladder descent ─────────────────────────────────────

    def _select_from_visible(self, event_id: int | None) -> None:
        """Assign the selection from the visible set; a miss clears it."""
        self.selected_event = next(
            (e for e in self.events if e.id == event_id), None
        )
        self.selected_event_changed.emit()

    def _is_pictured(self, event: Any) -> bool:
        """Whether the current ladder paints a card for ``event``.

        The check rides on ``rows`` itself (the tape is the source of truth
        about what is represented): coarser rungs show counter cards only,
        and a window-excluded event owns no card at all.
        """
        return any(
            isinstance(row, EventRow) and row.event_id == event.id
            for row in self.rows
        )

    async def create_event_at(self, day: date, name: str):
        """Inline creation from an empty day (task 6.1, design D4).

        The empty-day placeholder is the tape's create entry point: Enter on
        the inline field commits here with the clicked day and the typed name.
        One event is written with ``start = end = day`` (a single-day record)
        and no type or links — exactly what the «+»-dialog path would produce
        minus the fields the placeholder has none of — then the sample is
        reloaded and the new record selected, so the caller's reload shows its
        card washed (spec «Инлайн-создание события из пустого дня»).

        An empty (or whitespace-only) name creates nothing and reloads nothing
        (spec «Пустое поле не создаёт»): the placeholder never turns into a
        blank record. A write failure rolls the session back and re-raises so
        the wiring can report it; the shared session stays usable.
        """
        name = (name or "").strip()
        if not name:
            return None
        session = self._event_service._session
        try:
            event = await self._event_service.create_event(
                name=name,
                characteristics="",
                backstory="",
                start_date=day,
                end_date=day,  # single-day event, start == end == day
                event_type_id=None,  # no type on a quick inline create
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        await self.load_events()
        self.select_event_by_id(event.id)
        return event

    def select_event_by_id(self, event_id: int | None) -> None:
        """Select by event id (W3 id-contract); a miss clears the selection.

        External selections — the search path and the jump commands arrive
        through here — descend the ladder when the event owns no card on the
        current rung or window: ``level=DAY`` first and, when the event sits
        outside the «Выбор даты» window, ``window=None («Все дни»)`` — the
        rows are re-modelled (``events_changed`` fires) *before* the caller
        asserts the selection (spec «Внешний выбор с крупной ступени
        спускает лестницу»). An id the sample never held is a plain miss: it
        clears the selection in every layer without a pointless descent.
        """
        event = next((e for e in self._all_events if e.id == event_id), None)
        if event is None:
            self._select_from_visible(event_id)  # a miss: clears + announces
            return
        if not self._is_pictured(event):
            self.level = Level.DAY  # setter no-ops when already on DAY
            if not self._in_window(event):
                self.window = None  # reset re-models the rows («Все дни»)
        self.selected_event = event
        self.selected_event_changed.emit()
