"""Unit tests for ``TimelineRowModel`` (simplify-event-timeline-flat-list 2.2;
NRI-0023 task 5.2 turns the delivery into the two-level tree).

The model is the sole delivery channel of the tree rows to the QML island
(design D2 / spec «Питание QML-списков списочной моделью»): the simplified
row scalars (``event_id``, ``caption``, ``detail``, ``token_key``, ``flags`` —
``selectable`` plus the NRI-0021 ``isNow`` outline flag — plus the NRI-0023
tree scalars ``kind``/``depth``/``hasChildren``/``expanded``) — asserted over
REAL ``build_rows`` output plus hand-made :class:`Row` records pinning the
caption and the description line of a typed, an untyped and an open row.
Since NRI-0021 (design Д6) the ``reapply_flags`` no-reset re-delivery of a
«now»-only re-model is pinned here too; since NRI-0023 (design Д6) so is the
expansion-shaped delivery: children arriving/leaving ride
``rowsInserted``/``rowsRemoved`` (the view animates and keeps its position),
the staying parent's flipped chevron rides a scoped ``dataChanged``, and only
real content moves stay a model reset.
"""
from datetime import date
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QModelIndex, Qt

from app.domain.game_calendar import current_calendar, reset_current_calendar, set_current_calendar
from app.presentation.viewmodels.timeline_viewmodel import (
    TimelineRowModel,
    _RowEntry,
)
from app.presentation.views.timeline_rows import Row, build_rows


class _Event:
    """Plain event double — the core's duck-typed input shape."""

    def __init__(self, id_, start, end, name, color_index=None, description=None,
                 parent_id=None, start_time_raw=None):
        self.id = id_
        self.start_date = start
        self.end_date = end
        self.name = name
        if description is not None:
            self.description = description
        if parent_id is not None:
            self.parent_id = parent_id
        if start_time_raw is not None:
            self.start_time_raw = start_time_raw
        if color_index is None:
            self.event_type = None
        else:
            class _T:
                pass
            t = _T()
            t.color_index = color_index
            self.event_type = t


@pytest.fixture(autouse=True)
def _default_game_months():
    """Captions are game-calendar text — pin the «Стандартный» preset around
    each unit regardless of what other suites left in the shared process
    state, then hand the previously active calendar object back."""
    saved = current_calendar()
    reset_current_calendar()
    yield
    set_current_calendar(saved)


def _model_of(rows, expanded=frozenset()):
    model = TimelineRowModel()
    model.rebuild(rows, expanded=expanded)
    return model


def _field(model, row, role):
    return model.data(model.index(row), role)


class TestRoleContract:
    def test_role_names_exposed(self):
        """The QML binding contract: the five flat role names (design D2 —
        the ladder's kind/day/count roles retired with the ladder; ``detail``
        is the row's description line) plus the NRI-0023 tree scalars the
        delegate paints (kind/depth/hasChildren/expanded plus the task 11.1
        isLastSibling closing the branch)."""
        names = set(TimelineRowModel().roleNames().values())
        assert names == {
            b"eventId", b"caption", b"detail", b"tokenKey", b"flags",
            b"kind", b"depth", b"hasChildren", b"expanded", b"isLastSibling",
        }


