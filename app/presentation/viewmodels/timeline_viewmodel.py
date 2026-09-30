"""Timeline ViewModel — event sample, «Выбор даты» window and selection.

simplify-event-timeline-flat-list (design D3): the panel's only view knob is
the «Выбор даты» *window* (``None``/partial pair = «Все дни»); the ladder knobs
(rung, sticky, zoom, drill, jump) and the hide-empty toggle retired with the
ladder. ``window`` and ``load_events`` re-project the visible ``events`` and
the tree ``rows`` through the Qt-free core (:func:`build_rows`) — the window's
intersection rule lives THERE (design D1) and is reused here, never
re-implemented; the re-model is memoized on the version key
(:meth:`_version_of`) so an identical slice at an identical window never
rebuilds. The state is plain session state, never persisted. Selecting an id
the current window excludes resets the window to «Все дни» before the
selection lands (spec «Внешний выбор вне окна сбрасывает окно») — there is no
ladder left to descend.

NRI-0021 (design Д6): the game's «now» arrives as the optional ``now_vm``
(the widget VM of the composition root). The row flag rides the same
``build_rows`` re-model, a «now» edit re-delivers only the flags (no reset,
no scroll), and the «➜ Сейчас» button reads its availability and target index
from here — Python counts, QML paints.

NRI-0023 (tasks 5.1–5.2, design Д6): the rows form the two-level tree. The
expanded-parent set is screen state like the window — empty by default, never
persisted, rebuilt through the core with the set passed down. ``toggle_expand``
is the chevron's channel (the QML slot ``toggleExpand``, snapshot-VM pattern),
``expand_to`` reveals a sub-event's parent before an external selection lands
(spec «Переход к свёрнутому подсобытию раскрывает цепочку»). Delivery to the
QML model diffs the re-model when rows were only inserted/removed around a
staying anchor (exactly the expansion case — the ListView then runs its
штатные add/displaced transitions and the view never rewinds, the flipped
chevron riding a scoped repaint); anything else stays the full reset it was.
"""
from __future__ import annotations

from typing import Any, Container, Sequence

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    Property,
    QObject,
    Qt,
    Signal,
    Slot,
)

from app.domain.date_era import era_key
from app.domain.game_calendar import InvalidGameDateError, current_calendar
from app.presentation.utils.date_utils import era_flag
from app.presentation.views.timeline_rows import (
    ROW_EVENT,
    Row,
    build_rows,
    crosses_window,
    event_parent_id,
    event_time_minutes,
    row_detail,
    window_contains,
)

# The «Выбор даты» window bounds travel as they arrive on the panel channels:
# a bare ``date`` (== «н.э.») or the ``(date, is_bc)`` pair the range popover
# applies (add-era-aware-dates, task 4.2). The ViewModel stores them verbatim;
# every comparison happens in the core :func:`build_rows` through the shared
# era key — the window is never re-interpreted here.


class _RowEntry:
    """One delivered tree row as a ``__slots__`` record (design D2: memory
    is __slots__ structs, never QObject rows) — all values are ready scalars
    (int/str/bool/None/dict-of-bool), the source event object never rides
    along (uniqueness invariant). The tree scalars (kind/depth/hasChildren/
    expanded/isLastSibling, NRI-0023 tasks 5.2/11.1) are delivered, never
    re-derived by QML."""

    __slots__ = (
        "event_id", "caption", "detail", "token_key", "flags",
        "kind", "depth", "has_children", "expanded", "is_last_sibling",
    )

    def __init__(
        self,
        event_id: int,
        caption: str,
        detail: str,
        token_key: str | None,
        flags: dict,
        kind: str,
        depth: int,
        has_children: bool,
        expanded: bool,
        is_last_sibling: bool,
    ) -> None:
        self.event_id = event_id
        self.caption = caption
        self.detail = detail
        self.token_key = token_key
        self.flags = flags
        self.kind = kind
        self.depth = depth
        self.has_children = has_children
        self.expanded = expanded
        self.is_last_sibling = is_last_sibling

    def same_position(self, other: "_RowEntry") -> bool:
        """Whether two delivered records can hold each other's place in the
        list — every scalar identical EXCEPT the two flags that move while a
        row STAYS (the diff alignment of :meth:`TimelineRowModel.rebuild`):
        the open/closed flag (expanding a parent inserts the children and
        flips the parent's own ``expanded``) and the group-closing flag
        (expanding one more child turns the previous last child into a middle
        one, NRI-0023 task 11.1, design Д11). An alignment that demanded
        byte-identity would demote every toggle to a reset (design Д6:
        expansion must reach the view as insert/remove) — both moved flags of
        the staying rows are delivered by the scoped repaint
        :meth:`TimelineRowModel._sync_open_state` emits."""
        return (
            self.event_id == other.event_id
            and self.caption == other.caption
            and self.detail == other.detail
            and self.token_key == other.token_key
            and self.flags == other.flags
            and self.kind == other.kind
            and self.depth == other.depth
            and self.has_children == other.has_children
        )


