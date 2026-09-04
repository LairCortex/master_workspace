"""Unit tests for ``TimelineRowModel`` (Q2.5a task 1.1).

The model is the sole delivery channel of ladder rows to the QML island
(spec «Питание QML-списков списочной моделью»): roles, counters, reset on
rebuild and the empty set — asserted over REAL ``build_rows`` output plus
hand-made rows pinning the caption of every position kind.
"""
from datetime import date

from PySide6.QtCore import QModelIndex, Qt

from app.presentation.viewmodels.timeline_viewmodel import (
    TimelineRowModel,
    _RowEntry,
)
from app.presentation.views.timeline_rows import (
    DayHeaderRow,
    EmptyDayRow,
    EventRow,
    GapCollapsedRow,
    PeriodCardRow,
    PeriodHeaderRow,
    ScaleUnit,
    build_rows,
    header_caption,
)


class _Event:
    """Plain event double — the core's duck-typed input shape."""

    def __init__(self, id_, start, end, name, color_index=None):
        self.id = id_
        self.start_date = start
        self.end_date = end
        self.name = name
        if color_index is None:
            self.event_type = None
        else:
            class _T:
                pass
            t = _T()
            t.color_index = color_index
            self.event_type = t


def _model_of(rows):
    model = TimelineRowModel()
    model.rebuild(rows)
    return model


def _field(model, row, role):
    return model.data(model.index(row), role)


class TestRoleContract:
    def test_role_names_exposed(self):
        """The QML binding contract: the seven declared role names."""
        names = set(TimelineRowModel().roleNames().values())
        assert names == {
            b"kind", b"eventId", b"day", b"caption",
            b"tokenKey", b"count", b"flags",
        }


class TestEntriesFromBuildRows:
    def test_event_card_entries_carry_all_roles(self):
        events = [
            _Event(1, date(1200, 1, 5), date(1200, 1, 7), "Council", color_index=2),
            _Event(2, date(1200, 1, 6), None, "Prophecy"),  # open — «бессрочно»
        ]
        rows = build_rows(events, window=(date(1200, 1, 5), date(1200, 1, 7)))
        model = _model_of(rows)
        assert model.rowCount() == len(rows)

        cards = [i for i in range(model.rowCount())
                 if _field(model, i, model.KIND_ROLE) == "event"]
        # Per day, cards in (start_date, id) order: 01-05 council; 01-06 and
        # 01-07 council + prophecy (the open event duplicates per day).
        assert [rows[i].event_id for i in cards] == [1, 1, 2, 1, 2]

        first = cards[0]
        assert _field(model, first, model.EVENT_ID_ROLE) == 1
        assert _field(model, first, model.DAY_ROLE) == date(1200, 1, 5)
        assert _field(model, first, model.CAPTION_ROLE) == "Council"
        assert _field(model, first, model.TOKEN_KEY_ROLE) == "color.chart.2"
        assert _field(model, first, model.COUNT_ROLE) == 0
        flags = _field(model, first, model.FLAGS_ROLE)
        assert flags["selectable"] is True
        assert flags["draggable"] is True
        assert flags["open"] is False
        # The dynamic tooltip body is ready Python text (game dates included).
        assert flags["summary"].startswith("Council\n")

        open_card = cards[2]  # the «Prophecy» card of its first day
        assert _field(model, open_card, model.EVENT_ID_ROLE) == 2
        assert _field(model, open_card, model.CAPTION_ROLE) == "Prophecy · бессрочно"
        assert _field(model, open_card, model.TOKEN_KEY_ROLE) is None
        assert _field(model, open_card, model.FLAGS_ROLE)["open"] is True
        # Untyped card: no token — the delegate paints no type dot.
        assert "Prophecy\n" in _field(model, open_card, model.FLAGS_ROLE)["summary"]

    def test_day_header_entries_carry_ready_captions(self):
        events = [_Event(1, date(1200, 1, 5), date(1200, 1, 5), "Fair")]
        rows = build_rows(events, window=(date(1200, 1, 5), date(1200, 1, 5)))
        model = _model_of(rows)
        assert _field(model, 0, model.KIND_ROLE) == "dayHeader"
        assert _field(model, 0, model.CAPTION_ROLE) == header_caption(rows[0])
        assert _field(model, 0, model.EVENT_ID_ROLE) is None
        assert _field(model, 0, model.FLAGS_ROLE)["summary"] is None


