"""Unit tests for ``TimelineRowModel`` (simplify-event-timeline-flat-list 2.2).

The model is the sole delivery channel of the FLAT rows to the QML island
(design D2 / spec «Питание QML-списков списочной моделью»): the simplified
row scalars (``event_id``, ``caption``, ``detail``, ``token_key``, ``flags`` —
only ``selectable``), reset on rebuild and the empty set — asserted over REAL
``build_rows`` output plus hand-made :class:`Row` records pinning the caption
and the description line of a typed, an untyped and an open row.
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

    def __init__(self, id_, start, end, name, color_index=None, description=None):
        self.id = id_
        self.start_date = start
        self.end_date = end
        self.name = name
        if description is not None:
            self.description = description
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


def _model_of(rows):
    model = TimelineRowModel()
    model.rebuild(rows)
    return model


def _field(model, row, role):
    return model.data(model.index(row), role)


class TestRoleContract:
    def test_role_names_exposed(self):
        """The QML binding contract: the five declared role names (design D2 —
        the ladder's kind/day/count roles retired with the ladder; ``detail``
        is the row's description line)."""
        names = set(TimelineRowModel().roleNames().values())
        assert names == {b"eventId", b"caption", b"detail", b"tokenKey", b"flags"}


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
        assert _field(model, 0, model.FLAGS_ROLE) == {"selectable": True}
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
        assert _field(model, 0, model.FLAGS_ROLE) == {"selectable": True}

    def test_only_the_flag_key_set_selectable_on_every_row(self):
        """QML never reads an undefined flag — and the ladder's
        drillable/windowable/etc. vocabulary is gone (design D2)."""
        model = _model_of(build_rows([
            _Event(1, date(1200, 1, 1), date(1200, 1, 2), "closed", color_index=3),
            _Event(2, date(1200, 1, 3), None, "open"),
        ]))
        for i in range(model.rowCount()):
            assert set(_field(model, i, model.FLAGS_ROLE)) == {"selectable"}


class TestGetConvenience:
    def test_get_hits_the_flat_row_scalars(self):
        """``get`` is the island's hit-test convenience: the simplified row's
        scalars keyed by role name."""
        model = _model_of(build_rows([
            _Event(7, date(1200, 3, 1), None, "Слух", color_index=5)
        ]))
        row = model.get(0)
        assert set(row) == {"eventId", "caption", "detail", "tokenKey", "flags"}
        assert row["eventId"] == 7
        assert row["caption"] == "01 Март 1200 — ∞ · Слух"
        assert row["detail"] == ""
        assert row["tokenKey"] == "color.chart.5"
        assert row["flags"] == {"selectable": True}

    def test_get_misses_answer_empty(self):
        model = _model_of(build_rows([
            _Event(1, date(1200, 1, 1), date(1200, 1, 1), "x")
        ]))
        assert model.get(-1) == {}
        assert model.get(1) == {}


class TestRebuildAndEmpty:
    def test_fresh_model_is_empty(self):
        model = TimelineRowModel()
        assert model.rowCount() == 0
        assert model.data(model.index(0), model.EVENT_ID_ROLE) is None
        assert model.entries == ()

    def test_rebuild_replaces_rows_and_fires_reset(self):
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
        assert len(resets) == 2  # every re-modelling is a reset

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
        event source object never rides along."""
        model = _model_of([
            Row(event_id=1, start=date(1200, 1, 1), end=None, name="Open",
                token_key=None, caption="01 Январь 1200 — ∞ · Open",
                detail="лес растёт"),
        ])
        (entry,) = model.entries
        assert isinstance(entry, _RowEntry)
        assert set(type(entry).__slots__) == {
            "event_id", "caption", "detail", "token_key", "flags"
        }
        assert entry.detail == "лес растёт"
        assert not hasattr(entry, "__dict__")