def _flags_of(row: Row) -> dict:
    """The delivered flag map of one row: only a real event row is selectable
    (design D2; NRI-0023 task 5.2 — a parent stub explains, never interacts:
    «выбор и редактирование через неё недоступны»); ``isNow`` carries the
    core's single today-outline flag (NRI-0021 task 5.1) so the delegate can
    paint the outline without ever reading a row rule itself."""
    return {"selectable": row.kind == ROW_EVENT, "isNow": row.is_now}


def _entry_of(row: Row, expanded: Container[int] = frozenset()) -> _RowEntry:
    """Project one Qt-free tree row onto its delivered ``_RowEntry``; the
    caption/token/detail rules are the core's (``build_rows``) — the model never
    re-derives content itself. ``expanded`` is the ViewModel's expanded-parent
    set: only a real event row can wear the open state (the stub's chevron is
    inactive by construction, the delegate paints none whatever this says)."""
    return _RowEntry(
        event_id=row.event_id,
        caption=row.caption,
        detail=row.detail,
        token_key=row.token_key,
        flags=_flags_of(row),
        kind=row.kind,
        depth=row.depth,
        has_children=row.has_children,
        expanded=row.kind == ROW_EVENT and row.event_id in expanded,
        is_last_sibling=row.is_last_sibling,
    )