class TestEntriesFromBuildRows:
    def test_row_count_is_the_flat_list_length(self):
        """``rowCount`` == len(build_rows(...)) — one event, one row."""
        events = [
            _Event(1, date(1200, 1, 5), date(1200, 1, 7), "Council", color_index=2),
            _Event(2, date(1200, 1, 6), None, "Prophecy"),
        ]
        rows = build_rows(events, window=(date(1200, 1, 5), date(1200, 1, 7)))
        model = _model_of(rows)
        assert model.rowCount() == len(rows) == 2  # no per-day duplication

    def test_typed_row_carries_the_ready_scalars(self):
        rows = build_rows([
            _Event(1, date(1200, 2, 20), date(1200, 3, 10), "War", color_index=1)
        ])
        model = _model_of(rows)
        assert _field(model, 0, model.EVENT_ID_ROLE) == 1
        assert _field(
            model, 0, model.CAPTION_ROLE
        ) == "20 Февраль 1200 — 10 Март 1200 · War"
        assert _field(model, 0, model.TOKEN_KEY_ROLE) == "color.chart.1"
        assert _field(model, 0, model.FLAGS_ROLE) == {"selectable": True, "isNow": False}
        assert _field(model, 0, model.DETAIL_ROLE) == ""  # no description carried

    def test_description_line_is_delivered_with_the_row(self):
        """Spec «Плоский список событий»: the row carries the event's own
        description text as its second line, ready to paint."""
        rows = build_rows([
            _Event(1, date(1200, 2, 20), None, "War",
                   description=SimpleNamespace(
                       characteristics="Первая\n    война", backstory="не важно"))
        ])
        model = _model_of(rows)
        assert _field(model, 0, model.DETAIL_ROLE) == "Первая война"

    def test_open_untyped_row_shows_the_infinity_mark(self):
        """Spec «Бессрочная строка»: the caption carries ``∞``, the untyped
        row has no token — the delegate paints the muted mark itself."""
        rows = build_rows([_Event(2, date(1200, 3, 5), None, "Prophecy")])
        model = _model_of(rows)
        assert _field(model, 0, model.CAPTION_ROLE) == "05 Март 1200 — ∞ · Prophecy"
        assert _field(model, 0, model.TOKEN_KEY_ROLE) is None
        assert _field(model, 0, model.FLAGS_ROLE) == {"selectable": True, "isNow": False}

    def test_flag_keys_are_the_selectable_and_isNow_pair_on_every_row(self):
        """QML never reads an undefined flag — and the ladder's
        drillable/windowable/etc. vocabulary is gone (design D2); the NRI-0021
        ``isNow`` key is delivered on every row, False unless the row starts
        exactly on the game's «now» (build_rows decides, here it rides)."""
        model = _model_of(build_rows([
            _Event(1, date(1200, 1, 1), date(1200, 1, 2), "closed", color_index=3),
            _Event(2, date(1200, 1, 3), None, "open"),
        ]))
        for i in range(model.rowCount()):
            assert set(_field(model, i, model.FLAGS_ROLE)) == {"selectable", "isNow"}

    def test_the_group_closing_role_rides_the_core_flag(self):
        """Task 11.1: ``isLastSibling`` is delivered from ``build_rows`` on
        the role, verbatim — true on the group's last child, false on the
        parent and every middle child (the delegate paints the angle from
        this scalar, never re-deriving it from ``index``)."""
        parent = _Event(1, date(1200, 1, 5), None, "Родитель")
        first = _Event(2, date(1200, 1, 6), None, "первый", parent_id=1)
        last = _Event(3, date(1200, 1, 7), None, "последний", parent_id=1)
        model = _model_of(build_rows([parent, first, last], expanded={1}),
                          expanded={1})
        delivered = [
            _field(model, row, model.IS_LAST_SIBLING_ROLE)
            for row in range(model.rowCount())
        ]
        assert delivered == [False, False, True]


class TestGetConvenience:
    def test_get_hits_the_flat_row_scalars(self):
        """``get`` is the island's hit-test convenience: the simplified row's
        scalars keyed by role name (the NRI-0023 tree scalars delivered as
        the delegate reads them — a plain top-level row is an event, depth 0,
        childless, collapsed, no group to close)."""
        model = _model_of(build_rows([
            _Event(7, date(1200, 3, 1), None, "Слух", color_index=5)
        ]))
        row = model.get(0)
        assert set(row) == {
            "eventId", "caption", "detail", "tokenKey", "flags",
            "kind", "depth", "hasChildren", "expanded", "isLastSibling",
        }
        assert row["eventId"] == 7
        assert row["caption"] == "01 Март 1200 — ∞ · Слух"
        assert row["detail"] == ""
        assert row["tokenKey"] == "color.chart.5"
        assert row["flags"] == {"selectable": True, "isNow": False}
        assert (row["kind"], row["depth"], row["hasChildren"], row["expanded"]) == (
            "event", 0, False, False
        )
        assert row["isLastSibling"] is False

    def test_get_misses_answer_empty(self):
        model = _model_of(build_rows([
            _Event(1, date(1200, 1, 1), date(1200, 1, 1), "x")
        ]))
        assert model.get(-1) == {}
        assert model.get(1) == {}


