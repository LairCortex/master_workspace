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

from app.domain.game_calendar import (
    CalendarSpec,
    CustomCalendar,
    InvalidGameDateError,
    MonthDay,
    MonthSpec,
    StandardCalendar,
    current_calendar,
    reset_current_calendar,
    set_current_calendar,
)
from app.presentation.views.timeline_rows import (
    DETAIL_MAX_CHARS,
    OPEN_END_MARK,
    ROW_EVENT,
    ROW_STUB,
    Row,
    build_rows,
    event_parent_id,
    event_time_minutes,
    row_detail,
    window_contains,
)


# ── helpers ───────────────────────────────────────────────────────────────────

class _Ev:
    """Minimal duck-typed event-like object (id/start/end/name [+event_type,
    +description, +start_bc/end_bc, +parent_id/start_time_raw])."""

    def __init__(self, id, start_date, end_date, name, event_type=None,
                 description=None, start_bc=False, end_bc=False,
                 parent_id=None, start_time_raw=None):
        self.id = id
        self.start_date = start_date
        self.end_date = end_date
        self.name = name
        self.event_type = event_type
        self.start_bc = start_bc
        self.end_bc = end_bc
        if description is not None:
            self.description = description
        # NRI-0023 tree fields — set only when given, so the attribute-less
        # legacy shape stays constructible and keeps reading «plain event».
        if parent_id is not None:
            self.parent_id = parent_id
        if start_time_raw is not None:
            self.start_time_raw = start_time_raw


def _event(id_, start, end, name, color_index=None, description=None,
           start_bc=False, end_bc=False, parent_id=None, start_time_raw=None):
    event_type = (
        None if color_index is None else type("T", (), {"color_index": color_index})()
    )
    return _Ev(id_, start, end, name, event_type=event_type, description=description,
               start_bc=start_bc, end_bc=end_bc,
               parent_id=parent_id, start_time_raw=start_time_raw)


def _description(characteristics="", backstory=""):
    return SimpleNamespace(characteristics=characteristics, backstory=backstory)


@pytest.fixture(autouse=True)
def _default_game_months():
    """Captions are game-calendar text — pin the «Стандартный» preset around
    each unit regardless of what other suites left in the shared process
    state, then hand the previously active calendar object back."""
    saved = current_calendar()
    reset_current_calendar()
    yield
    set_current_calendar(saved)


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
    """Spec «Игровые месяцы»: row text uses the active calendar's names."""
    set_current_calendar(StandardCalendar(month_names={3: "Медвежарь"}))
    row, = build_rows([_event(1, date(1200, 3, 5), date(1200, 3, 9), "Имя")])
    assert row.caption == "05 Медвежарь 1200 — 09 Медвежарь 1200 · Имя"


def test_caption_carries_the_chosen_time_after_the_start_date():
    # NRI-0023 task 8.1 (spec event-time «Время в строке»): the ladder row
    # prints its start through the shared surface helper — the time tail
    # comes right after the start date, the end stays a plain day; a row
    # without the domain face keeps the old caption (the None pin above).
    from app.domain.time_of_day import TimeOfDay

    event = _event(1, date(1200, 3, 5), None, "Слух", start_time_raw=9 * 60 + 5)
    event.start_time = TimeOfDay(9, 5)
    row, = build_rows([event])
    assert row.caption == "05 Март 1200, 09:05 — ∞ · Слух"


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


# ── eras: shared chronological key (add-era-aware-dates 4.2) ──────────────────

def test_event_without_era_attributes_reads_as_our_era():
    """Doubles without start_bc/end_bc at all (old-version rows) read «н.э.»."""
    legacy = SimpleNamespace(
        id=1, start_date=date(1200, 1, 1), end_date=None, name="ancient"
    )
    row, = build_rows([legacy])
    assert (row.start_bc, row.end_bc) == (False, False)