class TimelineRowModel(QAbstractListModel):
    """The tree's rows as a QML-ready list model (design D2 / spec «Питание
    QML-списков списочной моделью»).

    Fed exclusively from the core's ``build_rows`` output (via the ViewModel's
    ``rows``). A re-model that only inserted or removed whole rows while at
    least one row stayed in place — exactly what expanding/collapsing a parent
    does (NRI-0023 task 5.2) — is delivered as ``insertRows``/``removeRows``
    around the common head and tail: the view keeps its position and runs the
    штатный ``add``/``displaced`` transitions over the moved rows (design Д6),
    while the staying parent's flipped open state rides a scoped
    ``dataChanged``. A re-model the alignment consumes whole (same rows, same
    places — a toggle of a parent with no rows to show) is that repaint alone.
    Anything else (content edits in the middle, a re-cut with nothing staying
    in place — the first feed, an emptied list) lands as the full
    ``beginResetModel``/``endResetModel`` it always was — the core rebuilds
    the list, so there is no finer diff to emit, and incremental *delivery*
    (delegate reuse, lazy materialization) is the ListView's job on this side.
    The entries are ``__slots__`` records of ready scalars; the source events
    never enter the model (uniqueness invariant).
    """

    EVENT_ID_ROLE = Qt.ItemDataRole.UserRole + 1
    CAPTION_ROLE = Qt.ItemDataRole.UserRole + 2
    TOKEN_KEY_ROLE = Qt.ItemDataRole.UserRole + 3
    FLAGS_ROLE = Qt.ItemDataRole.UserRole + 4
    DETAIL_ROLE = Qt.ItemDataRole.UserRole + 5
    KIND_ROLE = Qt.ItemDataRole.UserRole + 6
    DEPTH_ROLE = Qt.ItemDataRole.UserRole + 7
    HAS_CHILDREN_ROLE = Qt.ItemDataRole.UserRole + 8
    EXPANDED_ROLE = Qt.ItemDataRole.UserRole + 9
    IS_LAST_SIBLING_ROLE = Qt.ItemDataRole.UserRole + 10

    #: The scalars that move while a row STAYS (design Д6 + NRI-0023 Д11):
    #: the open/closed chevron state and the group-closing last-sibling flag.
    #: ``same_position`` aligns across both, so an expansion arrives as a
    #: pure insert/remove and every moved flag reaches the kept delegates
    #: through the scoped repaints :meth:`_emit_flag_repaint` answers with.
    _FLAG_ROLES: tuple[tuple[int, str], ...] = (
        (EXPANDED_ROLE, "expanded"),
        (IS_LAST_SIBLING_ROLE, "is_last_sibling"),
    )

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._entries: list[_RowEntry] = []

    # ── feeding (the ViewModel's rebuild path) ───────────────────────────────

    def rebuild(self, rows: Sequence[Row], expanded: Container[int] = frozenset()) -> None:
        """Replace the whole tree row list, diffing where the view can keep
        its position: a pure insertion or removal that leaves a common anchor
        (at least one row staying in place) arrives as
        ``rowsInserted``/``rowsRemoved`` — exactly the expansion case, the rows
        the ListView must animate without rewinding the reading position; a
        re-model the alignment consumed whole (the same rows at the same
        places) is at most the open/closed flag moving and stays a scoped
        repaint; every other move — a re-cut with nothing staying in place
        (the first feed, an emptying list, a wholesale replacement), content
        edits inside the common range — is the legacy reset (the memo in
        front of this method makes that call rare, not wrong)."""
        entries = [_entry_of(row, expanded) for row in rows]
        old = self._entries
        limit = min(len(old), len(entries))
        head = 0
        while head < limit and old[head].same_position(entries[head]):
            head += 1
        tail = 0
        while (
            tail < limit - head
            and old[len(old) - 1 - tail].same_position(entries[len(entries) - 1 - tail])
        ):
            tail += 1
        removed = len(old) - head - tail
        inserted = len(entries) - head - tail
        if removed == 0 and inserted == 0:
            # The alignment consumed both lists whole: the same rows at the
            # same places (head + tail covers every position, each matched),
            # so only the two moving scalars (open/closed, last-sibling) may
            # differ — a chevron toggle on a parent whose children no window
            # shows, or a re-delivery of the identical list. Neither moves the
            # view: scoped repaints of the moved flags, never a reset.
            repaints = []
            for role, attr in self._FLAG_ROLES:
                dirty = [
                    index
                    for index, (entry, fresh) in enumerate(zip(old, entries))
                    if getattr(entry, attr) != getattr(fresh, attr)
                ]
                if dirty:
                    repaints.append((role, dirty))
            self._entries = entries
            self._emit_flag_repaint(repaints)
        elif (inserted > 0) != (removed > 0) and (head > 0 or tail > 0):
            # One side moved alone AND something stayed in place: the view
            # keeps its position and animates the move instead of rewinding.
            if inserted > 0:
                self.beginInsertRows(QModelIndex(), head, head + inserted - 1)
                self._entries[head:head] = entries[head: len(entries) - tail]
                self.endInsertRows()
            else:
                self.beginRemoveRows(QModelIndex(), head, head + removed - 1)
                del self._entries[head: head + removed]
                self.endRemoveRows()
            # The parent row whose chevron just flipped rode the common head
            # (same_position ignores the flag) — deliver its new state.
            self._sync_open_state(entries, head)
        else:
            # Content moved inside the common range, or nothing stayed in
            # place (the first feed, an emptied list, a full re-cut) — the
            # honest full re-delivery the flat list always used.
            self.beginResetModel()
            self._entries = entries
            self.endResetModel()

    def _sync_open_state(self, entries: Sequence["_RowEntry"], head: int) -> None:
        """Carry the moving scalars into the kept head rows after an
        insertion/removal delivery and repaint exactly the rows whose flag
        moved (``same_position`` aligns across the open/closed and the
        last-sibling flags, so the staying parent's new open state and the
        newly-demoted former last child's new closing state reach the
        delegates through these scoped ``dataChanged``\\ s — the one delivery
        the flipped tree bits need). Flags only ever move on the rows the
        change toggled, and a parent's children are emitted DIRECTLY under it:
        the moved rows always sit before the inserted/removed region, inside
        the common head — the aligned tail cannot carry a flag move."""
        repaints = []
        for role, attr in self._FLAG_ROLES:
            dirty: list[int] = []
            for own in range(head):
                entry, fresh = self._entries[own], entries[own]
                if getattr(entry, attr) != getattr(fresh, attr):
                    setattr(entry, attr, getattr(fresh, attr))
                    dirty.append(own)
            if dirty:
                repaints.append((role, dirty))
        self._emit_flag_repaint(repaints)

    def _emit_flag_repaint(self, repaints: Sequence[tuple[int, list[int]]]) -> None:
        """One scoped ``dataChanged`` per moved flag over exactly the rows
        that flag moved on — the delegate's tree bindings re-read the role
        they paint and nothing else is disturbed."""
        for role, dirty in repaints:
            self.dataChanged.emit(
                self.index(min(dirty)), self.index(max(dirty)), [role]
            )

    def reapply_flags(self, rows: Sequence[Row]) -> None:
        """Re-deliver the per-row flags of a «now»-only re-model (NRI-0021
        design Д6) WITHOUT a model reset: membership, order and texts never
        move with «now» — only the outline flag does — and the spec pins the
        same rule for the view («Смена „сейчас“ не прокручивает список
        сама»), which a reset would silently break (the QML onModelReset
        handler rewinds the head). A single ``dataChanged`` over the FLAGS
        role repaints the materialized delegates in place; the tree scalars
        of the entries stay untouched (they cannot move with «now»)."""
        if not self._entries:
            return
        for entry, row in zip(self._entries, rows):
            entry.flags = _flags_of(row)
        self.dataChanged.emit(
            self.index(0), self.index(len(self._entries) - 1), [self.FLAGS_ROLE]
        )

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
            "kind": entry.kind,
            "depth": entry.depth,
            "hasChildren": entry.has_children,
            "expanded": entry.expanded,
            "isLastSibling": entry.is_last_sibling,
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
        if role == self.KIND_ROLE:
            return entry.kind
        if role == self.DEPTH_ROLE:
            return entry.depth
        if role == self.HAS_CHILDREN_ROLE:
            return entry.has_children
        if role == self.EXPANDED_ROLE:
            return entry.expanded
        if role == self.IS_LAST_SIBLING_ROLE:
            return entry.is_last_sibling
        return None

    def roleNames(self) -> dict:  # Qt API name
        return {
            self.EVENT_ID_ROLE: b"eventId",
            self.CAPTION_ROLE: b"caption",
            self.TOKEN_KEY_ROLE: b"tokenKey",
            self.FLAGS_ROLE: b"flags",
            self.DETAIL_ROLE: b"detail",
            self.KIND_ROLE: b"kind",
            self.DEPTH_ROLE: b"depth",
            self.HAS_CHILDREN_ROLE: b"hasChildren",
            self.EXPANDED_ROLE: b"expanded",
            self.IS_LAST_SIBLING_ROLE: b"isLastSibling",
        }