class TestReapplyFlags:
    """``reapply_flags`` (NRI-0021 design Д6): the «now»-only re-model moves
    the outline flag ALONE — membership, order and texts stay put, so the
    delivery is a scoped ``dataChanged`` and NEVER a reset (a reset would
    rewind the view's head, which the spec forbids for a «now» edit)."""

    EVENTS = [
        _Event(1, date(1200, 1, 5), None, "Council"),
        _Event(2, date(1200, 3, 7), None, "Fair"),
    ]

    def _spy(self, model):
        resets: list = []
        changes: list = []
        model.modelReset.connect(lambda: resets.append(1))
        model.dataChanged.connect(
            lambda top, bottom, roles=None: changes.append(
                (top.row(), bottom.row(), list(roles or []))
            )
        )
        return resets, changes

    def test_reapply_moves_the_flag_without_a_model_reset(self):
        model = _model_of(build_rows(self.EVENTS, now=date(1200, 1, 5)))
        assert [entry.flags["isNow"] for entry in model.entries] == [True, False]
        resets, changes = self._spy(model)
        captions_before = [entry.caption for entry in model.entries]

        model.reapply_flags(build_rows(self.EVENTS))  # «now» gone: nobody today

        assert [entry.flags["isNow"] for entry in model.entries] == [False, False]
        assert resets == []  # no reset → the view never rewinds
        assert changes == [
            (0, model.rowCount() - 1, [model.FLAGS_ROLE])
        ]  # one scoped repaint of the delivered rows
        assert [entry.caption for entry in model.entries] == captions_before
        # The scalars QML re-reads after dataChanged carry the new state.
        assert _field(model, 0, model.FLAGS_ROLE) == {"selectable": True, "isNow": False}

    def test_reapply_on_an_empty_model_is_a_silent_noop(self):
        """A «now» edit on an unloaded panel must not emit index-invalid
        changes (the delegates read nothing yet)."""
        model = TimelineRowModel()
        resets, changes = self._spy(model)
        model.reapply_flags(build_rows(self.EVENTS, now=date(1200, 1, 5)))
        assert model.rowCount() == 0
        assert resets == [] and changes == []


class TestRebuildAndEmpty:
    def test_fresh_model_is_empty(self):
        model = TimelineRowModel()
        assert model.rowCount() == 0
        assert model.data(model.index(0), model.EVENT_ID_ROLE) is None
        assert model.entries == ()

    def test_rebuild_replaces_rows_and_fires_reset(self):
        """A re-model that rewrites the whole list (no common head/tail to
        keep) is the full reset it always was — counters and entries follow
        the core's re-cut (NRI-0023: the diff only spares the view when it
        can literally keep the rows in place)."""
        model = TimelineRowModel()
        resets: list[int] = []
        model.modelReset.connect(lambda: resets.append(1))

        model.rebuild(build_rows([
            _Event(1, date(1200, 1, 1), date(1200, 1, 1), "One")
        ]))
        assert model.rowCount() == 1
        assert _field(model, 0, model.EVENT_ID_ROLE) == 1

        model.rebuild(build_rows([
            _Event(2, date(1200, 1, 2), date(1200, 1, 2), "Two"),
            _Event(3, date(1200, 1, 3), None, "Three"),
        ]))
        assert model.rowCount() == 2  # counters follow the re-model
        assert [entry.event_id for entry in model.entries] == [2, 3]
        assert len(resets) == 2  # a re-cut with nothing in common is a reset

        model.rebuild([])
        assert model.rowCount() == 0
        assert model.data(model.index(0), model.EVENT_ID_ROLE) is None
        assert len(resets) == 3

    def test_out_of_range_and_invalid_index_answer_none(self):
        model = _model_of(build_rows([
            _Event(1, date(1200, 1, 1), date(1200, 1, 1), "x")
        ]))
        assert model.data(model.index(5), model.CAPTION_ROLE) is None
        assert model.data(QModelIndex(), model.CAPTION_ROLE) is None
        assert model.rowCount(model.index(0)) == 0  # rows have no children
        # Unclaimed Qt roles (Display/Edit/…) answer None — the delegates read
        # the model exclusively through the four custom roles.
        assert model.data(model.index(0), Qt.ItemDataRole.DisplayRole) is None
        assert model.data(model.index(0), Qt.ItemDataRole.EditRole) is None

    def test_entries_are_slots_scalars_only(self):
        """The delivered structs are ``__slots__`` records (design D2) — the
        event source object never rides along; the record carries exactly the
        five flat scalars plus the NRI-0023 tree scalars (kind/depth/
        hasChildren/expanded plus the task 11.1 is_last_sibling)."""
        model = _model_of([
            Row(event_id=1, start=date(1200, 1, 1), end=None, name="Open",
                token_key=None, caption="01 Январь 1200 — ∞ · Open",
                detail="лес растёт"),
        ])
        (entry,) = model.entries
        assert isinstance(entry, _RowEntry)
        assert set(type(entry).__slots__) == {
            "event_id", "caption", "detail", "token_key", "flags",
            "kind", "depth", "has_children", "expanded", "is_last_sibling",
        }
        assert entry.detail == "лес растёт"
        assert not hasattr(entry, "__dict__")