def test_bc_rows_precede_our_era_rows_regardless_of_year_numbers():
    """Spec «Смешанная сортировка»: 500/1 до н.э. раньше 1 г. н.э. и 2026 —
    numbers inside the BC era run down, the key runs forward (design D2)."""
    events = [
        _event(20, date(2026, 1, 1), None, "наши дни"),
        _event(1, date(1, 1, 1), None, "1 год до н.э.", start_bc=True),
        _event(2, date(500, 6, 1), None, "500 лет до н.э.", start_bc=True),
        _event(3, date(1, 1, 1), None, "наша эра"),
    ]
    assert [row.event_id for row in build_rows(events)] == [2, 1, 3, 20]


def test_days_and_months_run_forward_inside_the_bc_year():
    """Design D2: within a BC year days go naturally (5 марта 44 г. до н.э.
    позже 1 марта того же года), а годы считаются вниз к 1 г. до н.э."""
    events = [
        _event(1, date(44, 3, 15), None, "середина", start_bc=True),
        _event(2, date(43, 12, 31), None, "следующий bc-год", start_bc=True),
        _event(3, date(44, 3, 5), None, "начало", start_bc=True),
        _event(4, date(45, 1, 1), None, "предыдущий bc-год", start_bc=True),
    ]
    assert [row.event_id for row in build_rows(events)] == [4, 3, 1, 2]


def test_same_moment_breaks_tie_by_id_even_in_the_bc_era():
    """Spec «Порядок строк» + «Единый хронологический порядок»: одинаковый
    момент (та же дата той же эры) — порядок по id."""
    events = [
        _event(9, date(44, 3, 5), None, "второе", start_bc=True),
        _event(4, date(44, 3, 5), None, "первое", start_bc=True),
    ]
    assert [(row.start, row.start_bc, row.event_id) for row in build_rows(events)] == [
        (date(44, 3, 5), True, 4),
        (date(44, 3, 5), True, 9),
    ]


def test_the_same_day_in_different_eras_is_not_a_tie():
    """1 июня до н.э. и 1 июня н.э. — разные моменты: эра решает, id ни при чём."""
    events = [
        _event(1, date(44, 6, 1), None, "наша эра"),
        _event(2, date(44, 6, 1), None, "до н.э.", start_bc=True),
    ]
    assert [row.event_id for row in build_rows(events)] == [2, 1]


def test_bc_captions_carry_the_suffix_and_rows_mirror_the_eras():
    """Spec «Годы до нашей эры на шкале»: строка показывает суффикс
    «N г. до н.э.», открытый конец по-прежнему ∞ и без эры."""
    row, = build_rows([_event(1, date(44, 3, 5), None, "Кассаций", start_bc=True)])
    assert row.caption == "05 Март 44 г. до н.э. — ∞ · Кассаций"
    assert (row.start_bc, row.end_bc) == (True, False)
    closed = build_rows([_event(
        2, date(100, 1, 1), date(70, 1, 1), "Империя",
        start_bc=True, end_bc=True,
    )])[0]
    assert closed.caption == (
        "01 Январь 100 г. до н.э. — 01 Январь 70 г. до н.э. · Империя"
    )
    assert (closed.start_bc, closed.end_bc) == (True, True)


# Mixed window across the era border: 500 г. до н.э. … 100 г. н.э.
_BORDER_WINDOW = ((date(500, 1, 1), True), (date(100, 12, 31), False))


def test_window_across_the_era_border_keeps_events_of_both_eras():
    """Spec «Границы окна через эпохи»: в окно попадают события обеих эр
    внутри диапазона."""
    inside_bc = _event(1, date(400, 5, 5), date(350, 5, 5), "эллины",
                       start_bc=True, end_bc=True)
    crossing = _event(2, date(2, 1, 1), date(50, 1, 1), "через границу")
    inside_ce = _event(3, date(60, 1, 1), date(90, 1, 1), "римляне")
    rows = build_rows([inside_ce, inside_bc, crossing], _BORDER_WINDOW)
    assert [row.event_id for row in rows] == [1, 2, 3]