class TimelineViewModel(QObject):
    events_changed = Signal()
    selected_event_changed = Signal()
    #: Availability of the «➜ Сейчас» header button (NRI-0021 task 5.2): the
    #: QML binding follows it on every «now» or window move.
    nowScrollEnabledChanged = Signal()
    #: The button's scroll request (design Д6): Python computes the target
    #: row index, the island owns geometry and performs the scroll — the
    #: facade maps this request onto its ``scrollToIndex`` channel.
    nowScrollRequested = Signal(int)
    #: NRI-0023 (task 6.1, design Д7): «Создать подсобытие» was picked from
    #: the main-event row's native context menu; the payload is that event's
    #: id. The connector turns the request into a prefilled create dialog —
    #: the ladder itself opens nothing.
    subevent_create_requested = Signal(int)

    def __init__(
        self,
        event_service,
        now_vm=None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._event_service = event_service
        self._all_events: list[Any] = []
        self.events: list[Any] = []
        self.rows: list[Row] = []
        self.selected_event: Any | None = None
        # The «Выбор даты» window (design D3) — the panel's single filter and
        # the session's only view state, never persisted; ``None``/a partial
        # pair means «Все дни». Bounds ride as they arrive: a bare date (==
        # «н.э.») or a (date, is_bc) pair from the popover (task 4.2); every
        # comparison on them happens in the core through the shared era key.
        self._window: tuple | None = None
        # NRI-0023 (task 5.2, spec «Шеврон раскрытия дерева»): the ids of the
        # parents whose children the ladder currently shows. Screen state
        # exactly like the window — empty by default (collapsed tree), never
        # persisted, another game (another ViewModel) starts collapsed again.
        self._expanded_parent_ids: set[int] = set()
        # NRI-0021 (tasks 5.1–5.2, design Д6): the game-«now» VM (value
        # reader + single nowChanged broadcast, pattern of the detail panel).
        # The subscription is retired explicitly with the panel island
        # (DEFECT-1 posture — see :meth:`detach_now_listener`).
        self._now_vm = now_vm
        if now_vm is not None:
            now_vm.nowChanged.connect(self._on_now_changed)
        # Memo key behind the ``rows`` re-model (the «update_events no-op при
        # том же срезе» fast path): any window or content move invalidates it.
        self._rows_version: tuple | None = None
        # The flat rows as the QML island's list model — the one delivery
        # channel to QML, kept in lockstep with ``rows`` by every real
        # rebuild; it carries only derived scalars, never the events
        # themselves (uniqueness invariant).
        self._row_model = TimelineRowModel(self)

    def now_pair(self) -> tuple | None:
        """The served game-«now» ``(coord, is_bc)`` pair, ``None`` for a VM
        built without the game's «now» (the outline and the «➜ Сейчас»
        button then simply stay absent/inert)."""
        if self._now_vm is None:
            return None
        return (self._now_vm.coord, self._now_vm.is_bc)

    def detach_now_listener(self) -> None:
        """Stop following the game's «now» (island teardown, NRI-0021 — the
        DEFECT-1 posture: the subscription never outlives the panel);
        idempotent."""
        if self._now_vm is not None:
            self._now_vm.nowChanged.disconnect(self._on_now_changed)
            self._now_vm = None

    def _on_now_changed(self) -> None:
        """The one «now» broadcast (design Д6): the outline flag travels to
        the delegates WITHOUT a model reset (spec «Смена „сейчас“ SHALL не
        прокручивать список сама» — a reset rewinds the head), and the
        «➜ Сейчас» availability is re-evaluated. No scroll, no selection, no
        window move — only the flag and the button."""
        self._rebuild_rows(reapply=True)
        self.nowScrollEnabledChanged.emit()

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

    # ── expansion state (NRI-0023 task 5.2, spec «Шеврон раскрытия дерева») ──

    @property
    def expanded_parent_ids(self) -> frozenset[int]:
        """The parents whose children the ladder shows (immutable view of the
        screen state — empty by default, never persisted)."""
        return frozenset(self._expanded_parent_ids)

    def toggle_expand(self, parent_id: int) -> None:
        """Open/close one parent's children (the chevron's rule). Tolerant by
        construction: an unknown or childless id just rides the set until the
        next re-model ignores it — the delegate only ever wears a chevron the
        core marked with ``hasChildren``."""
        if parent_id in self._expanded_parent_ids:
            self._expanded_parent_ids.discard(parent_id)
        else:
            self._expanded_parent_ids.add(parent_id)
        self._rebuild_rows()

    # QML channel of :meth:`toggle_expand` (camelCase slot as everywhere on
    # this surface; the snapshot VM's toggleSection is the same pattern).
    @Slot(int)
    def toggleExpand(self, parent_id: int) -> None:  # noqa: N802
        self.toggle_expand(parent_id)

    # ── subevent creation (NRI-0023 task 6.1, design Д7) ─────────────────────

    @Slot(int)
    def requestSubeventCreate(self, parent_id: int) -> None:  # noqa: N802
        """The facade's context-menu pick lands here (design Д7): the ladder
        owns no dialog, it only re-broadcasts the parent id on
        :attr:`subevent_create_requested` for the connector to open the
        prefilled create card. The main-event gate lives on the delegate (the
        request never arrives for a child or a stub row), so this slot stays
        kind-agnostic by the same contract the chevron's ``toggleExpand``
        follows."""
        self.subevent_create_requested.emit(int(parent_id))

    def expand_to(self, event_id: int | None) -> bool:
        """Reveal ``event_id``'s parent chain (spec «Переход к свёрнутому
        подсобытию раскрывает цепочку»): with the two-level guarantee exactly
        one link — the event's own parent — is opened, and only when the id
        names a loaded sub-event whose parent is not expanded yet. True when
        the rows were re-modelled by this call (the caller's scroll must run
        after it); top-level events, unknown ids and already-open parents are
        silent no-ops."""
        if event_id is None:
            return False
        event = next((e for e in self._all_events if e.id == event_id), None)
        if event is None:
            return False
        parent_id = event_parent_id(event)
        if parent_id is None or parent_id in self._expanded_parent_ids:
            return False
        self._expanded_parent_ids.add(parent_id)
        self._rebuild_rows()
        return True

    # ── the date window (design D3) ──────────────────────────────────────────

    @property
    def window(self) -> tuple | None:
        """«Выбор даты» window — the only filter of the list, ``None``/a
        partial pair = «Все дни». Bounds are bare dates (== «н.э.») or
        ``(date, is_bc)`` pairs; the core judges them by the shared era key."""
        return self._window

    @window.setter
    def window(self, value: tuple | None) -> None:
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
        window: tuple | None,
        now: tuple | None = None,
        expanded: frozenset[int] = frozenset(),
    ) -> tuple:
        """The rebuild key: the ``(id, start, start_bc, end, end_bc, name,
        color, detail, parent, время)`` set of the WHOLE sample plus the
        ``window``, the served game-«now» pair, the expanded-parent set and
        the active calendar object.

        The window joins the key so a window change is never swallowed by the
        identical-sample fast path. The era flags join it because rows carry
        era-suffixed captions: an era flip alone must re-model the list even
        though no date moved. A rename or recolor moves the key too:
        rows carry captions and type-dot tokens, so the list must repaint even
        when no date moved. The description line joins it for the same reason
        — rows carry the bounded description text, so editing it alone must
        re-model the rows with no date or name having moved. The active
        calendar joins the key as of piece C2 (design D7) for the same reason
        as the captions: they are pre-built with ``format_game_date`` from the
        calendar's names, so installing another calendar object must
        re-model the rows (spec «Игровые месяцы»). Calendars are immutable and
        compare by identity, so re-laying out with the very same object keeps
        the fast path intact — no name-map copy any more. The «now» pair joins
        it as of NRI-0021 (design Д6): the ``is_now`` outline flag is a row
        datum, so a «now» edit alone must re-deliver the rows even though no
        event moved. NRI-0023 moves the key onto the WHOLE sample and adds the
        parent/время fields plus the expanded set: the rows are built from all
        events now (a stub quotes the window-excluded parent's name, a time
        move reorders within the day, a re-chain regroups), so anything the
        tree projection reads must invalidate the memo — an identical sample
        at an identical knob still short-circuits."""
        return (
            tuple(
                (
                    e.id, e.start_date, e.end_date, e.name,
                    era_flag(getattr(e, "start_bc", False)),
                    era_flag(getattr(e, "end_bc", False)),
                    getattr(getattr(e, "event_type", None), "color_index", None),
                    row_detail(e),
                    event_parent_id(e),
                    event_time_minutes(e),
                )
                for e in events
            ),
            window,
            now,
            tuple(sorted(expanded)),
            current_calendar(),
        )

    def _rebuild_rows(self, reapply: bool = False) -> None:
        """Re-project the sample into ``rows`` via the tree core.

        One row per crossing EVENT, ordered ``(start, время, id)`` per level,
        children under expanded parents, stubs over window-excluded parents of
        shown children; the window filters but never reorders (designs D1/Д6).
        The WHOLE sample rides into the core — the visible slice alone could
        not name a stub's parent — and ``self.events`` (the crossing set, see
        :meth:`_reproject_window`) stays the membership answer the selection
        layers gate on. ``reapply`` switches the delivery to the no-reset flag
        re-delivery of :meth:`TimelineRowModel.reapply_flags` — the «now»-only
        path of design Д6 (never a view scroll); membership and order cannot
        move when only «now» moved, so the entries stay in place by
        construction.
        """
        now = self.now_pair()
        coord, is_bc = now if now is not None else (None, False)
        version = self._version_of(
            self._all_events, self._window, now,
            frozenset(self._expanded_parent_ids),
        )
        if version == self._rows_version:
            return  # identical sample at an identical window — same list
        self._rows_version = version
        self.rows = build_rows(
            self._all_events,
            self._window,
            now=coord,
            now_bc=is_bc,
            expanded=self._expanded_parent_ids,
        )
        # The island's model rides every real re-model (a reset or an
        # expansion-shaped insert/remove; the memoized no-op above never
        # re-emits it).
        if reapply:
            self._row_model.reapply_flags(self.rows)
        else:
            self._row_model.rebuild(self.rows, self._expanded_parent_ids)

    # ── data loading and the date window ─────────────────────────────────────

    async def load_events(self) -> None:
        self._all_events = list(await self._event_service.get_all_events())
        # The window keeps living for the session across reloads (design D3).
        self._reproject_window()

    def _reproject_window(self) -> None:
        """Recompute the visible set from the window and re-derive its rows.

        The intersection rule is the core's (design D1), read through its
        public :func:`crosses_window` predicate since NRI-0023: membership in
        the window answers with the EVENTS whose interval crosses it — a
        sub-event inside the window belongs to ``events`` even while no row of
        its is emitted (collapsed parent), and the window-excluded parent of a
        shown child stays OUT (its row is only the stub, and a stub is never
        selectable). An open event stays visible in any window at/after its
        start; an event starting before the window stays visible while it
        still reaches into it. ``rows`` is recomputed before
        ``events_changed`` so any consumer reading it from the signal sees
        data consistent with ``events``.

        A selected event the new window excludes is dropped here (and
        ``selected_event_changed`` fires), so the ViewModel, the list and the
        detail panel never disagree about what is selected (spec «Окно
        исключило выбранное событие»). The internal revalidation never resets
        the window — only an external selection does (spec «при возврате
        события в окно выбор сам не восстанавливается»).
        """
        self.events = [
            e for e in self._all_events if crosses_window(e, self._window)
        ]
        self._rebuild_rows()
        self.events_changed.emit()
        # The «➜ Сейчас» availability is a function of the window too (spec
        # «Кнопка вне окна»: сброс окна в «Все дни» возвращает кнопке жизнь).
        self.nowScrollEnabledChanged.emit()
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
        NRI-0023 (task 5.2, spec «Переход к свёрнутому подсобытию раскрывает
        цепочку»): just before the selection lands, :meth:`expand_to` opens
        the parent of a sub-event — every selection point that reaches the
        ladder (search click, the shared ``_on_event_selected`` handler, the
        full entity path) is this funnel, so the caller's highlight-and-scroll
        always finds the child's now-visible row.
        """
        event = next((e for e in self._all_events if e.id == event_id), None)
        if event is None:
            self._select_from_visible(event_id)  # a miss: clears + announces
            return
        if event.id not in {e.id for e in self.events}:
            self.window = None  # outside the window → «Все дни» (re-projects)
        self.expand_to(event.id)
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

    # ── «➜ Сейчас» button (NRI-0021 task 5.2, design Д6) ─────────────────────

    def _now_scroll_enabled(self) -> bool:
        """Whether the game's «now» is one of the current window's days
        (spec «Кнопка прокрутки „➜ Сейчас“»: active exactly when «сейчас»
        falls inside the filter; «Все дни» — always). A VM without the game's
        «now» has nothing to scroll to; a «now» the active calendar refuses
        cannot be located on the window's scale (group-4 posture: the derived
        control goes inert, it never raises)."""
        now = self.now_pair()
        if now is None:
            return False
        try:
            return window_contains(self._window, now[0], now[1])
        except InvalidGameDateError:
            return False

    nowScrollEnabled = Property(bool, _now_scroll_enabled,
                                notify=nowScrollEnabledChanged)

    @Slot()
    def requestNowScroll(self) -> None:  # noqa: N802
        """The header button's sync entry: compute the landing row and emit
        the scroll request (design Д6 — QML owns geometry, Python owns the
        index; the button's activation is the ONE scroll, a «now» edit alone
        never scrolls).

        Target = the first row whose start is STRICTLY later than «now»
        (spec «Прокрутка к позиции „сейчас“»), else the list end (spec
        «„Сейчас“ позже всех событий»). ``-1`` = nothing to reveal: an empty
        list, or a «now»/window comparison the calendar refuses — the facade
        then keeps the scroll, exactly like the ``scrollToEvent`` no-op."""
        now = self.now_pair()
        index = -1
        if now is not None:
            try:
                now_key = era_key(now[0], now[1])
                for idx, row in enumerate(self.rows):
                    if era_key(row.start, row.start_bc) > now_key:
                        index = idx
                        break
                else:
                    index = len(self.rows) - 1 if self.rows else -1
            except InvalidGameDateError:
                index = -1
        self.nowScrollRequested.emit(index)
