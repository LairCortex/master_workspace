"""Timeline ViewModel — event sample, «Выбор даты» window and selection.

simplify-event-timeline-flat-list (design D3): the panel's only view knob is
the «Выбор даты» *window* (``None``/partial pair = «Все дни»); the ladder knobs
(rung, sticky, zoom, drill, jump) and the hide-empty toggle retired with the
ladder. ``window`` and ``load_events`` re-project the visible ``events`` and
the flat ``rows`` through the Qt-free core (:func:`build_rows`) — the window's
intersection rule lives THERE (design D1) and is reused here, never
re-implemented; the re-model is memoized on the version key
(:meth:`_version_of`) so an identical slice at an identical window never
rebuilds. The state is plain session state, never persisted. Selecting an id
the current window excludes resets the window to «Все дни» before the
selection lands (spec «Внешний выбор вне окна сбрасывает окно») — there is no
ladder left to descend.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Sequence

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    Property,
    QObject,
    Qt,
    Signal,
    Slot,
)

from app.presentation.utils.date_utils import get_custom_months
from app.presentation.views.timeline_rows import Row, build_rows, row_detail


class _RowEntry:
    """One delivered flat-list row as a ``__slots__`` record (design D2: memory
    is __slots__ structs, never QObject rows) — all values are ready scalars
    (int/str/bool/None/dict-of-bool), the source event object never rides
    along (uniqueness invariant)."""

    __slots__ = ("event_id", "caption", "detail", "token_key", "flags")

    def __init__(
        self,
        event_id: int,
        caption: str,
        detail: str,
        token_key: str | None,
        flags: dict,
    ) -> None:
        self.event_id = event_id
        self.caption = caption
        self.detail = detail
        self.token_key = token_key
        self.flags = flags


def _entry_of(row: Row) -> _RowEntry:
    """Project one Qt-free flat row onto its delivered ``_RowEntry``; the
    caption/token/detail rules are the core's (``build_rows``) — the model never
    re-derives content itself. Every row is a real event row, so the only
    flag is ``selectable`` (design D2)."""
    return _RowEntry(
        event_id=row.event_id,
        caption=row.caption,
        detail=row.detail,
        token_key=row.token_key,
        flags={"selectable": True},
    )


class TimelineRowModel(QAbstractListModel):
    """The flat list's rows as a QML-ready list model (design D2 / spec
    «Питание QML-списков списочной моделью»).

    Fed exclusively from the core's ``build_rows`` output (via the ViewModel's
    ``rows``): every re-model lands as a full ``beginResetModel``/
    ``endResetModel`` — the core always rebuilds the whole flat list, so there
    is no per-row diff to emit, and incremental *delivery* (delegate reuse,
    lazy materialization) is the ListView's job on this side. The entries are
    ``__slots__`` records of ready scalars; the source events never enter the
    model (uniqueness invariant).
    """

    EVENT_ID_ROLE = Qt.ItemDataRole.UserRole + 1
    CAPTION_ROLE = Qt.ItemDataRole.UserRole + 2
    TOKEN_KEY_ROLE = Qt.ItemDataRole.UserRole + 3
    FLAGS_ROLE = Qt.ItemDataRole.UserRole + 4
    DETAIL_ROLE = Qt.ItemDataRole.UserRole + 5

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._entries: list[_RowEntry] = []

    # ── feeding (the ViewModel's rebuild path) ───────────────────────────────

    def rebuild(self, rows: Sequence[Row]) -> None:
        """Replace the whole flat row list; emits a model reset."""
        self.beginResetModel()
        self._entries = [_entry_of(row) for row in rows]
        self.endResetModel()

    @property
    def entries(self) -> tuple[_RowEntry, ...]:
        """The delivered entries (test introspection; never mutated outside
        :meth:`rebuild`)."""
        return tuple(self._entries)

    # ── QML hit-test convenience ──────────────────────────────────────────────
    # The island addresses rows by index (clicks, scroll landing) — a visual
    # item is not always materialized for those reads, so the scalars come from
    # the model itself. Same values ``data()`` delivers; no rule lives here
    # (spec «Питание QML-списков списочной моделью»: QML renders and looks up,
    # never re-derives).

    @Slot(int, result="QVariantMap")
    def get(self, index: int) -> dict:
        """The row at ``index`` keyed by the role names — an empty map for an
        out-of-range index (the island treats it as "no row there")."""
        if not (0 <= index < len(self._entries)):
            return {}
        entry = self._entries[index]
        return {
            "eventId": entry.event_id,
            "caption": entry.caption,
            "detail": entry.detail,
            "tokenKey": entry.token_key,
            "flags": entry.flags,
        }

    # ── QAbstractListModel contract ──────────────────────────────────────────

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # Qt API name
        return 0 if parent.isValid() else len(self._entries)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._entries)):
            return None
        entry = self._entries[index.row()]
        if role == self.EVENT_ID_ROLE:
            return entry.event_id
        if role == self.CAPTION_ROLE:
            return entry.caption
        if role == self.TOKEN_KEY_ROLE:
            return entry.token_key
        if role == self.FLAGS_ROLE:
            return entry.flags
        if role == self.DETAIL_ROLE:
            return entry.detail
        return None

    def roleNames(self) -> dict:  # Qt API name
        return {
            self.EVENT_ID_ROLE: b"eventId",
            self.CAPTION_ROLE: b"caption",
            self.TOKEN_KEY_ROLE: b"tokenKey",
            self.FLAGS_ROLE: b"flags",
            self.DETAIL_ROLE: b"detail",
        }


class TimelineViewModel(QObject):
    events_changed = Signal()
    selected_event_changed = Signal()

    def __init__(self, event_service, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._event_service = event_service
        self._all_events: list[Any] = []
        self.events: list[Any] = []
        self.rows: list[Row] = []
        self.selected_event: Any | None = None
        # The «Выбор даты» window (design D3) — the panel's single filter and
        # the session's only view state, never persisted; ``None``/a partial
        # pair means «Все дни».
        self._window: tuple[date | None, date | None] | None = None
        # Memo key behind the ``rows`` re-model (the «update_events no-op при
        # том же срезе» fast path): any window or content move invalidates it.
        self._rows_version: tuple | None = None
        # The flat rows as the QML island's list model — the one delivery
        # channel to QML, kept in lockstep with ``rows`` by every real
        # rebuild; it carries only derived scalars, never the events
        # themselves (uniqueness invariant).
        self._row_model = TimelineRowModel(self)

    @property
    def row_model(self) -> TimelineRowModel:
        """The QML list model of the current flat rows."""
        return self._row_model

    # QML-side alias of :attr:`row_model` (the island binds ``model:
    # vm.rowModel``); the Python property above stays the Python contract.
    # CONSTANT: the model object's identity never changes (rebuilds run
    # in-place through the reset signals), so the QML binding resolves once.
    rowModel = Property("QVariant", lambda self: self._row_model, constant=True)

    @property
    def all_events(self) -> tuple[Any, ...]:
        """The whole loaded sample, BEFORE the «Выбор даты» window cuts it.

        External selection callers (the search wiring) must ask whether an id
        exists at all — a window-excluded event is exactly the case the window
        reset in :meth:`select_event_by_id` exists for, so gating on the
        windowed ``events`` would make «Внешний выбор вне окна сбрасывает
        окно» unreachable (spec «Выбор и открытие события»)."""
        return tuple(self._all_events)

    # ── the date window (design D3) ──────────────────────────────────────────

    @property
    def window(self) -> tuple[date | None, date | None] | None:
        """«Выбор даты» window — the only filter of the list, ``None``/a
        partial pair = «Все дни»."""
        return self._window

    @window.setter
    def window(self, value: tuple[date | None, date | None] | None) -> None:
        # The window is navigation, not a property predicate: visibility rides
        # on intersection with it (design D1), so the visible sample itself is
        # recomputed — and a selection the new window excludes is pruned.
        if value == self._window:
            return
        self._window = value
        self._reproject_window()

    # ── rows projection (Qt-free core, memoized) ─────────────────────────────

    @staticmethod
    def _version_of(
        events: Any,
        window: tuple[date | None, date | None] | None,
    ) -> tuple:
        """The rebuild key: the ``(id, start, end, name, color, detail)`` set
        plus the ``window`` and the live game-month map.

        The window joins the key so a window change is never swallowed by the
        identical-sample fast path. A rename or recolor moves the key too:
        rows carry captions and type-dot tokens, so the list must repaint even
        when no date moved. The description line joins it for the same reason
        — rows carry the bounded description text, so editing it alone must
        re-model the rows with no date or name having moved. The month map
        joins the key for the same reason as the captions: they are pre-built
        with ``format_game_date``, so a settings-game rename must re-model the
        rows (spec «Игровые месяцы»); identical maps keep the fast path intact.
        """
        return (
            tuple(
                (
                    e.id, e.start_date, e.end_date, e.name,
                    getattr(getattr(e, "event_type", None), "color_index", None),
                    row_detail(e),
                )
                for e in events
            ),
            window,
            tuple(sorted(get_custom_months().items())),
        )

    def _rebuild_rows(self) -> None:
        """Re-project the visible sample into ``rows`` via the flat core.

        One row per crossing event, ordered ``(start_date, id)``; the window
        filters but never reorders (design D1). The events are already the
        window-filtered sample (``_reproject_window``), so the core's filter
        is a guard here, not the cut itself.
        """
        version = self._version_of(self.events, self._window)
        if version == self._rows_version:
            return  # identical sample at an identical window — same list
        self._rows_version = version
        self.rows = build_rows(self.events, self._window)
        # The island's model rides every real re-model (a reset; the memoized
        # no-op above never re-emits it).
        self._row_model.rebuild(self.rows)

    # ── data loading and the date window ─────────────────────────────────────

    async def load_events(self) -> None:
        self._all_events = list(await self._event_service.get_all_events())
        # The window keeps living for the session across reloads (design D3).
        self._reproject_window()

    def _reproject_window(self) -> None:
        """Recompute the visible set from the window and re-derive its rows.

        The intersection rule is the core's (design D1): the visible ids come
        straight out of :func:`build_rows` over the whole sample — the VM
        never re-implements what «crosses the window» means. An open event
        stays visible in any window at/after its start; an event starting
        before the window stays visible while it still reaches into it.
        ``rows`` is recomputed before ``events_changed`` so any consumer
        reading it from the signal sees data consistent with ``events``.

        A selected event the new window excludes is dropped here (and
        ``selected_event_changed`` fires), so the ViewModel, the list and the
        detail panel never disagree about what is selected (spec «Окно
        исключило выбранное событие»). The internal revalidation never resets
        the window — only an external selection does (spec «при возврате
        события в окно выбор сам не восстанавливается»).
        """
        visible_ids = {
            row.event_id for row in build_rows(self._all_events, self._window)
        }
        self.events = [e for e in self._all_events if e.id in visible_ids]
        self._rebuild_rows()
        self.events_changed.emit()
        if self.selected_event is not None:
            self._select_from_visible(self.selected_event.id)

    # ── selection (design D3: no ladder, the window is the only gate) ────────

    def _select_from_visible(self, event_id: int | None) -> None:
        """Assign the selection from the visible set; a miss clears it."""
        self.selected_event = next(
            (e for e in self.events if e.id == event_id), None
        )
        self.selected_event_changed.emit()

    def select_event_by_id(self, event_id: int | None) -> None:
        """Select by event id (the W3 id-contract); a miss clears the selection.

        External selections — the search path arrives through here — reset the
        «Выбор даты» window when the event sits outside it: ``window=None
        («Все дни»)`` re-projects the rows (``events_changed`` fires) *before*
        the caller asserts the selection (spec «Внешний выбор вне окна
        сбрасывает окно»); an event the window already pictures is selected
        without moving anything. An id the sample never held is a plain miss:
        it clears the selection in every layer without a pointless reset.
        """
        event = next((e for e in self._all_events if e.id == event_id), None)
        if event is None:
            self._select_from_visible(event_id)  # a miss: clears + announces
            return
        if event.id not in {e.id for e in self.events}:
            self.window = None  # outside the window → «Все дни» (re-projects)
        self.selected_event = event
        self.selected_event_changed.emit()

    # ── QML island invokables ────────────────────────────────────────────────
    # Sync, service-free entry points the island calls directly: they answer
    # with *indices* (the QML owns geometry and performs every scroll), and
    # none of them touches the selection — the id-contract signals stay
    # untouched.

    def index_for_event(self, event_id: int | None) -> int | None:
        """Index of the event's single row in ``rows`` (``None`` = not in the
        flat list — a miss or a window-excluded event)."""
        if event_id is None:
            return None
        for idx, row in enumerate(self.rows):
            if row.event_id == event_id:
                return idx
        return None

    @Slot(int, result=int)
    def scrollToEvent(self, event_id: int) -> int:
        """Where the island must land for ``event_id``: the index of its single
        row, or ``-1`` when the list holds no row for it (the island then keeps
        its scroll — the facade's ``scroll_to_event`` no-op 1:1)."""
        idx = self.index_for_event(event_id)
        return -1 if idx is None else idx