class TestTreeDelivery:
    """NRI-0023 task 5.2 (design Д6): expansion is the delivery the view must
    feel as motion, not as a rewind. Children arriving/leaving ride
    ``rowsInserted``/``rowsRemoved`` (the ListView then runs its штатные
    add/displace transitions and never re-lays the reading position), the
    parent row that STAYS while its flag flips rides a scoped
    ``dataChanged`` over the EXPANDED role, and only real content moves fall
    back to the full reset."""

    PARENT = _Event(1, date(1200, 1, 5), date(1200, 1, 9), "Родитель")
    CHILD = _Event(2, date(1200, 1, 6), None, "Ребёнок", parent_id=1)
    PLAIN = _Event(3, date(1200, 2, 1), None, "Постороннее")

    def _spies(self, model):
        resets: list = []
        inserts: list = []
        removes: list = []
        changes: list = []
        model.modelReset.connect(lambda: resets.append(1))
        model.rowsInserted.connect(
            lambda parent, first, last: inserts.append((first, last))
        )
        model.rowsRemoved.connect(
            lambda parent, first, last: removes.append((first, last))
        )
        model.dataChanged.connect(
            lambda top, bottom, roles=None: changes.append(
                (top.row(), bottom.row(), list(roles or []))
            )
        )
        return resets, inserts, removes, changes

    def test_expand_delivers_the_children_as_insertion(self):
        model = TimelineRowModel()
        model.rebuild(build_rows([self.PARENT, self.CHILD, self.PLAIN]))
        assert [entry.event_id for entry in model.entries] == [1, 3]
        resets, inserts, removes, changes = self._spies(model)

        expanded = {self.PARENT.id}
        model.rebuild(
            build_rows([self.PARENT, self.CHILD, self.PLAIN], expanded=expanded),
            expanded=expanded,
        )

        assert inserts == [(1, 1)]  # the child lands between the two old rows
        assert removes == []
        assert resets == []  # …and the view is NOT rewound
        # The staying parent's chevron state rides the scoped repaint.
        assert changes == [(0, 0, [model.EXPANDED_ROLE])]
        assert [entry.event_id for entry in model.entries] == [1, 2, 3]
        assert _field(model, 1, model.KIND_ROLE) == "event"
        assert _field(model, 1, model.DEPTH_ROLE) == 1

    def test_collapse_delivers_the_children_as_removal(self):
        expanded = {self.PARENT.id}
        model = TimelineRowModel()
        model.rebuild(
            build_rows([self.PARENT, self.CHILD, self.PLAIN], expanded=expanded),
            expanded=expanded,
        )
        resets, inserts, removes, changes = self._spies(model)

        model.rebuild(build_rows([self.PARENT, self.CHILD, self.PLAIN]))

        assert removes == [(1, 1)]
        assert inserts == []
        assert resets == []
        assert changes == [(0, 0, [model.EXPANDED_ROLE])]
        assert [entry.event_id for entry in model.entries] == [1, 3]

    def test_one_more_child_stays_an_insertion_and_repaints_moved_flags(self):
        """NRI-0023 task 11.1 (design Д11): growing an OPEN group from one
        child to two must stay a pure insertion (the view animates, never
        rewinds) even though the staying child's LAST-SIBLING flag flips with
        it — the alignment ignores both moving scalars, and each moved flag
        reaches the delegates through its own scoped ``dataChanged``."""
        first = self.CHILD
        second = _Event(4, date(1200, 1, 7), None, "Второй", parent_id=1)
        one = [self.PARENT, first]
        two = [self.PARENT, first, second]
        model = TimelineRowModel()
        model.rebuild(build_rows(one, expanded={1}), expanded={1})
        assert [entry.event_id for entry in model.entries] == [1, 2]
        assert model.entries[1].is_last_sibling is True
        resets, inserts, removes, changes = self._spies(model)

        model.rebuild(build_rows(two, expanded={1}), expanded={1})

        assert resets == []
        assert inserts == [(2, 2)]  # the second child lands under the first
        assert removes == []
        # The staying first child lost its closing flag (the parent's open
        # flag did not move — the group was open already) — the repaint
        # names exactly the role that moved, on exactly the row it moved on.
        assert changes == [(1, 1, [model.IS_LAST_SIBLING_ROLE])]
        assert [entry.is_last_sibling for entry in model.entries] == [
            False, False, True
        ]

        # Collapsing that group then moves the OTHER scalar the same way:
        # pure removal, one scoped repaint of the flipped chevron state.
        resets.clear(), inserts.clear(), removes.clear(), changes.clear()
        model.rebuild(build_rows(two))
        assert removes == [(1, 2)]
        assert inserts == [] and resets == []
        assert changes == [(0, 0, [model.EXPANDED_ROLE])]

    def test_flag_flip_without_children_to_show_is_a_pure_repaint(self):
        """Expanding a parent whose children no window shows changes one
        scalar on one row: no reset, no move — just the chevron repaint."""
        window = (date(1200, 1, 5), date(1200, 1, 5))  # the child starts later
        rows = build_rows([self.PARENT, self.CHILD], window)
        model = TimelineRowModel()
        model.rebuild(rows)  # collapsed
        resets, inserts, removes, changes = self._spies(model)

        model.rebuild(rows, expanded={self.PARENT.id})

        assert (resets, inserts, removes) == ([], [], [])
        assert changes == [(0, 0, [model.EXPANDED_ROLE])]
        assert model.entries[0].expanded is True

    def test_identical_rebuild_delivers_nothing(self):
        """The degenerate re-delivery (the memo makes it rare, not wrong):
        the same rows with the same expanded set move no signal at all."""
        rows = build_rows([self.PARENT, self.CHILD, self.PLAIN])
        model = TimelineRowModel()
        model.rebuild(rows)
        resets, inserts, removes, changes = self._spies(model)

        model.rebuild(rows)

        assert (resets, inserts, removes, changes) == ([], [], [], [])
        assert model.rowCount() == 2

    def test_stub_row_is_delivered_inert(self):
        """Spec «Окно фильтрации и пустое состояние»: the parent stub carries
        its kind, no dates in the caption, no type token, no selectable flag —
        and no open state even though the sample holds children for it."""
        far_parent = _Event(1, date(1200, 1, 1), date(1200, 1, 2), "Родитель")
        orphan = _Event(2, date(1200, 1, 6), None, "Ребёнок", parent_id=1)
        window = (date(1200, 1, 6), date(1200, 1, 6))  # the parent's interval
        rows = build_rows([far_parent, orphan], window)  # ended days before
        assert [(row.kind, row.event_id) for row in rows] == [("stub", 1), ("event", 2)]
        model = _model_of(rows, expanded={1})  # the set names even a stub
        assert _field(model, 0, model.FLAGS_ROLE) == {"selectable": False, "isNow": False}
        assert _field(model, 0, model.KIND_ROLE) == "stub"
        assert _field(model, 0, model.CAPTION_ROLE) == "Родитель"
        assert _field(model, 0, model.TOKEN_KEY_ROLE) is None
        assert _field(model, 0, model.DETAIL_ROLE) == ""
        assert _field(model, 0, model.HAS_CHILDREN_ROLE) is True
        # Only a real event row can wear the open state (the delegate paints
        # no chevron on a stub whatever this slot says).
        assert _field(model, 0, model.EXPANDED_ROLE) is False
        assert _field(model, 1, model.EXPANDED_ROLE) is False