def test_window_border_excludes_events_wholly_outside_it():
    """До 500 г. до н.э. и после 100 г. н.э. — вне окна; границы включаются."""
    too_old = _event(1, date(600, 1, 1), date(550, 1, 1), "слишком рано",
                     start_bc=True, end_bc=True)
    too_new = _event(2, date(101, 1, 1), date(200, 1, 1), "слишком поздно")
    on_start = _event(3, _BORDER_WINDOW[0][0], None, "касание начала",
                      start_bc=True)
    on_end = _event(4, _BORDER_WINDOW[1][0], _BORDER_WINDOW[1][0],
                    "касание конца")
    rows = build_rows([too_new, too_old, on_start, on_end], _BORDER_WINDOW)
    assert [row.event_id for row in rows] == [3, 4]


def test_open_bc_event_is_covered_by_a_later_our_era_window():
    """Spec «Бессрочное из доисторического прошлого накрыто окном н.э.»."""
    open_bc = _event(1, date(300, 1, 1), None, "вечное", start_bc=True)
    window = (date(2026, 9, 1), date(2026, 9, 30))
    assert [row.event_id for row in build_rows([open_bc], window)] == [1]


def test_bc_event_ending_before_a_bc_window_is_hidden():
    """Окно целиком в до н.э.: окончание 300 г. до н.э. раньше начала окна
    200 г. до н.э. — событие скрыто (числа лет обратили бы фильтр наизнанку)."""
    ended = _event(1, date(400, 1, 1), date(300, 1, 1), "уже кончилось",
                   start_bc=True, end_bc=True)
    window = ((date(200, 1, 1), True), (date(100, 1, 1), True))
    assert build_rows([ended], window) == []


def test_window_bounds_accept_bare_dates_and_pairs_alike():
    """A bare bound (== «н.э.», old contract) and the same bound as a pair
    filter identically."""
    event = _event(1, date(1200, 8, 15), date(1200, 8, 25), "в окне")
    bare = build_rows([event], _WINDOW)
    paired = build_rows(
        [event], ((date(1200, 8, 10), False), (date(1200, 8, 20), False))
    )
    assert [row.event_id for row in bare] == [row.event_id for row in paired] == [1]


# ── the «today» outline flag (nri-0021 task 5.1) ──────────────────────────────

_TODAY = date(1200, 8, 14)


class TestTodayOutlineFlag:
    """Spec «Обводка события, начинающегося „сегодня“»: exactly one row —
    the FIRST in sort order starting the very day of the game's «now», same
    era included — carries ``is_now``; without such an event nobody does,
    and the rule never raises on a «now» the active calendar refuses."""

    def test_two_events_started_today_mark_only_the_first_in_sort_order(self):
        """Spec «Обводится первое сегодняшнее»: при двух сегодняшних обводка
        на первом по сортировке (тот же день — порядок по id), вторая без."""
        events = [
            _event(9, _TODAY, None, "второе-в-сорте"),
            _event(4, _TODAY, date(1200, 9, 1), "первое-в-сорте"),
            _event(1, date(1200, 7, 1), None, "раньше"),
        ]
        rows = build_rows(events, now=_TODAY)
        assert [(row.event_id, row.is_now) for row in rows] == [
            (1, False), (4, True), (9, False),
        ]

    def test_no_event_starts_on_now_leaves_every_row_unmarked(self):
        """Spec «Нет сегодняшних — нет обводки»."""
        rows = build_rows(
            [
                _event(1, date(1200, 8, 13), None, "накануне"),
                _event(2, date(1200, 8, 15), None, "наследующий"),
            ],
            now=_TODAY,
        )
        assert [row.is_now for row in rows] == [False, False]

    def test_without_now_nobody_is_marked(self):
        """A VM built without the game's «now» keeps the list outline-free."""
        rows = build_rows([_event(1, _TODAY, None, "сегодняшнее")])
        assert [row.is_now for row in rows] == [False]

    def test_the_same_day_in_the_other_era_is_not_today(self):
        """Spec «Эры не путаются»: «14 августа 2090» и «14 августа 2090 г.
        до н.э.» — разные дни (тот же shared era key, что и для сортировки)."""
        rows = build_rows(
            [_event(1, date(2090, 8, 14), None, "до н.э.", start_bc=True)],
            now=date(2090, 8, 14),
        )
        assert [row.is_now for row in rows] == [False]

    def test_bc_now_marks_the_bc_row_of_the_same_numbers(self):
        """The era-positive half: «сейчас» до н.э. находит ровно своё
        до-н.-э. событие, н.э.-двойник с теми же числами обходит."""
        rows = build_rows(
            [
                _event(1, date(2090, 8, 14), None, "наша эра"),
                _event(2, date(2090, 8, 14), None, "до н.э.", start_bc=True),
            ],
            now=date(2090, 8, 14),
            now_bc=True,
        )
        assert [(row.event_id, row.is_now) for row in rows] == [(2, True), (1, False)]

    def test_flag_rides_only_the_visible_rows(self):
        """An event the window cut away leaves no outline behind (the flag
        is set on the built rows, after the window filter)."""
        rows = build_rows(
            [_event(1, _TODAY, _TODAY, "вне окна")],
            (date(1300, 1, 1), date(1300, 2, 1)),
            now=_TODAY,
        )
        assert rows == []

    def test_a_now_the_active_calendar_refuses_marks_nobody(self):
        """The Д1 seeding posture (group-4 rule): the real today seeded into
        a CUSTOM calendar may name a month that calendar does not have — the
        outline stays absent, the list never breaks."""
        set_current_calendar(CustomCalendar(CalendarSpec(
            months=(MonthSpec("Первомес", 30), MonthSpec("Второмес", 20)),
            week_names=tuple("Пн Вт Ср Чт Пт Сб Вс".split()),
        )))
        rows = build_rows(
            [_event(1, MonthDay(1200, 1, 5), None, "сентябрьского нет")],
            now=MonthDay(1200, 9, 1),
        )
        assert [(row.event_id, row.is_now) for row in rows] == [(1, False)]


