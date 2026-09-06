"""Unit tests for the Qt-free flat row core (simplify-event-timeline-flat-list 1.2).

The ladder's row vocabulary, geometry and gesture helpers retired with the
ladder; what remains in ``timeline_rows`` is the flat «event → one row»
contract: ``build_rows(events, window)`` filters by window overlap and sorts
``(start_date, id)``. The module must import and run without a QApplication,
enforced by this file being plain units (no qtbot, no Qt imports anywhere).
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.presentation.utils.date_utils import get_custom_months, set_custom_months
from app.presentation.views.timeline_rows import (
    DETAIL_MAX_CHARS,
    OPEN_END_MARK,
    Row,
    build_rows,
    row_detail,
)


# ── helpers ───────────────────────────────────────────────────────────────────

class _Ev:
    """Minimal duck-typed event-like object (id/start/end/name [+event_type,
    +description])."""

    def __init__(self, id, start_date, end_date, name, event_type=None,
                 description=None):
        self.id = id
        self.start_date = start_date
        self.end_date = end_date
        self.name = name
        self.event_type = event_type
        if description is not None:
            self.description = description


def _event(id_, start, end, name, color_index=None, description=None):
    event_type = (
        None if color_index is None else type("T", (), {"color_index": color_index})()
    )
    return _Ev(id_, start, end, name, event_type=event_type, description=description)


def _description(characteristics="", backstory=""):
    return SimpleNamespace(characteristics=characteristics, backstory=backstory)


@pytest.fixture(autouse=True)
def _default_game_months():
    """Captions are game-calendar text — pin the default month map around each
    unit regardless of what other suites left in the shared module state."""
    saved = get_custom_months()
    set_custom_months(None)
    yield
    set_custom_months(saved)


# ── module purity ─────────────────────────────────────────────────────────────

def test_module_imports_without_qt_application():
    """The pure core carries no Qt imports (design D1) and runs plain units."""
    import app.presentation.views.timeline_rows as rows_mod

    source = open(rows_mod.__file__, encoding="utf-8").read()
    assert "PySide6" not in source  # dataclass/typing only
    event = _event(1, date(1200, 1, 1), None, "event-1")
    assert build_rows([event])  # the flat core needs no QApplication


# ── one event = one row ───────────────────────────────────────────────────────

def test_multi_day_event_gets_exactly_one_row():
    """Spec «Одно событие — одна строка»: 3–10 марта — одна строка, не десять."""
    event = _event(1, date(1200, 3, 3), date(1200, 3, 10), "Фестиваль")
    rows = build_rows([event])
    assert rows == [Row(
        event_id=1,
        start=date(1200, 3, 3),
        end=date(1200, 3, 10),
        name="Фестиваль",
        token_key=None,
        caption="03 Март 1200 — 10 Март 1200 · Фестиваль",
    )]


def test_each_event_of_a_sample_gets_its_own_single_row():
    events = [
        _event(1, date(1200, 5, 1), date(1200, 6, 20), "long"),
        _event(2, date(1200, 5, 10), date(1200, 5, 12), "short"),
        _event(3, date(1200, 7, 1), None, "open"),
    ]
    rows = build_rows(events)
    assert [row.event_id for row in rows] == [1, 2, 3]
    assert len({row.event_id for row in rows}) == len(rows)


# ── captions: game calendar and the open-end mark ─────────────────────────────

def test_open_event_caption_shows_the_infinity_mark_not_an_invented_end():
    """Spec «Бессрочная строка»: `5 мар … — ∞ · имя`."""
    row, = build_rows([_event(1, date(1200, 3, 5), None, "Слух")])
    assert row.end is None
    assert OPEN_END_MARK == "∞"
    assert row.caption == "05 Март 1200 — ∞ · Слух"


def test_captions_follow_the_game_month_names():
    """Spec «Игровые месяцы»: row text uses the live custom month map."""
    set_custom_months({3: "Медвежарь"})
    row, = build_rows([_event(1, date(1200, 3, 5), date(1200, 3, 9), "Имя")])
    assert row.caption == "05 Медвежарь 1200 — 09 Медвежарь 1200 · Имя"


# ── type token (duck-typed) ───────────────────────────────────────────────────

def test_token_key_mirrors_the_type_color_index_and_untyped_rows_are_none():
    typed = _event(1, date(1200, 1, 1), None, "typed", color_index=4)
    untyped = _event(2, date(1200, 1, 2), None, "untyped")
    by_id = {row.event_id: row for row in build_rows([typed, untyped])}
    assert by_id[1].token_key == "color.chart.4"
    assert by_id[2].token_key is None


# ── the description line (spec «Плоский список событий») ──────────────────────


def test_row_carries_the_characteristics_as_its_second_line():
    """The description glimpse rides the row it belongs to."""
    row, = build_rows([_event(
        1, date(1200, 1, 1), None, "Совет",
        description=_description(characteristics="Собрались втроем"),
    )])
    assert row.detail == "Собрались втроем"


def test_backstory_is_the_fallback_only_without_characteristics():
    """Characteristics first, backstory when there is nothing else."""
    rows = build_rows([
        _event(1, date(1200, 1, 1), None, "both",
               description=_description(characteristics="главное", backstory="дальше")),
        _event(2, date(1200, 1, 2), None, "backstory only",
               description=_description(characteristics="   ", backstory="дальше")),
    ])
    assert [row.detail for row in rows] == ["главное", "дальше"]


def test_missing_description_leaves_the_row_without_a_second_line():
    """A double without the attribute and an empty description both paint one
    line (the row drops back to ``rowHeight`` in the view)."""
    rows = build_rows([
        _event(1, date(1200, 1, 1), None, "no attribute"),
        _event(2, date(1200, 1, 2), None, "empty", description=_description()),
    ])
    assert [row.detail for row in rows] == ["", ""]


def test_detail_collapses_newlines_and_runs_of_spaces():
    """The glimpse is ONE logical line whatever the source holds; the delegate
    owns where it wraps."""
    raw = "  первая   строка\n\nвторая\tстрока  "
    assert row_detail(_event(1, date(1200, 1, 1), None, "x",
                             description=_description(characteristics=raw))) \
        == "первая строка вторая строка"


def test_detail_is_bounded_to_the_glimpse_budget():
    """The row is a digest, the card owns the full text: the bounded budget,
    cut on a word-friendly edge and marked with an ellipsis."""
    long_text = " слово" * 100
    detail = row_detail(_event(1, date(1200, 1, 1), None, "x",
                               description=_description(characteristics=long_text)))
    assert len(detail) <= DETAIL_MAX_CHARS + 1
    assert detail.endswith("…")
    assert detail == " ".join(long_text.split())[:DETAIL_MAX_CHARS].rstrip() + "…"


def test_row_detail_is_the_same_text_the_row_carries():
    """``row_detail`` is the single description rule — the ViewModel's rebuild
    key reads exactly this text, so the two may never diverge."""
    event = _event(1, date(1200, 1, 1), None, "x",
                   description=_description(backstory="память"))
    assert build_rows([event])[0].detail == row_detail(event)


# ── window intersection rule (design D1) ──────────────────────────────────────

_WINDOW = (date(1200, 8, 10), date(1200, 8, 20))


def test_event_crossing_the_window_left_edge_is_visible():
    """Spec «Пересекающее событие видно в окне»: 1 июля — 5 сентября при окне
    10–20 августа показано своей единственной строкой."""
    event = _event(1, date(1200, 7, 1), date(1200, 9, 5), "Через окно")
    assert [row.event_id for row in build_rows([event], _WINDOW)] == [1]


def test_event_ending_before_the_window_is_hidden():
    event = _event(1, date(1200, 7, 1), date(1200, 8, 9), "до окна")
    assert build_rows([event], _WINDOW) == []


def test_event_starting_after_the_window_is_hidden():
    event = _event(1, date(1200, 8, 21), date(1200, 9, 1), "после окна")
    assert build_rows([event], _WINDOW) == []


def test_open_event_started_before_the_window_stays_visible():
    """Spec «Бессрочное видно в окне после начала»."""
    event = _event(1, date(1200, 1, 1), None, "бессрочное")
    rows = build_rows([event], _WINDOW)
    assert [row.event_id for row in rows] == [1]
    assert rows[0].caption == "01 Январь 1200 — ∞ · бессрочное"


def test_event_touching_the_window_border_is_visible():
    """Границы включаются: окончание ровно в start окна и начало ровно в end."""
    ends_on_start = _event(1, date(1200, 8, 1), _WINDOW[0], "касание слева")
    starts_on_end = _event(2, _WINDOW[1], date(1200, 9, 1), "касание справа")
    assert [row.event_id for row in build_rows([ends_on_start, starts_on_end], _WINDOW)] == [1, 2]


def test_one_day_window_keeps_crossing_events_only():
    day = date(1200, 8, 14)
    inside = _event(1, day, day, "в этот день")
    crossing = _event(2, date(1200, 7, 1), date(1200, 9, 1), "через день")
    missed = _event(3, date(1200, 8, 13), date(1200, 8, 13), "накануне")
    assert [row.event_id for row in build_rows([inside, crossing, missed], (day, day))] == [2, 1]


@pytest.mark.parametrize("window", [None, (None, None), (date(1200, 8, 10), None), (None, date(1200, 8, 20))])
def test_empty_window_shows_everything(window):
    """«Все дни»: None и частичная пара — не фильтр."""
    events = [
        _event(1, date(1200, 1, 1), date(1200, 2, 1), "рано"),
        _event(2, date(1200, 9, 1), None, "поздно"),
    ]
    assert len(build_rows(events, window)) == 2


# ── ordering ──────────────────────────────────────────────────────────────────

def test_rows_sort_by_start_date_then_id_regardless_of_input_order():
    """Spec «Порядок строк»: одинаковый день — по id; дни — по возрастанию."""
    events = [
        _event(9, date(1200, 3, 5), None, "второе-в-дне"),
        _event(4, date(1200, 3, 5), None, "первое-в-дне"),
        _event(7, date(1200, 1, 1), None, "ранний"),
        _event(2, date(1200, 12, 31), None, "поздний"),
    ]
    assert [(row.start, row.event_id) for row in build_rows(events)] == [
        (date(1200, 1, 1), 7),
        (date(1200, 3, 5), 4),
        (date(1200, 3, 5), 9),
        (date(1200, 12, 31), 2),
    ]


def test_window_filters_but_never_reorders():
    hidden = _event(1, date(1200, 1, 1), date(1200, 1, 2), "вне окна")
    late = _event(2, date(1200, 8, 15), None, "в окне")
    early = _event(3, date(1200, 7, 1), date(1200, 8, 10), "в окне раньше")
    assert [row.event_id for row in build_rows([late, hidden, early], _WINDOW)] == [3, 2]


# ── empty results ─────────────────────────────────────────────────────────────

def test_empty_sample_gives_an_empty_list():
    assert build_rows([]) == []
    assert build_rows([], _WINDOW) == []


def test_window_that_no_event_crosses_gives_an_empty_list():
    events = [
        _event(1, date(1200, 1, 1), date(1200, 2, 1), "рано"),
        _event(2, date(1200, 9, 1), date(1200, 9, 5), "поздно"),
    ]
    assert build_rows(events, _WINDOW) == []
