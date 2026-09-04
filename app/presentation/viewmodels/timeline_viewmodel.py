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

from app.presentation.utils.date_utils import format_game_date
from app.presentation.views.timeline_rows import (
    DayHeaderRow,
    EmptyDayRow,
    EventRow,
    GapCollapsedRow,
    LadderRow,
    Level,
    PeriodCardRow,
    PeriodHeaderRow,
    build_rows,
    content_bottom,
    drill_target,
    header_caption,
    period_span,
    sticky_state,
    zoom_level,
    zoom_target,
)

# ── ladder captions delivered ready to QML (Q2.5a D8: the island renders,
# Python formats) ────────────────────────────────────────────────────────────
#: Placeholder text of an eventless day — the inline-create entry point.
_EMPTY_DAY_TEXT = "+  нет события"
#: Explicit open-end mark every card of an open event carries (no end asserted).
_OPEN_MARK = "бессрочно"
#: Separates the name from the open-end mark on an open event's card.
_OPEN_MARK_SEP = " · "
#: Counter card of a period that no event crosses.
_NO_EVENTS_TEXT = "нет событий"


def _events_phrase(count: int) -> str:
    """RU count phrase for the period counter («4 события», «1 событие»)."""
    if count % 100 in range(11, 15):
        return "событий"
    last = count % 10
    if last == 1:
        return "событие"
    if 2 <= last <= 4:
        return "события"
    return "событий"


def _card_caption(row: EventRow) -> str:
    """Card text: the event name; open events carry the «бессрочно» mark."""
    if row.end is None:
        return f"{row.name}{_OPEN_MARK_SEP}{_OPEN_MARK}"
    return row.name


def _range_text(start: date, end: date | None) -> str:
    """``start — end`` in the game format; an open end stays an explicit ``—``."""
    start_s = format_game_date(start)
    if end is None:
        return f"{start_s} —"
    return f"{start_s} — {format_game_date(end)}"


def _card_summary(row: EventRow) -> str:
    """Dynamic card tooltip body: full name + the game-formatted date range
    (the tooltip shim shows it verbatim — game dates never reach QML)."""
    return f"{row.name}\n{_range_text(row.start, row.end)}"


def _gap_caption(row: GapCollapsedRow) -> str:
    """Collapsed-gap caption: «нет событий» with the gap's game bounds."""
    return (
        f"{_NO_EVENTS_TEXT}: {format_game_date(row.date)} — "
        f"{format_game_date(row.end)}"
    )


def _counter_caption(row: PeriodCardRow) -> str:
    """Period counter text: «N событий» / the muted «нет событий» stub."""
    if row.count:
        return f"{row.count} {_events_phrase(row.count)}"
    return _NO_EVENTS_TEXT


# Interaction/visual flags every entry carries — the full key set on every row
# so QML never reads an undefined key; «summary» is the event card's tooltip
# text (None on every other kind).
_FLAG_KEYS = (
    "selectable",
    "draggable",
    "drillable",
    "creatable",
    "windowable",
    "open",
    "empty",
)


class _RowEntry:
    """One delivered tape row as a ``__slots__`` record (Q2.5a D2: memory is
    __slots__ structs, never QObject rows) — all values are ready scalars
    (str/int/bool/date), the source event object never rides along (1.3)."""

    __slots__ = ("kind", "event_id", "day", "caption", "token_key", "count", "flags")

    def __init__(
        self,
        kind: str,
        event_id: int | None,
        day: date,
        caption: str,
        token_key: str | None,
        count: int,
        flags: dict,
    ) -> None:
        self.kind = kind
        self.event_id = event_id
        self.day = day
        self.caption = caption
        self.token_key = token_key
        self.count = count
        self.flags = flags