class TestEveryKind:
    """Hand-made rows pin the caption/counter/flags of each position kind."""

    def _rows(self):
        return [
            DayHeaderRow(date=date(1200, 3, 1)),
            EventRow(date=date(1200, 3, 1), event_id=7, start=date(1200, 2, 20),
                     end=date(1200, 3, 10), name="War", token_key="color.chart.1"),
            EmptyDayRow(date=date(1200, 3, 2)),
            GapCollapsedRow(date=date(1200, 3, 3), end=date(1200, 3, 30)),
            PeriodHeaderRow(date=date(1200, 4, 1), level=ScaleUnit.MONTH),
            PeriodCardRow(date=date(1200, 4, 1), level=ScaleUnit.MONTH, count=4),
            PeriodCardRow(date=date(1200, 5, 1), level=ScaleUnit.MONTH, count=0),
        ]

    def test_kinds(self):
        model = _model_of(self._rows())
        kinds = [_field(model, i, model.KIND_ROLE) for i in range(model.rowCount())]
        assert kinds == [
            "dayHeader", "event", "emptyDay", "gap",
            "periodHeader", "periodCard", "periodCard",
        ]

    def test_captions_and_counters(self):
        model = _model_of(self._rows())
        assert _field(model, 2, model.CAPTION_ROLE) == "+  нет события"
        gap = _field(model, 3, model.CAPTION_ROLE)
        assert gap.startswith("нет событий: ") and " — " in gap
        assert _field(model, 4, model.CAPTION_ROLE) == header_caption(self._rows()[4])
        assert _field(model, 5, model.CAPTION_ROLE) == "4 события"
        assert _field(model, 5, model.COUNT_ROLE) == 4
        assert _field(model, 5, model.FLAGS_ROLE)["empty"] is False
        assert _field(model, 6, model.CAPTION_ROLE) == "нет событий"
        assert _field(model, 6, model.COUNT_ROLE) == 0
        assert _field(model, 6, model.FLAGS_ROLE)["empty"] is True
        # The period card drills, selects never (draggable off, selectable off).
        period_flags = _field(model, 5, model.FLAGS_ROLE)
        assert period_flags["drillable"] is True
        assert period_flags["selectable"] is False
        assert period_flags["draggable"] is False
        # The empty day creates; the collapsed gap opens «Выбор даты».
        assert _field(model, 2, model.FLAGS_ROLE)["creatable"] is True
        assert _field(model, 3, model.FLAGS_ROLE)["windowable"] is True

    def test_ru_counter_phrases(self):
        for count, phrase in ((1, "событие"), (2, "события"), (5, "событий"),
                              (11, "событий"), (21, "событие"), (111, "событий")):
            model = _model_of([
                PeriodCardRow(date=date(1200, 1, 1), level=ScaleUnit.YEAR,
                              count=count)
            ])
            assert _field(model, 0, model.CAPTION_ROLE) == f"{count} {phrase}"

    def test_flag_key_set_is_full_on_every_row(self):
        """QML never reads an undefined flag: every entry carries all keys."""
        model = _model_of(self._rows())
        expected = {"selectable", "draggable", "drillable", "creatable",
                    "windowable", "open", "empty", "summary"}
        for i in range(model.rowCount()):
            assert set(_field(model, i, model.FLAGS_ROLE)) == expected


class TestRebuildAndEmpty:
    def test_fresh_model_is_empty(self):
        model = TimelineRowModel()
        assert model.rowCount() == 0
        assert model.data(model.index(0), model.KIND_ROLE) is None
        assert model.entries == ()

    def test_rebuild_replaces_rows_and_fires_reset(self):
        model = TimelineRowModel()
        resets: list[int] = []
        model.modelReset.connect(lambda: resets.append(1))

        model.rebuild([DayHeaderRow(date=date(1200, 1, 1))])
        assert model.rowCount() == 1
        assert _field(model, 0, model.KIND_ROLE) == "dayHeader"

        model.rebuild([
            DayHeaderRow(date=date(1200, 1, 2)),
            EmptyDayRow(date=date(1200, 1, 2)),
        ])
        assert model.rowCount() == 2  # counters follow the re-model
        assert _field(model, 0, model.CAPTION_ROLE) == header_caption(
            DayHeaderRow(date=date(1200, 1, 2))
        )
        assert len(resets) == 2  # every re-modelling is a reset

        model.rebuild([])
        assert model.rowCount() == 0
        assert model.data(model.index(0), model.KIND_ROLE) is None
        assert len(resets) == 3

    def test_out_of_range_and_invalid_index_answer_none(self):
        model = _model_of([DayHeaderRow(date=date(1200, 1, 1))])
        assert model.data(model.index(5), model.KIND_ROLE) is None
        assert model.data(QModelIndex(), model.CAPTION_ROLE) is None
        assert model.rowCount(model.index(0)) == 0  # rows have no children
        # Unclaimed Qt roles (Display/Edit/…) answer None — the delegates read
        # the model exclusively through the seven custom roles.
        assert model.data(model.index(0), Qt.ItemDataRole.DisplayRole) is None
        assert model.data(model.index(0), Qt.ItemDataRole.EditRole) is None

    def test_get_hits_the_entry_map_and_misses_answer_empty(self):
        """``get`` is the island's hit-test convenience: the whole role map for
        a row, an empty map out of range (QML treats it as “no row there”)."""
        model = _model_of([DayHeaderRow(date=date(1200, 1, 1))])
        row = model.get(0)
        assert set(row) == {
            "kind", "eventId", "day", "caption", "tokenKey", "count", "flags",
        }
        assert row["day"] == date(1200, 1, 1)
        assert model.get(-1) == {}
        assert model.get(1) == {}

    def test_entries_are_slots_scalars_only(self):
        """The delivered structs are ``__slots__`` records (design D2) — the
        event source object never rides along (task 1.3 support)."""
        model = _model_of([
            EventRow(date=date(1200, 1, 1), event_id=1, start=date(1200, 1, 1),
                     end=None, name="Open", token_key=None),
        ])
        (entry,) = model.entries
        assert isinstance(entry, _RowEntry)
        assert set(type(entry).__slots__) == {
            "kind", "event_id", "day", "caption", "token_key", "count", "flags"
        }
        assert not hasattr(entry, "__dict__")