# ── window containment for the «➜ Сейчас» button (nri-0021 task 5.2) ─────────


class TestWindowContains:
    """``window_contains`` is the containment twin of the crossing rule:
    «is this date one of the window's days», answered on the same era key."""

    def test_absent_or_partial_window_contains_every_date(self):
        """«Все дни» — no filter and no boundary: always inside (spec
        «„Все дни“ — всегда»)."""
        inside = window_contains(None, _TODAY, False)
        start_only = window_contains((_TODAY, None), date(1300, 1, 1), False)
        end_only = window_contains((None, _TODAY), date(1100, 1, 1), False)
        assert inside and start_only and end_only

    def test_inside_outside_and_the_borders_are_included(self):
        window = (date(1200, 8, 10), date(1200, 8, 20))
        assert window_contains(window, date(1200, 8, 14), False) is True
        assert window_contains(window, window[0], False) is True   # граница
        assert window_contains(window, window[1], False) is True   # граница
        assert window_contains(window, date(1200, 8, 21), False) is False
        assert window_contains(window, date(1200, 8, 9), False) is False

    def test_the_era_separates_the_same_numbers(self):
        """Окно целиком в до н.э.: те же числа нашей эры в него не попадают
        (total ordering of the shared key, not year arithmetic)."""
        window = ((date(500, 1, 1), True), (date(100, 12, 31), True))
        assert window_contains(window, date(300, 6, 6), True) is True
        assert window_contains(window, date(300, 6, 6), False) is False

    def test_a_date_the_calendar_refuses_raises_its_own_error(self):
        """The helper does not decide the posture — the button caller
        catches, this core just reports (design Д6)."""
        set_current_calendar(CustomCalendar(CalendarSpec(
            months=(MonthSpec("Первомес", 30), MonthSpec("Второмес", 20)),
            week_names=tuple("Пн Вт Ср Чт Пт Сб Вс".split()),
        )))
        window = (MonthDay(1200, 1, 1), MonthDay(1200, 2, 20))
        with pytest.raises(InvalidGameDateError):
            window_contains(window, MonthDay(1200, 9, 1), False)


# ── the two-level tree (NRI-0023 task 5.1, spec «Дерево событий») ─────────────