def _entry_of(row: LadderRow) -> _RowEntry:
    """Project one Qt-free ladder row onto its delivered ``_RowEntry``; the
    caption/formatting rules are the core's (``header_caption``) or the pure
    helpers above — the model never re-derives content itself."""
    base_flags = {key: False for key in _FLAG_KEYS}
    base_flags["summary"] = None
    if isinstance(row, DayHeaderRow):
        return _RowEntry("dayHeader", None, row.date, header_caption(row),
                         None, 0, base_flags)
    if isinstance(row, PeriodHeaderRow):
        return _RowEntry("periodHeader", None, row.date, header_caption(row),
                         None, 0, base_flags)
    if isinstance(row, EventRow):
        flags = dict(base_flags)
        flags["selectable"] = True
        flags["draggable"] = True
        flags["open"] = row.end is None
        flags["summary"] = _card_summary(row)
        return _RowEntry("event", row.event_id, row.date, _card_caption(row),
                         row.token_key, 0, flags)
    if isinstance(row, EmptyDayRow):
        flags = dict(base_flags)
        flags["creatable"] = True
        return _RowEntry("emptyDay", None, row.date, _EMPTY_DAY_TEXT,
                         None, 0, flags)
    if isinstance(row, GapCollapsedRow):
        flags = dict(base_flags)
        flags["windowable"] = True
        return _RowEntry("gap", None, row.date, _gap_caption(row),
                         None, 0, flags)
    # PeriodCardRow — the one non-card click target with a counter.
    flags = dict(base_flags)
    flags["drillable"] = True
    flags["empty"] = row.count == 0
    return _RowEntry("periodCard", None, row.date, _counter_caption(row),
                     None, row.count, flags)