class TestTree:
    """``build_rows`` lays the events as the ladder's tree (design Д6): one
    top-level row per main event, children directly under their EXPANDED
    parent, the window-excluded parent of a shown child rendered as a name
    stub. The order of both levels is ``(start, время, id)`` — untimed rows
    precede timed ones, a full tie falls to ``id`` (spec event-time «Время
    участвует в порядке внутри дня»), mirroring the repository's SQL order."""

    PARENT = staticmethod(lambda: _event(1, date(1200, 1, 5), date(1200, 1, 9), "Поход"))

    def _sample(self):
        """Parent plus five children: one untimed (id 2), three at 09:00
        (ids 4, 5, 6) and one at 14:30 (id 3) — all on January 6."""
        return [
            _event(1, date(1200, 1, 5), date(1200, 1, 9), "Поход"),
            _event(2, date(1200, 1, 6), None, "Разведка"),  # без времени
            _event(3, date(1200, 1, 6), None, "Привал", start_time_raw=14 * 60 + 30),
            _event(4, date(1200, 1, 6), None, "Засека", start_time_raw=9 * 60),
            _event(5, date(1200, 1, 6), None, "Дозор", start_time_raw=9 * 60),
            _event(6, date(1200, 1, 6), None, "Пикет", start_time_raw=9 * 60),
        ]

    def _children(self, sample):  # attach all five to the parent
        return [sample[0]] + [
            _event(e.id, e.start_date, e.end_date, e.name,
                   start_time_raw=getattr(e, "start_time_raw", None),
                   parent_id=1)
            for e in sample[1:]
        ]

    def test_children_are_hidden_while_the_parent_is_collapsed(self):
        """Spec «Свёрнутый родитель детей прячет»: no child rows at all, and
        the parent announces itself as the one carrying a section."""
        rows = build_rows(self._children(self._sample()))
        assert [(r.kind, r.event_id, r.depth, r.parent_id) for r in rows] == [
            (ROW_EVENT, 1, 0, None)
        ]
        assert rows[0].has_children is True

    def test_expanded_parent_carries_children_directly_under_it(self):
        """Spec «Подсобытия под родителем с отступом»: children ride at depth
        1 with parent_id set, ordered (день, время, id) — untimed first, the
        09:00 trio ahead of 14:30, ties by id."""
        sample = self._children(self._sample())
        rows = build_rows(sample, expanded={1})
        assert [(r.kind, r.event_id, r.depth, r.parent_id) for r in rows] == [
            (ROW_EVENT, 1, 0, None),
            (ROW_EVENT, 2, 1, 1),  # без времени — раньше всех
            (ROW_EVENT, 4, 1, 1),  # 09:00, id 4
            (ROW_EVENT, 5, 1, 1),  # 09:00, id 5
            (ROW_EVENT, 6, 1, 1),  # 09:00, id 6
            (ROW_EVENT, 3, 1, 1),  # 14:30 — последней
        ]

    # ── the group-closing scalar (NRI-0023 task 11.1, design Д11) ────────────

    def test_only_the_last_emitted_child_of_a_group_closes_the_branch(self):
        """Task 11.1: ``is_last_sibling`` is true on the LAST child of the
        group (and on the only child), false on every middle child and on the
        parent — the delegate paints the «└» angle exactly where the trunk
        must stop."""
        rows = build_rows(self._children(self._sample()), expanded={1})
        assert [(r.event_id, r.is_last_sibling) for r in rows] == [
            (1, False),  # the parent is never its children's last sibling
            (2, False),
            (4, False),
            (5, False),
            (6, False),
            (3, True),  # the 14:30 row is the group's last — the «└»
        ]

    def test_a_single_child_is_its_own_last_sibling(self):
        parent = _event(1, date(1200, 1, 5), None, "Родитель")
        child = _event(2, date(1200, 1, 6), None, "Единственный", parent_id=1)
        rows = build_rows([parent, child], expanded={1})
        assert [(r.event_id, r.is_last_sibling) for r in rows] == [
            (1, False), (2, True)
        ]

    def test_the_windowed_group_closes_on_its_last_visible_child(self):
        """The flag answers the EMITTED group: a third child the window cuts
        away must not keep the group's last row promising a continuation."""
        parent = _event(1, date(1200, 1, 5), None, "Поход")
        first = _event(2, date(1200, 1, 6), None, "в окне", parent_id=1)
        second = _event(3, date(1200, 1, 7), None, "тоже в окне", parent_id=1)
        outside = _event(4, date(1200, 3, 1), None, "за окном", parent_id=1)
        window = (date(1200, 1, 6), date(1200, 1, 7))
        rows = build_rows([parent, first, second, outside], window, expanded={1})
        assert [(r.event_id, r.is_last_sibling) for r in rows] == [
            (1, False), (2, False), (3, True)
        ]

    def test_top_level_and_stub_rows_never_carry_the_group_flag(self):
        """Task 11.1's negative half: a stub is top-level decoration and a
        top-level event has no sibling group — both stay False however many
        rows follow them."""
        parent = _event(1, date(1200, 1, 1), date(1200, 1, 2), "Поход")
        first = _event(2, date(1200, 8, 14), None, "в окне", parent_id=1)
        second = _event(3, date(1200, 8, 14), None, "тоже в окне", parent_id=1)
        neighbour = _event(4, date(1200, 8, 14), None, "сосед сверху")
        rows = build_rows([parent, first, second, neighbour], self._FAR_WINDOW)
        assert [(r.kind, r.event_id, r.is_last_sibling) for r in rows] == [
            (ROW_STUB, 1, False),  # the stub itself never closes a branch
            (ROW_EVENT, 2, False),
            (ROW_EVENT, 3, True),  # the last orphan does
            (ROW_EVENT, 4, False),  # a top-level row has no group
        ]
        # …and collapsed/flat samples carry the flag nowhere.
        assert not any(r.is_last_sibling for r in build_rows([parent, first]))

    def test_the_same_time_tie_runs_in_id_order_stably(self):
        """Spec «Несколько подсобытий в одно время уживаются»: identical date
        and time is not merged and not disputed — the trio runs подряд by id,
        and the order repeats identically on every re-build (input shuffled
        both times)."""
        sample = self._children(self._sample())
        first = [r.event_id for r in build_rows(sample, expanded={1})]
        second = [r.event_id for r in build_rows(list(reversed(sample)), expanded={1})]
        assert first == second == [1, 2, 4, 5, 6, 3]

    def test_children_order_prefers_the_day_over_the_time(self):
        """Spec «Порядок разных дней не трогает»: a later-in-the-day child of
        the previous day still precedes the next day's untimed child."""
        sample = [
            _event(1, date(1200, 1, 1), None, "Родитель"),
            _event(2, date(1200, 1, 4), None, "вчера вечером",
                   start_time_raw=23 * 60, parent_id=1),
            _event(3, date(1200, 1, 5), None, "сегодня без времени", parent_id=1),
        ]
        rows = build_rows(sample, expanded={1})
        assert [r.event_id for r in rows] == [1, 2, 3]

    def test_main_events_also_order_by_time_inside_one_day(self):
        """Spec «Порядок строк»: top level obeys the same tuple — untimed,
        then время, ties by id (the repository's order, mirrored here)."""
        sample = [
            _event(9, date(1200, 3, 5), None, "в 14:30", start_time_raw=14 * 60 + 30),
            _event(4, date(1200, 3, 5), None, "без времени"),
            _event(7, date(1200, 3, 5), None, "в 9:00", start_time_raw=9 * 60),
        ]
        rows = build_rows(sample)
        assert [r.event_id for r in rows] == [4, 7, 9]

    # ── the parent stub (spec «Окно фильтрации и пустое состояние») ──────────

    _FAR_WINDOW = (date(1200, 8, 14), date(1200, 8, 14))

    def _orphan_sample(self):
        return [
            _event(1, date(1200, 1, 1), date(1200, 1, 2), "Поход"),  # вне окна
            _event(2, *self._FAR_WINDOW, "Дефиле в таверне", parent_id=1),
        ]

    def test_window_excluded_parent_becomes_a_stub_over_its_child(self):
        """Spec «Осиротевший ребёнок получает заглушку»: the stub is the bare
        parent NAME — no dates, no token, no detail — with the orphan child
        at depth 1 right under it."""
        rows = build_rows(self._orphan_sample(), self._FAR_WINDOW)
        assert [(r.kind, r.event_id) for r in rows] == [
            (ROW_STUB, 1), (ROW_EVENT, 2)
        ]
        stub, child = rows
        assert stub.caption == "Поход"
        assert stub.detail == ""
        assert stub.token_key is None
        assert (stub.depth, stub.parent_id) == (0, None)
        assert stub.has_children is True
        assert (child.depth, child.parent_id) == (1, 1)
        assert child.has_children is False

    def test_a_collapsed_window_crossing_parent_needs_no_stub(self):
        """The stub answers «where is the parent» only when its row cannot
        be shown — a parent inside the window rides its own row, collapsed
        children hidden, and no stub is fabricated."""
        parent = _event(1, date(1200, 8, 13), date(1200, 8, 15), "Поход")
        child = _event(2, *self._FAR_WINDOW, "Дефиле", parent_id=1)
        rows = build_rows([parent, child], self._FAR_WINDOW)
        assert [(r.kind, r.event_id) for r in rows] == [(ROW_EVENT, 1)]
        assert build_rows([], []) == []  # the empty sample guard stays

    def test_stub_group_rides_where_the_parent_would_have_stood(self):
        """The stub+orphans group is keyed by the parent's own order tuple,
        so the ladder keeps its chronological face: the February orphan group
        slots between the January neighbour (whose span reaches into the
        window) and a later February event, exactly where the parent itself
        would have stood."""
        january = _event(7, date(1200, 1, 10), date(1200, 2, 4), "Январь")
        parent = _event(1, date(1200, 2, 1), date(1200, 2, 2), "Февраль")
        orphan = _event(2, date(1200, 2, 5), None, "Осиротел", parent_id=1)
        later = _event(8, date(1200, 2, 4), date(1200, 2, 5), "Позже родителя")
        window = (date(1200, 2, 3), date(1200, 2, 5))  # parent's Feb 1–2 misses
        rows = build_rows([january, parent, orphan, later], window)
        assert [(r.kind, r.event_id) for r in rows] == [
            (ROW_EVENT, 7), (ROW_STUB, 1), (ROW_EVENT, 2), (ROW_EVENT, 8),
        ]

    def test_stub_never_takes_the_today_outline(self):
        """The outline needs a DATE; the stub shows none — even a parent
        starting exactly «today» leaves its stub unmarked and the outline
        simply absent."""
        parent = _event(1, _TODAY, _TODAY, "Сегодняшний")
        child = _event(2, date(1300, 1, 1), None, "В окне", parent_id=1)
        rows = build_rows([parent, child], (date(1300, 1, 1), date(1300, 1, 2)),
                          now=_TODAY)
        assert [(r.kind, r.is_now) for r in rows] == [
            (ROW_STUB, False), (ROW_EVENT, False),
        ]

    # ── degenerate and foreign shapes ─────────────────────────────────────────

    def test_dangling_and_self_parents_ride_the_top_level(self):
        """A parent id the sample never held (dangling FK) or naming the
        event itself is nobody's parent — the row stays a plain top-level
        event, no stub and no recursion."""
        dangling = _event(2, date(1200, 1, 6), None, "сирота", parent_id=999)
        self_parent = _event(3, date(1200, 1, 7), None, "сам себе", parent_id=3)
        rows = build_rows([dangling, self_parent])
        assert [(r.kind, r.event_id, r.depth) for r in rows] == [
            (ROW_EVENT, 2, 0), (ROW_EVENT, 3, 0),
        ]

    def test_foreign_parent_and_time_values_read_as_absent(self):
        """The duck-typed readers accept ints only: bools, strings and floats
        (auto-Mock noise from test doubles) read «без родителя» / «без
        времени», like the NULLable columns in storage."""
        parent = _event(1, date(1200, 1, 1), None, "main")
        weird = SimpleNamespace(
            id=2, start_date=date(1200, 1, 2), end_date=None, name="шум",
            parent_id=True, start_time_raw="14:30",
        )
        assert event_parent_id(weird) is None
        assert event_time_minutes(weird) is None
        assert event_parent_id(parent) is None  # attribute-less legacy shape
        assert event_time_minutes(parent) is None
        rows = build_rows([parent, weird], expanded={1})
        assert [(r.event_id, r.depth) for r in rows] == [(1, 0), (2, 0)]

    def test_expanded_parent_shows_only_window_crossing_children(self):
        parent = _event(1, date(1200, 1, 5), date(1200, 1, 9), "Поход")
        inside = _event(2, date(1200, 1, 6), None, "в окне", parent_id=1)
        outside = _event(3, date(1200, 1, 20), None, "за окном", parent_id=1)
        window = (date(1200, 1, 6), date(1200, 1, 6))
        rows = build_rows([parent, inside, outside], window, expanded={1})
        assert [(r.event_id, r.depth) for r in rows] == [(1, 0), (2, 1)]

    def test_the_today_outline_lands_on_the_first_emitted_event_row(self):
        """With the tree the outline follows emission order: the parent (not
        yet today) rides first, so its child starting «today» carries it."""
        parent = _event(1, date(1200, 8, 13), None, "Накануне")
        child = _event(2, _TODAY, None, "Сегодня", parent_id=1)
        rows = build_rows([parent, child], now=_TODAY, expanded={1})
        assert [(r.event_id, r.is_now) for r in rows] == [(1, False), (2, True)]


class TestTreelessSampleIsWordForWordTheOldFlatList:
    """Task 5.1's pin: with nothing expanded the tree core reproduces the
    pre-NRI-0023 flat list EXACTLY — same rows, same order, same texts. The
    comparison is with the outputs of the old core as they were last pinned
    in this file (full Row equality, default tree fields included)."""

    def test_flat_sample_output_is_frozen(self):
        events = [
            _event(20, date(2026, 1, 1), None, "наши дни", color_index=1),
            _event(1, date(1, 1, 1), None, "1 год до н.э.", start_bc=True,
                   description=_description(characteristics="сага")),
            _event(2, date(500, 6, 1), None, "500 лет до н.э.", start_bc=True),
            _event(3, date(1, 1, 1), None, "наша эра"),
            _event(9, date(1200, 3, 5), None, "второе-в-дне"),
            _event(4, date(1200, 3, 5), None, "первое-в-дне", color_index=2),
        ]
        assert build_rows(events) == [
            Row(event_id=2, start=date(500, 6, 1), end=None,
                name="500 лет до н.э.", token_key=None,
                caption="01 Июнь 500 г. до н.э. — ∞ · 500 лет до н.э.",
                start_bc=True),
            Row(event_id=1, start=date(1, 1, 1), end=None,
                name="1 год до н.э.", token_key=None,
                caption="01 Январь 1 г. до н.э. — ∞ · 1 год до н.э.",
                detail="сага", start_bc=True),
            Row(event_id=3, start=date(1, 1, 1), end=None, name="наша эра",
                token_key=None, caption="01 Январь 1 — ∞ · наша эра"),
            Row(event_id=4, start=date(1200, 3, 5), end=None,
                name="первое-в-дне", token_key="color.chart.2",
                caption="05 Март 1200 — ∞ · первое-в-дне"),
            Row(event_id=9, start=date(1200, 3, 5), end=None,
                name="второе-в-дне", token_key=None,
                caption="05 Март 1200 — ∞ · второе-в-дне"),
            Row(event_id=20, start=date(2026, 1, 1), end=None, name="наши дни",
                token_key="color.chart.1",
                caption="01 Январь 2026 — ∞ · наши дни"),
        ]

    def test_expanding_ids_that_bear_no_children_changes_nothing(self):
        """The expansion set is inert against a nesting-free sample: rows
        with unknown ids inside it must not move, mark or reformat a row."""
        events = [
            _event(4, date(1200, 3, 5), None, "первое"),
            _event(9, date(1200, 3, 5), None, "второе"),
        ]
        assert build_rows(events, expanded={404, 9}) == build_rows(events)