class TimelineRowModel(QAbstractListModel):
    """The tape's rows as a QML-ready list model (Q2.5a D2 / spec «Питание
    QML-списков списочной моделью»).

    Fed exclusively from the core's ``build_rows`` output (via the ViewModel's
    ``rows``): every re-model lands as a full ``beginResetModel``/
    ``endResetModel`` — the core always builds the day ladder whole, so there
    is no per-row diff to emit, and incremental *delivery* (delegate reuse,
    lazy materialization) is the ListView's job on this side. The entries are
    ``__slots__`` records of ready scalars; the source events never enter the
    model (uniqueness invariant, tasks 1.1/1.3).
    """

    KIND_ROLE = Qt.ItemDataRole.UserRole + 1
    EVENT_ID_ROLE = Qt.ItemDataRole.UserRole + 2
    DAY_ROLE = Qt.ItemDataRole.UserRole + 3
    CAPTION_ROLE = Qt.ItemDataRole.UserRole + 4
    TOKEN_KEY_ROLE = Qt.ItemDataRole.UserRole + 5
    COUNT_ROLE = Qt.ItemDataRole.UserRole + 6
    FLAGS_ROLE = Qt.ItemDataRole.UserRole + 7

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._entries: list[_RowEntry] = []

    # ── feeding (the ViewModel's rebuild path) ───────────────────────────────

    def rebuild(self, rows: Sequence[LadderRow]) -> None:
        """Replace the whole tape position list; emits a model reset."""
        self.beginResetModel()
        self._entries = [_entry_of(row) for row in rows]
        self.endResetModel()

    @property
    def entries(self) -> tuple[_RowEntry, ...]:
        """The delivered entries (test introspection; never mutated outside
        :meth:`rebuild`)."""
        return tuple(self._entries)

    # ── QML hit-test convenience ──────────────────────────────────────────────
    # The island navigates its delegates by index (drop targets, the inline
    # editor's day, wheel anchors) — a visual item is not always materialized
    # for those reads, so the roles come from the model itself. Same values
    # ``data()`` delivers; no rule lives here (spec «Питание QML-списков
    # списочной моделью»: QML renders and looks up, never re-derives).

    @Slot(int, result="QVariantMap")
    def get(self, index: int) -> dict:
        """The row at ``index`` keyed by the role names — an empty map for an
        out-of-range index (the island treats it as "no row there")."""
        if not (0 <= index < len(self._entries)):
            return {}
        entry = self._entries[index]
        return {
            "kind": entry.kind,
            "eventId": entry.event_id,
            "day": entry.day,
            "caption": entry.caption,
            "tokenKey": entry.token_key,
            "count": entry.count,
            "flags": entry.flags,
        }

    # ── QAbstractListModel contract ──────────────────────────────────────────

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # Qt API name
        return 0 if parent.isValid() else len(self._entries)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._entries)):
            return None
        entry = self._entries[index.row()]
        if role == self.KIND_ROLE:
            return entry.kind
        if role == self.EVENT_ID_ROLE:
            return entry.event_id
        if role == self.DAY_ROLE:
            return entry.day
        if role == self.CAPTION_ROLE:
            return entry.caption
        if role == self.TOKEN_KEY_ROLE:
            return entry.token_key
        if role == self.COUNT_ROLE:
            return entry.count
        if role == self.FLAGS_ROLE:
            return entry.flags
        return None

    def roleNames(self) -> dict:  # Qt API name
        return {
            self.KIND_ROLE: b"kind",
            self.EVENT_ID_ROLE: b"eventId",
            self.DAY_ROLE: b"day",
            self.CAPTION_ROLE: b"caption",
            self.TOKEN_KEY_ROLE: b"tokenKey",
            self.COUNT_ROLE: b"count",
            self.FLAGS_ROLE: b"flags",
        }


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
        # The tape's rows as the QML island's list model (Q2.5a D2) — the one
        # delivery channel to QML, kept in lockstep with ``rows`` by every
        # real rebuild; it carries only derived scalars, never the events
        # themselves (uniqueness invariant, task 1.3).
        self._row_model = TimelineRowModel(self)
        # The jump commands' reading anchor (the widget's currentRow mirror for
        # ``jump``): the row index external navigation last revealed; resets
        # to the selection's first card (or ``None`` → tape head) whenever
        # that anchor's row context moves.
        self._read_anchor: int | None = None

    @property
    def row_model(self) -> TimelineRowModel:
        """The QML list model of the current tape rows (Q2.5a D2)."""
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
        # The island's model rides every real re-model (a reset; the memoized
        # no-op above never re-emits it), and the reading anchor re-lands on
        # the selection's first card — the widget's ``_reassert_selection``
        # re-pointing the currentRow, expressed without a view.
        self._row_model.rebuild(self.rows)
        self._read_anchor = (
            self.index_for_event(self.selected_event.id)
            if self.selected_event is not None
            else None
        )

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
        self._read_anchor = self.index_for_event(event_id)
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
        self._read_anchor = self.index_for_event(event.id)
        self.selected_event_changed.emit()

    # ── QML island invokables (Q2.5a D7) ─────────────────────────────────────
    # Sync, service-free entry points the island calls directly: they answer
    # with *indices* (the QML owns geometry and performs every scroll), they
    # write knobs only through the existing property setters, and none of them
    # touches the selection — the id-contract signals stay untouched.

    def _index_at_date(self, day: date) -> int:
        """Index of the first position at/after ``day`` (nearest re-entry).

        Row dates are chronologically ordered (day ladder and period rungs
        alike), so this maps any pre-switch anchor date back onto the
        re-modeled tape: its own day/section, else the first section that
        starts behind it; a date past the tail lands on the last position
        (the widget's ``_index_at_date`` 1:1 — the caller only invokes it on
        a non-empty tape, the wheel answers ``-1`` when nothing anchors).
        """
        for idx, row in enumerate(self.rows):
            if row.date >= day:
                return idx
        return len(self.rows) - 1

    def index_for_event(self, event_id: int | None) -> int | None:
        """Index of the event's first card in ``rows`` (``None`` = not
        pictured — a miss or a coarser rung with counter cards only)."""
        if event_id is None:
            return None
        for idx, row in enumerate(self.rows):
            if isinstance(row, EventRow) and row.event_id == event_id:
                return idx
        return None

    @Slot(int, result=int)
    def scrollToEvent(self, event_id: int) -> int:
        """Where the island must land for ``event_id``: the row index of its
        first card, or ``-1`` when the tape pictures no card (the island then
        keeps its scroll — the widget's ``scroll_to_event`` no-op 1:1). The
        landing index also becomes the jump anchor (the widget's currentRow
        follow)."""
        idx = self.index_for_event(event_id)
        if idx is None:
            return -1
        self._read_anchor = idx
        return idx

    @Slot(int, result="QVariantMap")
    def stickyInfo(self, top_index: int) -> dict:
        """The two sticky captions for a tape whose top edge sits on
        ``top_index`` — the core's :func:`sticky_state` over the VM's ready
        rows (design D3: the QML renders and animates, Python decides *what*
        the overlays say). ``-1`` indices mean "no section there"."""
        state = sticky_state(self.rows, top_index)
        return {
            "currentIndex": -1 if state.current_index is None else state.current_index,
            "currentText": state.current_text,
            "nextIndex": -1 if state.next_index is None else state.next_index,
            "nextText": state.next_text,
        }

    @Slot(int, int, result=int)
    def zoomStep(self, anchor_index: int, delta: int) -> int:
        """Alt/Opt-wheel one notch (design D4/D6): ``delta`` rungs, positive
        zooms in toward DAY, anchored at the row the cursor pointed at (the
        island resolves its own gap/off-tape fallback into the index, the
        widget's «верхняя позиция» rule moves to the QML caller — D7).

        Mirrors the widget's ``_zoom`` knob writes: the ladder clamps at
        «сутки»/«год» silently, zooming OUT never touches the window, and
        zooming IN from a period row installs that row's period as the
        «Выбор даты» window (the descent rides the same «окно = период» rule
        as :meth:`drill`).

        Answers the landing index — the position the re-modeled tape must
        pin to its top edge so the anchored row stays under the cursor (the
        widget's ``_index_at_date`` + ``_scroll_row_to_top`` pair, 1:1;
        ``-1`` = clamped notch or no anchor, the island keeps its scroll).
        """
        target = zoom_level(self._level, 1 if delta > 0 else -1)
        if target is self._level:
            return -1  # the ladder clamps at «сутки» and «год»
        rows = self.rows
        row = rows[anchor_index] if 0 <= anchor_index < len(rows) else None
        if delta > 0:
            # Zooming in pins the row's own day on top; a period row also
            # installs its span as the window (window-then-rung, as drill).
            anchor = row.date if row is not None else None
            span = period_span(row) if row is not None else None
            if span is not None and span != self._window:
                self.window = span
        else:
            # Zooming out pins the anchor's COARSER unit on top (the core's
            # verdict: day row → its month, month row → its year); a row it
            # cannot anchor (a gap) leaves the scroll where it is.
            anchor = zoom_target(self._level, row)
        self.level = target
        if anchor is None:
            return -1
        return self._index_at_date(anchor)

    @Slot(int, result=bool)
    def drill(self, index: int) -> bool:
        """Drill click on the period card at ``index`` (design D4/D6): one
        rung down with the card's whole period as the window (the core's
        :func:`drill_target` pair, written through the knobs). A drill never
        selects — the selection and its signal are untouched; any index that
        is not a period card is a silent no-op."""
        rows = self.rows
        if not (0 <= index < len(rows)):
            return False
        row = rows[index]
        if not isinstance(row, PeriodCardRow):
            return False
        level, window = drill_target(row)
        self.window = window  # «Проваливание выставляет окно»: window first
        self.level = level
        return True

    @Slot(int, result=int)
    def jump(self, step: int) -> int:
        """Alt+Up/Down one event (``step`` = -1 back / +1 forward): the row
        index of the *other* event's nearest card from the reading anchor, or
        ``-1`` when no other event lies that way (the widget returned ``False``
        and the panel descended the ladder; the island gets ``-1``).

        The scan is the widget's ``_scan_event_index`` 1:1: headers, empty
        days and gaps are skipped, and a multi-day event duplicates into one
        card per day whose cards are all skipped — the jumps walk *between*
        events (W3b corridor semantics). Like the widget's ``_reveal_row``,
        this navigates only: the selection never moves (jump не выбирает)."""
        rows = self.rows
        if not rows or step == 0:
            return -1
        selected_id = self.selected_event.id if self.selected_event is not None else None
        own = self.index_for_event(selected_id) if selected_id is not None else None
        base = own if own is not None else (
            self._read_anchor if self._read_anchor is not None else 0
        )
        base = min(max(base, 0), len(rows) - 1)
        base_row = rows[base]
        anchor_event = (
            selected_id
            if selected_id is not None
            else base_row.event_id if isinstance(base_row, EventRow) else None
        )
        rng = (
            range(min(base, len(rows)) - 1, -1, -1)
            if step < 0
            else range(max(base, -1) + 1, len(rows))
        )
        for idx in rng:
            row = rows[idx]
            if isinstance(row, EventRow) and row.event_id != anchor_event:
                self._read_anchor = idx
                return idx
        return -1
