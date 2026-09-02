"""Timeline widget — vertical day-scaled event list (W3b) with the panel header.

The panel keeps its name, header («+» menu, chip date-range filter + jump row)
and the W3 id-contract signals. The ``TimelineCanvas`` horizontal Gantt is gone (W3b D2):
the body is a ``QListWidget`` whose rows come from the Qt-free
:mod:`timeline_rows` core — one block per calendar day of the visible range
(event lines sorted ``(start, id)``, or a single empty-day placeholder of the
same fixed height :data:`ROW_HEIGHT`). A ``QStyledItemDelegate`` paints the row
text (``start — end · name`` via ``format_game_date``, open end ``— ``) and the
date rail (day tick, rotated month label once per month at its
first day, event brackets over the spanned days). The rail is the interactive
scale zone (W3c D1): a left press inside it arms the rail gesture on the day
under the cursor — releasing below the drag threshold jumps that day to the
top (D4), a vertical move past it enters the range-drag mode (the covered days
wear an accent wash band; on release the (min, max) day range applies exactly
once through the panel's chip-filter channel, D6/D7, and a range that stayed
within a single day degrades to the click-jump), and a double-click in the
rail stays mute (D8); none of it ever selects or emits an id. A sticky
``QLabel`` overlay pinned over the viewport
top shows the full game date of the row under the top edge, or — while the
cursor hovers the rail, and throughout an active range drag — the day under
the cursor (D5 follow), hidden while
the model is empty — the empty-state hint label stays. The header's date
fields with apply/clear are
gone (W3b D9): the range filter is one chip («Все даты» / game-formatted
borders) opening a top-level two-calendar popover with live-apply, and the
second header row carries the jump buttons (⤒/⤓, also ``Alt+Up``/``Alt+Down``
while the panel has focus) that hop over empty days to the nearest event row
(D8).

W4 grew this single widget into the whole scale ladder (design D1/D2): the row
model asks the Qt-free core for ``DAY``/``MONTH``/``YEAR`` rungs, the delegate
paints UNIT positions («Март 1245 · 4 события» / muted «нет событий»), SECTION
headers (title weight) and the event type dot (``color.chart.*`` token, muted
for untyped events — «Оформление шкалы из токенов»). Ctrl/Cmd + wheel steps the
ladder with an anchor (zoom-in: unit under the sticky, zoom-out: first visible
date), a click on a month/year position zooms in one step anchored there, and
the rail drag on large rungs maps unit pairs to full-date filters (1-е число /
last-day, 1 янв / 31 дек) through the unchanged chip channel. The panel header
carries the «сутки · месяц · год» and grouping switchers; both write through
the ViewModel's ``unit``/``group_by`` setters (the single mutation point) and
never drop the selection, the filter or the reading anchor.

Colors are token derivatives only (W3b D10): every paint color is a
``token_rgb`` derivation with alphas spelled the way ``accent_rgba`` spells
them for sheets, the off-skin fallback uses named Qt globals, and nothing here
contains a literal hex or reads the OS palette (invariant of
``tests/presentation/test_no_chrome_hex.py``, which scans this file).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Sequence

from PySide6.QtCore import (
    QDate, QModelIndex, QItemSelection, QItemSelectionModel, QPoint,
    QPointF, QRect, QSize, QSignalBlocker, Qt, Signal,
)
from PySide6.QtGui import (
    QAction, QColor, QFont, QFontMetrics, QKeySequence, QPainter, QPen, QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMenu, QPushButton, QStyledItemDelegate,
    QStyle, QToolButton, QVBoxLayout, QWidget,
)

from app.presentation.theme.catalog import attach_theme, hint, set_role, title
from app.presentation.theme.compiler import CHART_TOKEN_KEYS, token_rgb
from app.presentation.utils.date_utils import format_game_date, month_name
from app.presentation.viewmodels.timeline_viewmodel import EntityKind
from app.presentation.views.custom_date_edit import _CustomCalendar
from app.presentation.views.timeline_rows import (
    BRACKET_LANE_STEP, BRACKET_X0, Row, RowKind, ScaleUnit, SerifTarget,
    bracket_lanes, build_rows, clamp_calendar, index_at_y, next_event_index,
    normalize_range, prev_event_index, serif_hit, serif_targets, target_day,
    translate_span,
)

#: Empty-selection hint shown while the list model is empty (spec: пустое
#: состояние — текстовая подсказка вместо пустого пространства).
EMPTY_HINT_TEXT = "Нет событий в диапазоне"

# ── module geometry constants (W3b D4/D6/D7) ───────────────────────────────
ROW_HEIGHT = 24            # equal-height rows; the one knob for row density (D4)
STICKY_HEIGHT = 26         # sticky-date overlay band == top viewport margin (D7)
RAIL_MIN_WIDTH = 60        # rail width minimum (D6); labels widen it beyond this
RAIL_FIXED_ZONE = 40       # bracket lanes + tick zone the rotated label needs on
                           # top of its own width (== font height when rotated)
RAIL_TICK_LEN = 10         # day tick length, measured from the rail's right edge
RAIL_TICK_RIGHT_INSET = 3
RAIL_LABEL_INSET = 24      # x of the rotated month label's baseline (rail-right)
# BRACKET_X0 / BRACKET_LANE_STEP live in timeline_rows since W5 1.4 — the
# Qt-free serif hit-test (D8) computes the very lane centers the delegate
# paints; they are imported above and re-exported for painting and tests.
BRACKET_SERIF_W = 6        # horizontal serif at the span's start/end day
MONTH_SHORT_FORM = 3       # first letters of a month name in the short form
TEXT_LEFT_PAD = 8
PEN_WIDTH = 1

#: W4 D7: square event type-dot side, painted left of the line text (over a
#: selection it keeps its token color and gets no outline).
DOT_SIZE = 8
DOT_TEXT_GAP = 4           # gap between the type dot and the line text
#: All text rungs (event lines, unit positions, sections) share one indent so
#: the ladder reads as one column regardless of the row kind.
TEXT_INDENT = TEXT_LEFT_PAD + DOT_SIZE + DOT_TEXT_GAP

#: Ladder order of the W4 scale (index grows towards coarser rungs).
LADDER: tuple[ScaleUnit, ...] = (ScaleUnit.DAY, ScaleUnit.MONTH, ScaleUnit.YEAR)

#: Fill alpha of the hovered row — an accent-token derivative spelled the way
#: ``accent_rgba`` derives the washes for stylesheets (W3b D10).
ROW_HOVER_ALPHA = 0.25

#: Vertical move (px, viewport coords) a rail press may drift by and still be
#: the click-jump (W3c D2); past this threshold the press has become the
#: range-drag gesture whose wash/apply state machine lives below.
DRAG_START_THRESHOLD_PX = 4

#: Fill alpha of the range-drag wash band (W3c D6). Spelled the way
#: ``accent_rgba`` derives sheet washes, a touch darker than
#: :data:`ROW_HOVER_ALPHA` so the band stays visible under the hovered row's
#: wash — the design open question, one knob, no contract.
DRAG_WASH_ALPHA = 0.35

# ── header filter chip / popover (W3b D9, tasks 3.1–3.2) ───────────────────
#: Chip caption while no filter is applied; the caret marks it as a dropdown.
FILTER_CHIP_ALL = "Все даты ▾"
#: Popover hint line guiding the two taps that pick the range (D9).
FILTER_PICK_START = "Кликните дату начала"
FILTER_PICK_END = "Кликните дату окончания"
FILTER_RESET_TEXT = "Сбросить"
#: The popover stacks its two calendars in one column, so both fit only when
#: the room under the chip covers ``2×`` a calendar's height — below that the
#: low-screen fallback keeps a single calendar and the taps assign the dates.
FILTER_DOUBLE_HEIGHT_FACTOR = 2

#: itemData roles of the row model built from ``timeline_rows.Row``.
ROLE_ROW = Qt.ItemDataRole.UserRole + 1        # timeline_rows.Row
ROLE_BRACKETS = Qt.ItemDataRole.UserRole + 2   # tuple[_BracketSeg, ...]
ROLE_SHOW_TICK = Qt.ItemDataRole.UserRole + 3  # first row of its day
ROLE_SHOW_MONTH = Qt.ItemDataRole.UserRole + 4  # first row of a month
ROLE_SHOW_YEAR = Qt.ItemDataRole.UserRole + 5  # W4: year label rung (Jan on
                                               # MONTH, every row on YEAR)

#: ``set_view`` sentinel discriminating "keep the knob" from an explicit
#: ``None`` (grouping off) — a plain ``None`` default could not clear grouping.
_KEEP = object()

#: Header ladder switcher captions, ladder order (spec «Переключатели ступени
#: и группировки в шапке»).
LADDER_CAPTIONS: tuple[tuple[ScaleUnit, str], ...] = (
    (ScaleUnit.DAY, "сутки"),
    (ScaleUnit.MONTH, "месяц"),
    (ScaleUnit.YEAR, "год"),
)
#: Header grouping switcher options: ``None`` is grouping off.
GROUPING_CAPTIONS: dict = {
    None: "выкл",
    EntityKind.CHARACTER: "персонажи",
    EntityKind.LOCATION: "локации",
    EntityKind.ORGANIZATION: "организации",
    EntityKind.ITEM: "предметы",
}
#: Menu order of the grouping options (task 5.7 enumerates them this way).
GROUPING_ORDER: tuple = (
    None, EntityKind.CHARACTER, EntityKind.LOCATION,
    EntityKind.ORGANIZATION, EntityKind.ITEM,
)


@dataclass(frozen=True)
class _BracketSeg:
    """Rail bracket piece for one row: which lane and where the serifs go."""

    lane: int
    serif_top: bool
    serif_bottom: bool


@dataclass(frozen=True)
class _RailPress:
    """An armed left-button rail gesture (W3c D2).

    ``anchor_index`` is the pressed day's first block row (normalized by the
    ``index_at_y`` hit-test), ``press_y`` the viewport y the drag threshold
    measures vertical moves from. A release below :data:`DRAG_START_THRESHOLD_PX`
    resolves the arm as the click-jump; past it the range-drag state machine
    (D2/D6) takes the same arm into its wash/apply phases.
    """

    anchor_index: int
    press_y: int


#: W5 D1: text-zone arms — full-span MOVE of a closed event, or START of an
#: open event (grab the start row only). Stretch lives on :class:`_SerifPress`.
_EDIT_MOVE = "move"
_EDIT_START = "start"


@dataclass(frozen=True)
class _EventPress:
    """An armed left-button press on an event's text line (W5 D1/D2).

    Armed on the DAY rung only: ``anchor_index`` is the pressed row,
    ``grab_day`` that row's ``Row.date`` (grab-offset base — never the event
    start unless the press landed on the start row), ``press_y`` the viewport
    y the drag threshold measures vertical moves from, and ``start``/``end``
    the press-time span. ``mode`` is :data:`_EDIT_MOVE` (closed span, shift
    through ``translate_span``) or :data:`_EDIT_START` (open event, new start
    = the day under the cursor, ``end`` stays ``None``).
    """

    event_id: int
    press_y: int
    anchor_index: int
    start: date
    end: date | None
    grab_day: date
    mode: str = _EDIT_MOVE


@dataclass(frozen=True)
class _SerifPress:
    """An armed left-button press on a closed multi-day bracket's bottom serif
    (W5 3.1/3.2, D1/D8).

    Armed on the DAY rung inside the serif's hit zone (``serif_hit`` over that
    row's core :class:`SerifTarget` list) *instead of* the rail arm — a press
    there never jumps nor range-drags, however small the release is. The other
    fields mirror :class:`_EventPress`: ``press_y`` is the drag-threshold base
    y, ``start``/``end`` the press-time closed span whose ``end`` the pull
    retargets. A past-threshold move latches into the stretch mode sharing
    ``TimelineListView._edit_preview`` with the move gesture — target end =
    ``target_day`` clamped to ``end ≥ start`` — and the release commits exactly
    one ``event_dates_moved`` carrying the OLD start.
    """

    event_id: int
    press_y: int
    start: date
    end: date


@dataclass(frozen=True)
class _Palette:
    """QColors for one paint pass, all derived from tokens of the live theme."""

    background: QColor     # sticky band surface
    rail: QColor           # day ticks (color.border)
    bracket: QColor        # span brackets (color.border)
    row_text: QColor       # event line text (color.fg.primary)
    selected_fill: QColor  # selected row fill (color.accent)
    selected_text: QColor  # text over the accent fill (color.accent.fg)
    hover_fill: QColor     # accent derivative wash under the hovered row
    drag_fill: QColor      # range-drag wash band over the covered days (D6)
    month_text: QColor     # month labels (color.fg.muted)
    hairline: QColor       # sticky band underline (color.accent)
    # ── W4 D5/D7: type dots and the large-rung positions ───────────────────
    unit_muted: QColor             # empty unit stub caption (color.fg.muted)
    type_dot_muted: QColor         # type dot of an untyped event (color.fg.muted)
    type_dots: dict                # ``color.chart.k`` token key → QColor (8)


def _from_rgb(rgb, alpha: float = 1.0) -> QColor:
    """Token RGB → QColor with an explicit alpha (None → neutral Qt global)."""
    color = QColor(*rgb) if rgb is not None else QColor(Qt.GlobalColor.gray)
    color.setAlphaF(alpha)
    return color


def _global(name: Qt.GlobalColor, alpha: float = 1.0) -> QColor:
    """Named Qt global → QColor: the only paint source without live tokens.

    Off-skin (no runtime / unparsable token) the list still has to be legible,
    and inventing a hex for that moment would break the ui-theme invariant —
    named Qt globals are theme-neutral constants, not colors this app owns
    (spec scenario «Вне скина»).
    """
    color = QColor(name)
    color.setAlphaF(alpha)
    return color


def rows_palette(runtime) -> _Palette:
    """Derive every row/rail/sticky color from the runtime's current tokens.

    On-skin every entry is a token derivation (D10). Off-skin (no runtime /
    invalid tokens) the list falls back to named Qt globals only — neutral
    paint for a state where no token exists to derive from, never an
    app-owned hex.
    """
    off_skin = runtime is None or not getattr(runtime, "is_valid", False)
    if off_skin:
        return _Palette(
            # The sticky band sits over the rows — off-skin it is a plain
            # light surface under the black fallback text (named globals).
            background=_global(Qt.GlobalColor.white),
            rail=_global(Qt.GlobalColor.gray),
            bracket=_global(Qt.GlobalColor.gray),
            row_text=_global(Qt.GlobalColor.black),
            selected_fill=_global(Qt.GlobalColor.gray),
            selected_text=_global(Qt.GlobalColor.white),
            hover_fill=_global(Qt.GlobalColor.gray, ROW_HOVER_ALPHA),
            drag_fill=_global(Qt.GlobalColor.gray, DRAG_WASH_ALPHA),
            month_text=_global(Qt.GlobalColor.gray),
            hairline=_global(Qt.GlobalColor.gray),
            # No tokens to derive chart colors from — every dot falls back to
            # the same named Qt global as the muted text (spec «Вне скина»).
            unit_muted=_global(Qt.GlobalColor.gray),
            type_dot_muted=_global(Qt.GlobalColor.gray),
            type_dots={key: _global(Qt.GlobalColor.gray) for key in CHART_TOKEN_KEYS},
        )
    tokens, theme = runtime.tokens, runtime.theme
    accent = token_rgb(tokens, theme, "color.accent")
    muted = token_rgb(tokens, theme, "color.fg.muted")
    return _Palette(
        background=_from_rgb(token_rgb(tokens, theme, "color.bg.surface")),
        rail=_from_rgb(token_rgb(tokens, theme, "color.border")),
        bracket=_from_rgb(token_rgb(tokens, theme, "color.border")),
        row_text=_from_rgb(token_rgb(tokens, theme, "color.fg.primary")),
        selected_fill=_from_rgb(accent),
        selected_text=_from_rgb(token_rgb(tokens, theme, "color.accent.fg")),
        hover_fill=_from_rgb(accent, ROW_HOVER_ALPHA),
        drag_fill=_from_rgb(accent, DRAG_WASH_ALPHA),
        month_text=_from_rgb(muted),
        hairline=_from_rgb(accent),
        unit_muted=_from_rgb(muted),
        type_dot_muted=_from_rgb(muted),
        # The mandatory W4 chart palette: dot k of a typed row is exactly
        # ``color.chart.k`` of the live theme (spec «Цвет типа равен токену»).
        type_dots={
            key: _from_rgb(token_rgb(tokens, theme, key))
            for key in CHART_TOKEN_KEYS
        },
    )


def _range_text(row: Row) -> str:
    """``start — end`` in the game format; an open end stays an explicit ``—``."""
    start = format_game_date(row.start)
    if row.end is None:
        return f"{start} —"
    return f"{start} — {format_game_date(row.end)}"


def _row_line(row: Row) -> str:
    """Row label: ``start — end · name`` with the game format (open end ``—``)."""
    return f"{_range_text(row)} · {row.name}"


def _preview_line(name: str, start: date, end: date | None) -> str:
    """Ghost caption for the live edit preview (same format as :func:`_row_line`)."""
    start_s = format_game_date(start)
    span = f"{start_s} —" if end is None else f"{start_s} — {format_game_date(end)}"
    return f"{span} · {name}"


def _row_tooltip(row: Row) -> str:
    """Tooltip body: full name plus the game-formatted date range (spec)."""
    return f"{row.name}\n{_range_text(row)}"


def _month_labels(day: date) -> tuple[str, str]:
    """(full, short) rail label of the month ``day`` belongs to (game names)."""
    full = format_game_date(day)
    short = f"{month_name(day.month)[:MONTH_SHORT_FORM]} {day.year}"
    return full, short


def unit_caption(day: date, unit: ScaleUnit) -> str:
    """Game caption of a ladder position: day date / «Март 1245» / «1245».

    The month name comes from the live game map (``month_name``), so custom
    months ride the ladder exactly like the W3b rail did (spec «Игровые
    месяцы»); re-read per call, a rename repaints without a rebuild.
    """
    if unit is ScaleUnit.MONTH:
        return f"{month_name(day.month)} {day.year}"
    if unit is ScaleUnit.YEAR:
        return str(day.year)
    return format_game_date(day)


def _events_phrase(count: int) -> str:
    """RU count phrase for the unit stub counter («4 события», «1 событие»)."""
    if count % 100 in range(11, 15):
        return "событий"
    last = count % 10
    if last == 1:
        return "событие"
    if 2 <= last <= 4:
        return "события"
    return "событий"


def _unit_line(row: Row) -> str:
    """UNIT position text: «Март 1245 · 4 события» / «… · нет событий»."""
    count = row.unit_count or 0
    tail = f"{count} {_events_phrase(count)}" if count else "нет событий"
    return f"{unit_caption(row.date, row.unit)} · {tail}"


def _unit_first(day: date, unit: ScaleUnit) -> date:
    """First day of the ladder unit ``unit`` containing ``day``."""
    if unit is ScaleUnit.MONTH:
        return date(day.year, day.month, 1)
    if unit is ScaleUnit.YEAR:
        return date(day.year, 1, 1)
    return day


def _unit_last(day: date, unit: ScaleUnit) -> date:
    """Last day of the ladder unit ``unit`` containing ``day`` — the drag's
    emit-time normalization target (1-е число … last-day, 1 янв … 31 дек)."""
    if unit is ScaleUnit.MONTH:
        following = date(day.year + (day.month == 12), day.month % 12 + 1, 1)
        return following - timedelta(days=1)
    if unit is ScaleUnit.YEAR:
        return date(day.year, 12, 31)
    return day


def build_event_groups(
    events: Sequence[Any], group_by: EntityKind | None
) -> dict[int, tuple[str, ...]] | None:
    """Materialize the «event id → entity names» map ``build_rows`` consumes.

    Duck-typed off the domain relations (W4 D8) exactly like the ViewModel's
    own map, so list-only samples without links simply land in «Без привязки».
    """
    if group_by is None:
        return None
    attr = group_by.event_attr
    return {
        e.id: tuple(
            name for link in (getattr(e, attr, None) or ())
            if (name := getattr(link, "name", ""))
        )
        for e in events
    }


class _RowDelegate(QStyledItemDelegate):
    """Paints one list position: selection/hover wash, rail (tick/label/bracket)
    and the ``start — end · name`` line. Everything else (selection model,
    scrolling, focus) is the plain ``QListWidget`` machinery (D2).
    """

    def __init__(self, view: "TimelineListView") -> None:
        super().__init__(view)
        self._view = view

    def sizeHint(self, option, index) -> QSize:  # Qt API name
        return QSize(0, ROW_HEIGHT)

    def paint(self, painter: QPainter, option, index) -> None:  # Qt API name
        row = index.data(ROLE_ROW)
        if not isinstance(row, Row):
            return
        view = self._view
        palette = view.paint_palette()
        preview = view.edit_preview()
        origin = preview is not None and row.event_id == preview[0]
        ghost = preview is not None and index.row() == view.edit_ghost_index()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = (
            not selected and not origin and not ghost
            and index.row() == view.hover_index()
        )
        painter.save()
        if selected and not origin:
            painter.fillRect(option.rect, palette.selected_fill)
        elif hovered:
            painter.fillRect(option.rect, palette.hover_fill)
        drag = view.drag_range()
        if drag is not None and drag[0] <= row.date <= drag[1]:
            # D6: the live range-drag band over every day it covers — the same
            # view state the hover wash reads; each covered row fills its own
            # slice, so partially visible rows clip the band automatically.
            # On the large rungs the pair holds unit anchors, so the band
            # washes exactly the covered unit positions (W4 5.6).
            painter.fillRect(option.rect, palette.drag_fill)
        if ghost:
            painter.fillRect(option.rect, palette.drag_fill)
        self._paint_rail(painter, option, index, row, palette, preview)
        if row.kind is RowKind.EVENT:
            self._paint_line(
                painter, option, row, palette, selected,
                origin=origin, ghost=ghost, preview=preview,
            )
        elif ghost:
            self._paint_ghost_line(painter, option, palette, preview)
        elif row.kind is RowKind.UNIT:
            self._paint_unit(painter, option, row, palette)
        elif row.kind is RowKind.SECTION:
            self._paint_section(painter, option, row, palette)
        painter.restore()

    def _paint_rail(
        self, painter, option, index, row: Row, palette: _Palette, preview,
    ) -> None:
        """Day tick, once-per-month rotated label, span brackets (all decorative)."""
        rail_w = self._view.rail_width()
        rect = option.rect
        painter.setPen(QPen(palette.rail, PEN_WIDTH))
        if index.data(ROLE_SHOW_TICK):
            # One tick per calendar day, at the top border of the day's first row.
            y = rect.top() + 0.5
            painter.drawLine(
                QPointF(rail_w - RAIL_TICK_LEN + 0.5, y),
                QPointF(rail_w - RAIL_TICK_RIGHT_INSET + 0.5, y),
            )
        stretch_lane = None
        stretch_span = None
        if (
            preview is not None
            and preview[2] is not None
            and self._view.stretch_preview_lane() is not None
        ):
            stretch_lane = self._view.stretch_preview_lane()
            stretch_span = (preview[1], preview[2])
        for seg in index.data(ROLE_BRACKETS) or ():
            if stretch_lane is not None and seg.lane == stretch_lane:
                continue  # replaced by the live stretch bracket below
            x = BRACKET_X0 + seg.lane * BRACKET_LANE_STEP + 0.5
            painter.setPen(QPen(palette.bracket, PEN_WIDTH))
            painter.drawLine(QPointF(x, rect.top() + 0.5), QPointF(x, rect.bottom() - 0.5))
            if seg.serif_top or seg.serif_bottom:
                for yy in (
                    (rect.top() + ROW_HEIGHT / 2,) if seg.serif_top else ()
                ) + ((rect.bottom() - ROW_HEIGHT / 2,) if seg.serif_bottom else ()):
                    y = int(yy) + 0.5
                    painter.drawLine(
                        QPointF(x, y), QPointF(x + BRACKET_SERIF_W, y),
                    )
        if stretch_lane is not None and stretch_span is not None:
            start, end = stretch_span
            if start <= row.date <= end:
                x = BRACKET_X0 + stretch_lane * BRACKET_LANE_STEP + 0.5
                painter.setPen(QPen(palette.bracket, PEN_WIDTH))
                painter.drawLine(
                    QPointF(x, rect.top() + 0.5), QPointF(x, rect.bottom() - 0.5),
                )
                serif_top = row.date == start
                serif_bottom = row.date == end
                if serif_top or serif_bottom:
                    for yy in (
                        (rect.top() + ROW_HEIGHT / 2,) if serif_top else ()
                    ) + ((rect.bottom() - ROW_HEIGHT / 2,) if serif_bottom else ()):
                        y = int(yy) + 0.5
                        painter.drawLine(
                            QPointF(x, y), QPointF(x + BRACKET_SERIF_W, y),
                        )
        if index.data(ROLE_SHOW_MONTH):
            full, short = _month_labels(row.date)
            self._paint_rotated_label(painter, option, rail_w, palette, full, short)
        if index.data(ROLE_SHOW_YEAR):
            # W4 5.2: the year rail label — January's unit position on MONTH,
            # every position on the YEAR rung — where DAY paints its month.
            self._paint_rotated_label(
                painter, option, rail_w, palette, str(row.date.year),
                str(row.date.year),
            )

    def _paint_rotated_label(
        self, painter, option, rail_w, palette, full: str, short: str
    ) -> None:
        """Rotated rail label climbing from its tick (D6).

        Drawn bottom-to-top so it bleeds into the already-painted rows above
        instead of being overpainted by the next row; when the headroom above
        is not enough for the full label, the short form is used.
        """
        fm = QFontMetrics(option.font)
        label = full if option.rect.top() >= fm.horizontalAdvance(full) else short
        painter.setPen(QPen(palette.month_text))
        painter.save()
        painter.translate(rail_w - RAIL_LABEL_INSET, option.rect.top() + 3)
        painter.rotate(-90)  # local +x runs up ⇒ text reads bottom-to-top
        painter.drawText(0, 0, label)
        painter.restore()

    def _draw_text(
        self, painter, option, text: str, color, *, bold: bool = False
    ) -> None:
        """One elided text run at the shared ladder indent (tooltip holds all)."""
        rect = option.rect.adjusted(
            self._view.rail_width() + TEXT_INDENT, 0, -TEXT_LEFT_PAD, 0
        )
        fm = QFontMetrics(option.font)
        elided = fm.elidedText(text, Qt.TextElideMode.ElideRight, max(rect.width(), 0))
        font = option.font
        if bold:
            font = QFont(option.font)
            font.setBold(True)  # SECTION = title weight (W4 D7)
        painter.setPen(QPen(color))
        painter.save()
        painter.setFont(font)
        painter.drawText(
            rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            elided,
        )
        painter.restore()

    def _paint_line(
        self, painter, option, row: Row, palette: _Palette, selected: bool,
        *, origin: bool = False, ghost: bool = False, preview=None,
    ) -> None:
        """The ``start — end · name`` line prefixed by the event type dot (W4).

        The dot square is token-derived (``color.chart.k`` via the row's
        ``token_key``, muted when the event is untyped); it is a bare fill with
        no pen, so it survives the selection wash without an outline (D7)."""
        rail_w = self._view.rail_width()
        dot_key = row.token_key
        dot = (
            palette.type_dots.get(dot_key, palette.type_dot_muted)
            if dot_key else palette.type_dot_muted
        )
        rect = option.rect
        painter.fillRect(
            QRect(
                rail_w + TEXT_LEFT_PAD,
                rect.center().y() - DOT_SIZE // 2,
                DOT_SIZE, DOT_SIZE,
            ),
            dot,
        )
        if ghost and preview is not None:
            text = _preview_line(row.name, preview[1], preview[2])
            color = palette.month_text
        elif origin:
            text = _row_line(row)
            color = palette.month_text
        else:
            text = _row_line(row)
            color = palette.selected_text if selected else palette.row_text
        self._draw_text(painter, option, text, color)

    def _paint_ghost_line(self, painter, option, palette: _Palette, preview) -> None:
        """Ghost caption on a non-EVENT target row (empty day / extrapolated)."""
        if preview is None:
            return
        name = ""
        origin_idx = self._view.index_for_event(preview[0])
        if origin_idx is not None:
            name = self._view.rows[origin_idx].name
        self._draw_text(
            painter, option, _preview_line(name, preview[1], preview[2]),
            palette.month_text,
        )

    def _paint_unit(self, painter, option, row: Row, palette: _Palette) -> None:
        """UNIT position: «Март 1245 · 4 события», an empty stub muted (D7)."""
        filled = bool(row.unit_count)
        self._draw_text(
            painter, option, _unit_line(row),
            palette.row_text if filled else palette.unit_muted,
        )

    def _paint_section(self, painter, option, row: Row, palette: _Palette) -> None:
        """SECTION header: the group name in the title weight (D7)."""
        self._draw_text(
            painter, option, row.group_key or "", palette.row_text, bold=True,
        )


class TimelineListView(QListWidget):
    """The vertical event scale: one list position per day block (W3b D2/D3).

    Signals carry **event ids** (the W3 id-contract): a click on an EVENT row
    emits ``event_selected(id)``, a double-click emits ``event_double_clicked``;
    empty-day rows are inert (disabled flags — not selectable, not clickable).
    The rail zone left of the text is the interactive scale (W3c D1): presses
    there arm the rail gesture on the day under the cursor — a release below
    the drag threshold jumps that day to the top of the view (D4) without
    touching the selection or the id-signals, a vertical move past it enters
    the range-drag mode (D2/D6) whose normalized day range is emitted *once*
    on release as ``day_range_applied(start, end)`` (D7), and a double-click
    stays mute (D8). W5 adds the move gesture (D1): a past-threshold
    press-drag on the text line of a *closed* event on the DAY rung previews
    the shifted span in ``edit_preview()`` on every move (data and the row
    model stay untouched) and commits exactly one
    ``event_dates_moved(event_id, start, end)`` on release — Esc or an
    external rebuild cancels it. The W5 stretch joins it: a past-threshold
    press-drag on the bottom serif of a *closed multi-day* bracket (the core
    serif hit-zone, checked before the rail branch) retargets the end with the
    clamp ``end ≥ start`` and commits the same signal once with the old start.
    Selection and scrolling are the view's own;
    the panel drives them through the public API below.
    """

    event_selected = Signal(int)  # event_id
    event_double_clicked = Signal(int)  # event_id
    day_range_applied = Signal(object, object)  # rail drag range (start, end)
    event_dates_moved = Signal(object, object, object)  # W5: commit of the
        # move gesture — (event_id, new_start, new_end), exactly once per
        # release; propagating it past the list is the panel's job (group 6)
    scale_changed = Signal(object)  # ScaleUnit after a gesture stepped the
                                    # ladder (Ctrl/Cmd wheel, unit click — 5.4/5.5)

    def __init__(self, theme=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._events: tuple[Any, ...] = ()
        self._rows: tuple[Row, ...] = ()
        self._version: tuple | None = None
        self._selected_id: int | None = None
        self._index_by_event: dict[int, int] = {}
        self._lanes: dict[int, int] = {}
        self._hover_row = -1
        self._palette = rows_palette(None)
        self._rail_w = RAIL_MIN_WIDTH
        self._rail_press: _RailPress | None = None  # armed rail gesture (W3c D2)
        self._drag_range: tuple[date, date] | None = None  # live range drag (D6)
        # W5 move gesture: the armed text-line press and, once latched, the
        # live preview (event_id, target_start, target_end) the delegate reads
        # (D6) — preview state only, never data or the row model.
        self._event_press: _EventPress | None = None
        self._edit_preview: tuple[int, date, date | None] | None = None
        # W5 3.1/3.2 serif stretch: the armed serif press (D1) and the D8 map
        # the press consults — row index → draggable bottom serifs, only ever
        # populated on the DAY rung (stretch is a days-only gesture).
        self._serif_press: _SerifPress | None = None
        self._serif_target_by_row: dict[int, tuple[SerifTarget, ...]] = {}
        self._follow_y: int | None = None  # rail cursor y the sticky follows (D5)
        # W4 D2 view knobs (mirror of the ViewModel's — the VM setter stays the
        # single mutation point; these drive build_rows and the gestures):
        self._unit: ScaleUnit = ScaleUnit.DAY
        self._group_by: EntityKind | None = None
        self._range: tuple[date | None, date | None] = (None, None)
        self._press_index = -1  # text-zone press the release may zoom on (5.5)

        self.setObjectName("timelineList")
        set_role(self, "list")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setUniformItemSizes(True)
        self.setWordWrap(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # One wheel notch == exactly one row (spec «Шаг прокрутки колеса»).
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerItem)
        self.setMouseTracking(True)  # hover wash under the cursor (accent derivative)
        self.setItemDelegate(_RowDelegate(self))

        # D7: the sticky overlay is a scroll-area child pinned above the
        # viewport; the viewport gets a top margin of exactly its height, so
        # nothing is ever hidden behind it.
        self.setViewportMargins(0, STICKY_HEIGHT, 0, 0)
        self._sticky = title("")
        self._sticky.setParent(self)
        self._sticky.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._hint = hint(EMPTY_HINT_TEXT)
        self._hint.setParent(self)
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self.verticalScrollBar().valueChanged.connect(lambda _v: self._sync_overlays())
        self.clicked.connect(self._on_clicked)
        self.doubleClicked.connect(self._on_double_clicked)
        self._rebuild_palette()
        self._sync_overlays()
        if theme is not None:
            # Live re-theme (D10): rebuild the paint palette and repaint the
            # rows — selection and scroll position are deliberately untouched.
            theme.add_listener(self._retheme)

    # ── public API (tasks 2.1/2.5) ──────────────────────────────────────────

    @property
    def events(self) -> tuple[Any, ...]:
        """The events currently rendered (test/E2E introspection)."""
        return self._events

    @property
    def rows(self) -> tuple[Row, ...]:
        """The current row model (pure ``timeline_rows`` data)."""
        return self._rows

    @property
    def scale_unit(self) -> ScaleUnit:
        """The ladder rung the list currently renders (W4 D2)."""
        return self._unit

    @property
    def grouping(self) -> EntityKind | None:
        """The entity kind the list is grouped by (``None`` = off)."""
        return self._group_by

    @property
    def selected_id(self) -> int | None:
        return self._selected_id

    @property
    def sticky_label(self) -> QLabel:
        """The sticky-date overlay (test/E2E introspection)."""
        return self._sticky

    @property
    def hint_label(self) -> QLabel:
        """The empty-state hint overlay (test/E2E introspection)."""
        return self._hint

    @staticmethod
    def _version_of(
        events: Sequence[Any],
        range_start: date | None,
        range_end: date | None,
        unit: ScaleUnit = ScaleUnit.DAY,
        group_by: EntityKind | None = None,
    ) -> tuple:
        """The rebuild key: the ``(id, start, end, name, color)`` set plus window.

        The visible range is part of the version (not just the events): the
        same sample under a different filter range is a different scale — the
        filter's empty days must appear whether or not the events moved. The
        W4 knobs join the key so a ladder/grouping change is never swallowed
        by the identical-sample fast path — and so does the type's palette
        index, because assigning/re-coloring a type repaints the row dots
        without any name or date moving (task 6.2/6.3 duck-typed: a test
        double without ``event_type`` carries the stable ``None`` facet).
        """
        return (
            tuple(
                (
                    e.id, e.start_date, e.end_date, e.name,
                    getattr(getattr(e, "event_type", None), "color_index", None),
                )
                for e in events
            ),
            range_start,
            range_end,
            unit,
            group_by,
        )

    def update_events(
        self,
        events: Sequence[Any],
        range_start: date | None = None,
        range_end: date | None = None,
    ) -> None:
        """Reload the row model — but only when the event set actually moved.

        ``range_start``/``range_end`` are the optional visible-range bounds
        (the live filter): enumerated exactly, empty days included (spec
        «Пустые и фильтрационные состояния»); omitted, the sample derives its
        own min–max. The "version" is the event set plus that window (
        :meth:`_version_of`): mutation reloads that change a name/date must
        redraw, repeated identical samples at the same window must not rebuild
        (and thus must not touch focus or scroll position). After a real
        rebuild the reading position is restored from the selected id when that
        event is still visible, and the list rewinds to the top otherwise (a
        new sample opens from its first day — and a selection the ViewModel
        pruned never keeps a stale offset).
        """
        events = tuple(events)
        version = self._version_of(
            events, range_start, range_end, self._unit, self._group_by
        )
        if version == self._version:
            # Same set — but game month names can move while no event does
            # (month settings reload identical events): repaint the rail
            # labels and the sticky date, rows/selection/scroll stay as they are.
            self._sync_overlays()
            self.viewport().update()
            return
        self._rebuild(events, range_start, range_end)
        # W4: an event without a *row* still has its selection pending on the
        # large rungs (UNIT positions own no event lines), so pruning follows
        # the sample membership, not the row index — only an event that left
        # the visible sample is forgotten (spec «Фильтр исключил выбранное»).
        visible_ids = {e.id for e in events}
        if self._selected_id is not None and self._selected_id not in visible_ids:
            self._selected_id = None  # excluded from the visible sample (spec)
        if self._selected_id is not None:
            self._apply_selection(scroll=True)
        else:
            with QSignalBlocker(self.verticalScrollBar()):
                self.verticalScrollBar().setValue(0)
            self._sync_overlays()

    def set_view(
        self,
        unit: ScaleUnit = _KEEP,
        group_by=_KEEP,
        anchor_date: date | None = None,
    ) -> None:
        """Switch the ladder knob (W4 D2) without touching filter or selection.

        The ViewModel owns the truth — its ``unit``/``group_by`` setters call
        this to reflect a change (and the panel drives gestures through the
        same door). The re-model keeps the reading position: the position
        containing the pre-switch top date (or an explicit ``anchor_date`` for
        a gesture's unit anchor) lands back under the sticky band, and a
        selection that still owns a row stays highlighted and visible.
        """
        unit = self._unit if unit is _KEEP else unit
        group_by = self._group_by if group_by is _KEEP else group_by
        knobs_changed = unit is not self._unit or group_by is not self._group_by
        if not knobs_changed and anchor_date is None:
            return
        anchor = anchor_date if isinstance(anchor_date, date) else self._top_date()
        if knobs_changed:
            self._unit = unit
            self._group_by = group_by
            self._rebuild(self._events, self._range[0], self._range[1])
        if anchor is not None:
            idx = self._unit_index_at(anchor)
            if idx is not None:
                self._jump_to_day_row(idx)
        if knobs_changed:
            self._reassert_selection()

    def set_selected(self, event_id: int | None) -> None:
        """Highlight ``event_id`` from the outside (search jump, prune-to-None).

        Idempotent: the same id is a complete no-op. A non-``None`` id also
        scrolls the row into view; an id outside the sample clears the
        highlight without moving anything.
        """
        if event_id == self._selected_id:
            return
        self._selected_id = event_id
        self._apply_selection(scroll=True)

    def scroll_to_event(self, event_id: int) -> None:
        """Scroll just enough to reveal the event's row (search jump)."""
        idx = self._index_by_event.get(event_id)
        if idx is None:
            return
        self.scrollToItem(self.item(idx), QAbstractItemView.ScrollHint.PositionAtCenter)

    def jump_prev_event(self) -> bool:
        """Scroll to the nearest EVENT row before the visible position (D8).

        Runs of empty days are skipped; at the head of the sample the command
        is inert (``prev_event_index`` returns ``None``). On MONTH/YEAR there
        are no EVENT rows at all, so the ``False`` return tells the panel to
        drop the ladder first (W4 D4/spec «Прыжок с месяцной ступени»).
        """
        idx = prev_event_index(self._rows, self._jump_base_index())
        if idx is not None:
            self._reveal_row(idx)
            return True
        return False

    def jump_next_event(self) -> bool:
        """Mirror of :meth:`jump_prev_event` towards the tail of the sample."""
        idx = next_event_index(self._rows, self._jump_base_index())
        if idx is not None:
            self._reveal_row(idx)
            return True
        return False

    def index_for_event(self, event_id: int) -> int | None:
        """Row index of ``event_id`` in the current model (``None`` → absent)."""
        return self._index_by_event.get(event_id)

    def bracket_lane(self, event_id: int) -> int | None:
        """Rail lane of the event's bracket (``None``: day tick owns the mark).

        Public so the E2E/pixel acceptance group can prove overlapping spans
        take neighbour lanes without reaching into the private lane map.
        """
        return self._lanes.get(event_id)

    def top_visible_index(self) -> int:
        """Index of the row under the viewport's top edge (``-1`` when empty)."""
        item = self.itemAt(self.viewport().rect().topLeft())
        return self.row(item) if item is not None else -1

    def rail_width(self) -> int:
        """Current rail width (label-derived, floored at ``RAIL_MIN_WIDTH``)."""
        return self._rail_w

    def paint_palette(self) -> _Palette:
        """The palette the delegate paints with (rebuilt on every re-theme)."""
        return self._palette

    def hover_index(self) -> int:
        return self._hover_row

    def drag_range(self) -> tuple[date, date] | None:
        """The days an active range-drag covers (D6), inclusive at both ends —
        the delegate's wash-band state (``None`` when no drag is in flight)."""
        return self._drag_range

    def edit_preview(self) -> tuple[int, date, date | None] | None:
        """The live edit preview (W5 D6): ``(event_id, target_start, target_end)``
        recomputed on every past-threshold move — ``target_end`` is ``None``
        for an open-event start drag. The events and the row model never
        carry it."""
        return self._edit_preview

    def edit_ghost_index(self) -> int | None:
        """Row the ghost wash paints on: the day under the cursor if it is in
        the model, else the last visible row (extrapolated target, D2)."""
        if self._edit_preview is None:
            return None
        target = self._follow_day
        if target is not None:
            for idx, row in enumerate(self._rows):
                if row.date == target:
                    return idx
        return self._last_visible_index()

    def stretch_preview_lane(self) -> int | None:
        """Bracket lane of an active end-stretch, else ``None`` (live bracket)."""
        if self._serif_press is None or self._edit_preview is None:
            return None
        return self._lanes.get(self._serif_press.event_id)

    def _last_visible_index(self) -> int | None:
        if not self.count():
            return None
        bottom = max(self.viewport().rect().bottom() - 1, 0)
        idx = self.indexAt(QPoint(self.rail_width() + TEXT_LEFT_PAD, bottom)).row()
        if idx < 0:
            return self.count() - 1
        return idx

    def _covering_closed_event(self, day: date):
        """First closed event whose span contains ``day`` (for mid-body grab)."""
        covering = [
            event for event in self._events
            if event.end_date is not None and event.start_date <= day <= event.end_date
        ]
        covering.sort(key=lambda event: (event.start_date, event.id))
        return covering[0] if covering else None

    def _arm_event_press(self, pressed: int, y: int) -> None:
        """Arm MOVE/START from a text-zone press on the DAY rung (W5 D1/2b/2.5)."""
        self._event_press = None
        if not (0 <= pressed < len(self._rows)):
            return
        pressed_row = self._rows[pressed]
        if pressed_row.kind is RowKind.EVENT:
            if pressed_row.start is not None and pressed_row.end is not None:
                self._event_press = _EventPress(
                    event_id=pressed_row.event_id,
                    press_y=y,
                    anchor_index=pressed,
                    start=pressed_row.start,
                    end=pressed_row.end,
                    grab_day=pressed_row.date,
                    mode=_EDIT_MOVE,
                )
                return
            if (
                pressed_row.start is not None
                and pressed_row.end is None
                and pressed_row.date == pressed_row.start
            ):
                self._event_press = _EventPress(
                    event_id=pressed_row.event_id,
                    press_y=y,
                    anchor_index=pressed,
                    start=pressed_row.start,
                    end=None,
                    grab_day=pressed_row.date,
                    mode=_EDIT_START,
                )
            return
        if pressed_row.kind is RowKind.EMPTY_DAY:
            covering = self._covering_closed_event(pressed_row.date)
            if covering is None:
                return
            self._event_press = _EventPress(
                event_id=covering.id,
                press_y=y,
                anchor_index=pressed,
                start=covering.start_date,
                end=covering.end_date,
                grab_day=pressed_row.date,
                mode=_EDIT_MOVE,
            )

    def _retarget_edit(self, y: int) -> None:
        """Recompute ``_edit_preview`` from viewport ``y`` (move / start / stretch)."""
        target = target_day(
            self._rows, ROW_HEIGHT, y, self.verticalScrollBar().value(),
        )
        if target is None:
            return
        serif_press = self._serif_press
        if serif_press is not None:
            end = target if target >= serif_press.start else serif_press.start
            preview = (serif_press.event_id, serif_press.start, end)
        else:
            event_press = self._event_press
            if event_press is None:
                return
            if event_press.mode == _EDIT_START or event_press.end is None:
                preview = (event_press.event_id, target, None)
            else:
                new_start, new_end = translate_span(
                    event_press.start, event_press.end,
                    (target - event_press.grab_day).days,
                )
                preview = (
                    event_press.event_id,
                    clamp_calendar(new_start),
                    clamp_calendar(new_end),
                )
        if preview != self._edit_preview:
            self._edit_preview = preview
            self.viewport().update()
        if self._follow_day != target:
            self._follow_day = target
            self._refresh_sticky_text()

    def _serif_target_at(self, x: int, y: int) -> SerifTarget | None:
        """The draggable serif under a rail press point, ``None`` for a miss.

        W5 3.1/D8: the vertical window of the hit zone is the serif's own row
        (the core map is keyed by row index, computed on the equal-height
        contract like :func:`index_at_y` but without the day-head walk-back —
        the serif is painted on its end day's *last* row only); the horizontal
        radius is the core's :func:`serif_hit`. A target whose owning event
        owns no EVENT row (or a non-closed span, which the core already
        excludes) is treated as a miss — defensive, the map is rebuilt with
        every model and can never legitimately desync.
        """
        if not self._serif_target_by_row:
            return None
        row = (y + ROW_HEIGHT * self.verticalScrollBar().value()) // ROW_HEIGHT
        targets = self._serif_target_by_row.get(row)
        if not targets:
            return None
        target = serif_hit(targets, x)
        if target is None:
            return None
        event_idx = self._index_by_event.get(target.event_id)
        pressed = self._rows[event_idx] if event_idx is not None else None
        if not isinstance(pressed, Row) or pressed.start is None or pressed.end is None:
            return None
        return target

    def axis_labels(self) -> list[str]:
        """Month rail labels of the current sample, game-formatted, one per month.

        Re-reads the live ``format_game_date`` month names on every call — a
        month rename is visible without rebuilding the rows (the labels are a
        pure function of the row dates).
        """
        labels: list[str] = []
        seen: set[tuple[int, int]] = set()
        for row in self._rows:
            if row.date.day == 1 and (row.date.year, row.date.month) not in seen:
                seen.add((row.date.year, row.date.month))
                labels.append(format_game_date(row.date))
        return labels

    # ── row model construction ──────────────────────────────────────────────

    def _rebuild(
        self,
        events: tuple[Any, ...],
        range_start: date | None = None,
        range_end: date | None = None,
    ) -> None:
        """Rebuild the Qt list from ``build_rows`` (O(range + events), see risks).

        Explicit bounds (a live filter) enumerate exactly the units/days of the
        window those days bound, empty ones included; omitted, the sample's own
        min–max owns the range. The current ladder rung and grouping (W4 D1)
        decide the row model; the window is remembered on ``self._range`` so
        :meth:`set_view` can re-model it under new knobs.
        """
        self._events = events
        self._version = self._version_of(
            events, range_start, range_end, self._unit, self._group_by
        )
        self._range = (range_start, range_end)
        rows = build_rows(
            events, range_start, range_end,
            unit=self._unit, groups=build_event_groups(events, self._group_by),
        )
        self._rows = tuple(rows)
        # Open-end brackets reach the last day of the visible range — the
        # filter bound when one is live, otherwise what build_rows derived
        # (max(end|start)). The last row is exactly that edge (unit rungs:
        # the first day of the last unit, which maps onto that unit).
        range_end_eff = rows[-1].date if rows else None
        self._lanes = bracket_lanes(events, range_end_eff, self._unit)
        # W5 D8: the serif hit-zone is built from the very geometry the
        # delegate paints (core ``serif_targets``) — closed multi-day brackets
        # only, DAY rung only; larger rungs own no draggable handle.
        self._serif_target_by_row = (
            serif_targets(self._rows, events, self._lanes)
            if self._unit is ScaleUnit.DAY else {}
        )

        indices_by_day: dict[date, list[int]] = defaultdict(list)
        indices_by_unit: dict[date, int] = {}
        self._index_by_event = {}
        self._rail_press = None  # stale day anchors must not outlive the model
        self._drag_range = None  # ...nor may a wash band paint onto a new scale
        self._event_press = None  # W5 D5: an external rebuild kills the move…
        self._edit_preview = None  # …and its ghost with it (cancel, no write)
        self._serif_press = None  # …and a serif press/stretch just as much
        self._follow_day = None
        self._press_index = -1
        for idx, row in enumerate(self._rows):
            indices_by_day[row.date].append(idx)
            if row.kind is RowKind.UNIT:
                indices_by_unit.setdefault(row.date, idx)
            if row.event_id is not None:
                self._index_by_event[row.event_id] = idx

        segs_by_row: dict[int, list[_BracketSeg]] = defaultdict(list)
        one_day = timedelta(days=1)
        for event in events:
            if event.id not in self._lanes:
                continue  # a one-day span owns no bracket lane
            lane = self._lanes[event.id]
            span_end = (
                range_end_eff if event.end_date is None
                else min(event.end_date, range_end_eff)
            )
            if self._unit is ScaleUnit.DAY:
                day = event.start_date
                while day <= span_end:
                    for idx in indices_by_day.get(day, ()):
                        segs_by_row[idx].append(
                            _BracketSeg(
                                lane=lane,
                                serif_top=day == event.start_date,
                                serif_bottom=day == span_end,
                            )
                        )
                    day += one_day
            else:
                # W4 3.4/D7: the span paints every unit position it touches —
                # serifs at the first and last touched unit of the window.
                first_unit = _unit_first(event.start_date, self._unit)
                last_unit = _unit_first(span_end, self._unit)
                for unit_date, idx in indices_by_unit.items():
                    if first_unit <= unit_date <= last_unit:
                        segs_by_row[idx].append(
                            _BracketSeg(
                                lane=lane,
                                serif_top=unit_date == first_unit,
                                serif_bottom=unit_date == last_unit,
                            )
                        )

        with QSignalBlocker(self):
            self.clear()
            for idx, row in enumerate(self._rows):
                item = QListWidgetItem()
                item.setSizeHint(QSize(0, ROW_HEIGHT))
                if row.kind is RowKind.EVENT:
                    item.setToolTip(_row_tooltip(row))
                else:
                    # Empty days, unit positions and section heads are not
                    # selectable, not clickable, not even keyboard-reachable
                    # (spec «Пустая позиция не выбирается»; a unit click is
                    # the zoom gesture, handled by the view itself).
                    item.setFlags(Qt.ItemFlag.NoItemFlags)
                item.setData(ROLE_ROW, row)
                item.setData(ROLE_BRACKETS, tuple(segs_by_row.get(idx, ())))
                prev_row = self._rows[idx - 1] if idx else None
                first_of_day = prev_row is None or prev_row.date != row.date
                if self._unit is ScaleUnit.DAY:
                    show_tick = first_of_day
                    # One month label per month, only at its first day (spec).
                    show_month = first_of_day and row.date.day == 1
                    show_year = False
                else:
                    # W4 5.2: one tick per unit position; a year label once a
                    # year on MONTH (January's unit), on every position of the
                    # YEAR rung. Section heads are heads, not units — no tick.
                    show_tick = row.kind is RowKind.UNIT
                    show_month = False
                    show_year = row.kind is RowKind.UNIT and (
                        self._unit is ScaleUnit.YEAR or row.date.month == 1
                    )
                item.setData(ROLE_SHOW_TICK, show_tick)
                item.setData(ROLE_SHOW_MONTH, show_month)
                item.setData(ROLE_SHOW_YEAR, show_year)
                self.addItem(item)
        self._recompute_rail_width()
        self._sync_overlays()
        self.viewport().update()

    def _recompute_rail_width(self) -> None:
        """max(label zone, minimum) — a rotated label's zone ~ font height."""
        self._rail_w = max(RAIL_MIN_WIDTH, RAIL_FIXED_ZONE + self.fontMetrics().height())

    # ── selection / navigation internals ────────────────────────────────────

    def _apply_selection(self, scroll: bool) -> None:
        """Drive the Qt selection model from ``_selected_id`` (no signals out)."""
        idx = None
        with QSignalBlocker(self):
            selection = self.selectionModel()
            if self._selected_id is not None:
                idx = self._index_by_event.get(self._selected_id)
            if selection is not None:
                selection.clearSelection()
                if idx is not None:
                    index = self.model().index(idx, 0)
                    selection.select(
                        QItemSelection(index, index),
                        QItemSelectionModel.SelectionFlag.ClearAndSelect
                        | QItemSelectionModel.SelectionFlag.Rows,
                    )
                    # The current row follows the selection too — it is the
                    # anchor the jump commands start from (D8).
                    self.setCurrentIndex(index)
                else:
                    self.setCurrentIndex(QModelIndex())
        if idx is not None and scroll:
            # Selection from outside also reveals the row (spec «Выбор из поиска»).
            self.scrollToItem(self.item(idx), QAbstractItemView.ScrollHint.PositionAtCenter)
        self.viewport().update()

    def _reveal_row(self, idx: int) -> None:
        """Move the reading position to ``idx`` (D8): scroll + jump anchor.

        The id-contract stays untouched — ``_selected_id`` is not moved and
        no id-signal fires, so the detail panel keeps its event: the jump
        commands navigate, they do not select. The plain ``setCurrentIndex``
        this W3b command predates moves Qt's own current/highlight bookkeeping
        along to the row (unlike the rail jump, :meth:`_jump_to_day_row`,
        which anchors through ``NoUpdate``); only the reading position is
        semantically meaningful here (task 5.2: jump kept as-is in W3c).
        """
        with QSignalBlocker(self):
            self.setCurrentIndex(self.model().index(idx, 0))
        self.scrollToItem(self.item(idx), QAbstractItemView.ScrollHint.PositionAtCenter)

    def _jump_base_index(self) -> int:
        """Row the jump commands start from: current, else top visible."""
        current = self.currentRow()
        return current if current >= 0 else self.top_visible_index()

    def _on_clicked(self, index: QModelIndex) -> None:
        event_id = self._event_id_at(index)
        if event_id is None:
            return
        self._selected_id = event_id  # the view already moved the selection
        self.event_selected.emit(event_id)

    def _on_double_clicked(self, index: QModelIndex) -> None:
        event_id = self._event_id_at(index)
        if event_id is not None:
            self.event_double_clicked.emit(event_id)

    @staticmethod
    def _event_id_at(index: QModelIndex) -> int | None:
        if not index.isValid():
            return None
        row = index.data(ROLE_ROW)
        return row.event_id if isinstance(row, Row) else None

    # ── themes / overlays / Qt plumbing ─────────────────────────────────────

    def _retheme(self) -> None:
        """Repaint from the new tokens; selection/scroll deliberately untouched."""
        self._rebuild_palette()
        self.viewport().update()

    def _rebuild_palette(self) -> None:
        """Rebuild the paint-pass palette and restyle the sticky band (D10).

        The sticky band needs an *opaque* surface (rows scroll underneath) and
        an accent hairline — both computed from tokens, never a source-level
        hex; off-skin the named Qt globals stand in (spec «Вне скина»).
        """
        self._palette = rows_palette(self._theme)
        bg = self._palette.background.name()
        hairline = self._palette.hairline.name()
        self._sticky.setStyleSheet(
            "QLabel { background-color: " + bg + ";"
            " border-bottom: 1px solid " + hairline + ";"
            " padding-left: 8px; }"
        )

    def _sync_overlays(self) -> None:
        """Reposition the overlays and refresh the sticky date (D7)."""
        self._sticky.setGeometry(0, 0, self.width(), STICKY_HEIGHT)
        viewport = self.viewport()
        self._hint.setGeometry(
            viewport.x(), viewport.y(), viewport.width(), viewport.height()
        )
        self._hint.setVisible(self.count() == 0)
        if self.count() == 0:
            self._sticky.hide()  # hidden while empty, the hint stays (spec)
            return
        self._refresh_sticky_text()

    def _refresh_sticky_text(self) -> None:
        """The sticky date: the top row's unit (sync) with the follow unit
        over it while the rail hover is active (W3c D5).

        One funnel for both writers — a scroll/reload sync and a hover update
        can never leave each other's text stale (design risk note): sync runs
        first, follow wins while set. On the W4 large rungs the caption is the
        unit's own signature, day rung keeps the full game date (5.3).
        """
        if self._follow_day is not None:
            text = unit_caption(self._follow_day, self._unit)
        else:
            item = self.itemAt(self.viewport().rect().topLeft())
            if item is None:  # scrolled fully past the end — keep the last date
                self._sticky.show()
                return
            row = item.data(ROLE_ROW)
            if not isinstance(row, Row):
                self._sticky.show()
                return
            text = unit_caption(row.date, self._unit)
        if self._sticky.text() != text:
            self._sticky.setText(text)
        self._sticky.show()

    def _rail_index_at(self, y: int) -> int | None:
        """First row of the day at the rail's viewport y (W3c D3).

        Equal-height rows make the hit-test pure division; the scrollbar rides
        on as whole rows (ScrollPerItem), and ``index_at_y`` clamps to the row
        block — which is what keeps presses/releases outside the laid-out
        range on their nearest day.
        """
        return index_at_y(
            self._rows, ROW_HEIGHT, y + ROW_HEIGHT * self.verticalScrollBar().value()
        )

    def _visible_cursor_day(self, y: int) -> date | None:
        """The day a range-drag maps to (D6): only ``y`` is significant and it
        is clamped to the viewport, so a cursor past an edge resolves to that
        edge's last visible day — which is what a release outside the list
        applies. ``None`` when there is no model to map onto.
        """
        if not self._rows:
            return None
        bottom = max(self.viewport().height() - 1, 0)
        idx = self._rail_index_at(min(max(y, 0), bottom))
        return None if idx is None else self._rows[idx].date

    def _update_follow_day(self, pos: QPoint) -> None:
        """D5 follow flag: while the cursor sits in the rail the overlay shows
        the day under it; anywhere else it falls back to the top row's date.
        During an active range drag :meth:`mouseMoveEvent` keeps the flag set
        past the rail's edge (and across :meth:`leaveEvent`) on its own."""
        idx = self._rail_index_at(pos.y()) if pos.x() < self.rail_width() else None
        day = self._rows[idx].date if idx is not None else None
        if day != self._follow_day:
            self._follow_day = day
            self._refresh_sticky_text()

    def _jump_to_day_row(self, idx: int) -> None:
        """The click-jump (W3c D4): the pressed day becomes the top row under
        the sticky date and the current row (the jump anchor) follows it.

        PositionAtTop — pinned to the top edge, not centered, so the day's
        whole context below stays on screen. The reading position moves via
        the selection model with ``NoUpdate`` because the gesture *navigates*:
        ``QListView::setCurrentIndex`` follows its default command and would
        also *select* the landed row (and refuse to move onto a disabled
        empty-day row), while the spec keeps the selection, ``_selected_id``
        and the id-signals untouched.
        """
        item = self.item(idx)
        if item is None:
            return
        self.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtTop)
        selection = self.selectionModel()
        if selection is not None:
            selection.setCurrentIndex(
                self.model().index(idx, 0),
                QItemSelectionModel.SelectionFlag.NoUpdate,
            )

    # ── ladder internals (W4 5.3–5.5) ───────────────────────────────────────

    def _top_date(self) -> date | None:
        """Date of the date under the sticky band (top visible row, else head)."""
        if not self._rows:
            return None
        return self._rows[max(self.top_visible_index(), 0)].date

    def _unit_index_at(self, day: date) -> int | None:
        """Index of the position whose unit contains ``day`` (nearest if the
        sample starts later) — the ladder's re-entry anchor."""
        if not self._rows:
            return None
        idx = 0
        for i, row in enumerate(self._rows):
            if row.date <= day:
                idx = i
            else:
                break
        return idx

    def _reassert_selection(self) -> None:
        """Re-highlight the pending selection after a ladder re-model.

        On a rung where the event owns no line the highlight simply has no
        row to paint (``_apply_selection`` clears the Qt selection while
        ``_selected_id`` stays pending — task 4.3/5.7: switching never drops
        the selection), and returning to DAY brings the row back.
        """
        if self._selected_id is None:
            return
        self._apply_selection(scroll=False)
        idx = self._index_by_event.get(self._selected_id)
        if idx is not None:
            self.scrollToItem(
                self.item(idx), QAbstractItemView.ScrollHint.EnsureVisible
            )

    def _zoomed_unit(self, steps: int) -> ScaleUnit | None:
        """The rung ``steps`` positions along the ladder (negative = finer),
        ``None`` when the step would leave «сутки · месяц · год»."""
        idx = LADDER.index(self._unit) + steps
        if not 0 <= idx < len(LADDER):
            return None
        return LADDER[idx]

    def _step_scale(self, finer: bool) -> None:
        """Ctrl/Cmd + wheel one notch: one ladder step with the W4 anchor —
        zooming in anchors on the unit under the sticky label, zooming out on
        the first visible date; the scroll step itself never moves (spec
        «Колесо с Ctrl меняет ступень, а не прокрутку»)."""
        unit = self._zoomed_unit(-1 if finer else 1)
        if unit is None:
            return  # DAY is the bottom of the ladder: zoom-out beyond it is inert
        anchor = self._top_date()
        self.set_view(unit=unit, anchor_date=anchor)
        self.scale_changed.emit(unit)

    def zoom_into_unit(self, unit_date: date) -> None:
        """Click on a month/year position: zoom in one rung anchored there
        (spec «Клик по месяцу приближает»), without any selection/id signal."""
        unit = self._zoomed_unit(-1)
        if unit is None:
            return
        self.set_view(unit=unit, anchor_date=unit_date)
        self.scale_changed.emit(unit)

    def mousePressEvent(self, event) -> None:  # Qt API name
        if (
            event.button() == Qt.MouseButton.LeftButton
            and event.position().x() < self.rail_width()
        ):
            # W5 3.1 (D1): the bottom-serif hit-zone test runs *before* the
            # rail branch — a press on a closed multi-day bracket's serif
            # belongs to the end-stretch and never arms the jump/range-drag.
            # The rail arm is untouched for every other rail point (spec
            # «Промах мимо засечки остаётся рейкой», «Засечка открытой скобки
            # не ручка» — the core map excludes one-day and open spans).
            serif_target = self._serif_target_at(
                int(event.position().x()), int(event.position().y()),
            )
            if serif_target is not None:
                self._press_index = -1
                pressed_row = self._rows[self._index_by_event[serif_target.event_id]]
                self._serif_press = _SerifPress(
                    event_id=serif_target.event_id,
                    press_y=int(event.position().y()),
                    start=pressed_row.start,
                    end=pressed_row.end,
                )
                event.accept()
                return
            # W3c D1: the rail owns its zone — the press arms the click/drag
            # gesture on the day under the cursor and never reaches the base
            # class, so a rail press selects nothing and emits no ``clicked``.
            self._press_index = -1
            anchor = self._rail_index_at(int(event.position().y()))
            self._rail_press = None if anchor is None else _RailPress(
                anchor_index=anchor, press_y=int(event.position().y()),
            )
            event.accept()
            return
        # W4 5.5: a left press on a UNIT position belongs to the zooming click
        # (disabled rows never select/click via the base machinery anyway) —
        # consume it here so the re-model on release can never leave a stale
        # pressed index behind.
        pressed = (
            self.indexAt(event.position().toPoint()).row()
            if event.button() == Qt.MouseButton.LeftButton else -1
        )
        self._press_index = pressed
        if (
            0 <= pressed < len(self._rows)
            and self._rows[pressed].kind is RowKind.UNIT
        ):
            event.accept()
            return
        if self._unit is ScaleUnit.DAY and 0 <= pressed < len(self._rows):
            self._arm_event_press(pressed, int(event.position().y()))
            if (
                self._event_press is not None
                and self._rows[pressed].kind is RowKind.EMPTY_DAY
            ):
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # Qt API name
        press = self._rail_press
        if press is not None and event.button() == Qt.MouseButton.LeftButton:
            self._rail_press = None
            # D6: the drag state is dropped *before* the resolve — the apply
            # emit may synchronously rebuild the model, and no stale wash may
            # survive into (or repaint over) the new scale.
            drag, self._drag_range = self._drag_range, None
            y = int(event.position().y())
            if drag is not None:
                anchor_day = self._rows[press.anchor_index].date
                end_day = self._visible_cursor_day(y)
                # D6/D7: a day-crossing drag applies exactly once, here, on
                # the release position (a cursor past an edge lands on the
                # last visible day). A range that stayed inside one day is
                # the click-jump instead (spec «Однодневный drag равен клику»).
                start, end = normalize_range(
                    anchor_day, anchor_day if end_day is None else end_day
                )
                if start == end:
                    self._jump_to_day_row(press.anchor_index)
                else:
                    # W4 D3: on the large rungs the pair holds unit anchors —
                    # the emit normalizes them to full dates (1-е число /
                    # last-day месяца, 1 янв / 31 дек года). DAY is unchanged.
                    self.day_range_applied.emit(start, _unit_last(end, self._unit))
                if self.count():  # the emit path may have rebuilt the model
                    self._update_follow_day(event.position().toPoint())
            elif abs(y - press.press_y) < DRAG_START_THRESHOLD_PX:
                # D2: the release decision splits on the drag threshold —
                # under it this is the click-jump (D4); on the large rungs the
                # same jump runs per unit (W4 5.5, spec «Прыжок на пустой
                # день» — любой ступени).
                self._jump_to_day_row(press.anchor_index)
            # D2: a past-threshold release with no drag move under it stays
            # consumed inert — the base class never sees any rail release, so
            # the list can neither select nor start a gesture from the rail.
            self.viewport().update()
            event.accept()
            return
        serif_press = self._serif_press
        if serif_press is not None and event.button() == Qt.MouseButton.LeftButton:
            # W5 3.2, inheriting the W3c-D6/EVENT-press pattern: the gesture
            # state is dropped *before* resolving — the latched stretch commits
            # exactly one ``event_dates_moved`` carrying the OLD start and the
            # clamped preview end. A sub-threshold release was still owned by
            # the serif arm (the press inside the hit zone belongs to the
            # stretch, spec «Интерактив рейки»), so it stays consumed inert —
            # no jump, no range, no commit, no selection.
            self._serif_press = None
            preview, self._edit_preview = self._edit_preview, None
            self.viewport().update()
            if preview is not None:
                if self._follow_day is not None:
                    self._follow_day = None
                    self._refresh_sticky_text()
                self.event_dates_moved.emit(
                    serif_press.event_id, preview[1], preview[2]
                )
                if self.count():  # the commit path may have rebuilt the model
                    self._update_follow_day(event.position().toPoint())
                self.viewport().update()
            event.accept()
            return
        event_press = self._event_press
        if event_press is not None and event.button() == Qt.MouseButton.LeftButton:
            self._event_press = None
            preview, self._edit_preview = self._edit_preview, None
            if preview is not None:
                # W5 D6, inheriting the W3c-D6 pattern: the gesture state is
                # dropped *before* committing — the ``event_dates_moved`` slot
                # may synchronously reload and rebuild the model, and no
                # preview state may survive into (or paint over) the new
                # scale. A release below the threshold never gets here: the
                # base class still resolves it as the plain selection click.
                if self._follow_day is not None:
                    self._follow_day = None
                    self._refresh_sticky_text()
                self.viewport().update()
                self.event_dates_moved.emit(
                    event_press.event_id, preview[1], preview[2]
                )
                if self.count():  # the commit path may have rebuilt the model
                    self._update_follow_day(event.position().toPoint())
                self.viewport().update()
                event.accept()
                return
        if event.button() == Qt.MouseButton.LeftButton:
            pressed = self._press_index
            self._press_index = -1
            idx = self.indexAt(event.position().toPoint()).row()
            if (
                0 <= pressed < len(self._rows)
                and idx == pressed
                and self._rows[pressed].kind is RowKind.UNIT
            ):
                # W4 5.5: a click on a month/year position zooms one step with
                # that unit as anchor — a position is never a selection, so
                # the base class (and its id-signals) never sees this release.
                self.zoom_into_unit(self._rows[pressed].date)
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # Qt API name
        if (
            event.button() == Qt.MouseButton.LeftButton
            and event.position().x() < self.rail_width()
        ):
            event.accept()  # D8: a rail double-click stays mute — no select, no edit
            return
        if self._edit_preview is not None:
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event) -> None:  # Qt API name
        pos = event.position().toPoint()
        row = self.indexAt(pos).row()
        if row != self._hover_row:
            self._hover_row = row
            self.viewport().update()
        press = self._rail_press
        if press is not None and bool(event.buttons() & Qt.MouseButton.LeftButton):
            # D1: the rail consumed the press, so it owns every with-button
            # move too — the base class must not select, rubber-band or
            # auto-scroll from a rail gesture (W3b hover machinery is driven
            # by buttonless moves and stays intact).
            if (
                self._drag_range is not None
                or abs(pos.y() - press.press_y) >= DRAG_START_THRESHOLD_PX
            ):
                # D2/D6: past the threshold the gesture is a range drag —
                # latched until release, only y significant (clamped to the
                # viewport: no autoscroll exists, so the clamp stays glued to
                # the same visible days for the whole gesture), normalized
                # against the armed anchor day.
                day = self._visible_cursor_day(pos.y())
                if day is not None:
                    self._drag_range = normalize_range(
                        self._rows[press.anchor_index].date, day
                    )
                    if self._follow_day != day:
                        # D5: the sticky follows the drag's day past the
                        # rail's edge — into the text zone and beyond alike.
                        self._follow_day = day
                        self._refresh_sticky_text()
                    self.viewport().update()
            else:
                self._update_follow_day(pos)
            event.accept()
            return
        serif_press = self._serif_press
        if serif_press is not None and bool(event.buttons() & Qt.MouseButton.LeftButton):
            if (
                self._edit_preview is not None
                or abs(pos.y() - serif_press.press_y) >= DRAG_START_THRESHOLD_PX
            ):
                self._retarget_edit(pos.y())
            else:
                self._update_follow_day(pos)
            event.accept()
            return
        event_press = self._event_press
        if (
            event_press is not None
            and bool(event.buttons() & Qt.MouseButton.LeftButton)
            and (
                self._edit_preview is not None
                or abs(pos.y() - event_press.press_y) >= DRAG_START_THRESHOLD_PX
            )
        ):
            self._retarget_edit(pos.y())
            event.accept()
            return
        self._update_follow_day(pos)
        super().mouseMoveEvent(event)

    def keyPressEvent(self, event) -> None:  # Qt API name
        if event.key() == Qt.Key.Key_Escape and self._edit_preview is not None:
            # W5 D5: Esc aborts a latched move or stretch — no commit, no
            # signal, and the armed press goes with it (before the threshold
            # Esc and so is a no-op).
            self._event_press = None
            self._serif_press = None
            self._edit_preview = None
            if self._follow_day is not None:
                self._follow_day = None
                self._refresh_sticky_text()
            self.viewport().update()
            event.accept()
            return
        super().keyPressEvent(event)

    def leaveEvent(self, event) -> None:  # Qt API name
        if self._hover_row != -1:
            self._hover_row = -1
            self.viewport().update()
        if (
            self._follow_day is not None
            and self._drag_range is None
            and self._edit_preview is None
        ):
            # No gesture is active: leaving the list hands the sticky overlay
            # back to the top row's date (D5). An active range drag — or an
            # active W5 move, whose target lives under the cursor outside the
            # viewport by design — keeps the follow flag set across the leave
            # (spec «Follow во время drag'а»).
            self._follow_day = None
            self._refresh_sticky_text()
        super().leaveEvent(event)

    def wheelEvent(self, event) -> None:  # Qt API name
        """One notch == exactly one row (spec «Шаг прокрутки колеса»).

        ``ScrollPerItem`` alone is not enough: Qt multiplies a notch by the
        platform's wheel-scroll-lines setting (3 lines/notch on macOS), so the
        step is pinned here to a single row in either direction. Ctrl/Cmd +
        колесо no longer scrolls at all — it steps the W4 ladder (5.4),
        zooming in on wheel-up; the other modifiers keep the plain one-row
        step (spec «иные модификаторы шаг прокрутки менять НЕ SHALL»).
        """
        angle = event.angleDelta().y()
        editing = self._edit_preview is not None
        if event.modifiers() & (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier
        ):
            if editing:
                event.accept()
                return
            if angle != 0:
                self._step_scale(finer=angle > 0)
            event.accept()  # the wheel belongs to the ladder while Ctrl rides
            return
        if angle == 0:  # e.g. a horizontal trackpad glide — leave it to Qt
            super().wheelEvent(event)
            return
        bar = self.verticalScrollBar()
        bar.setValue(bar.value() + (1 if angle < 0 else -1))
        if editing:
            self._retarget_edit(int(event.position().y()))
        event.accept()

    def resizeEvent(self, event) -> None:  # Qt API name
        super().resizeEvent(event)
        self._sync_overlays()


def filter_chip_text(start: date | None, end: date | None) -> str:
    """Chip caption for a filter state (task 3.1): «Все даты ▾» or game borders."""
    if start is None or end is None:
        return FILTER_CHIP_ALL
    return f"{format_game_date(start)} — {format_game_date(end)} ▾"


class _DateFilterResetButton(QPushButton):
    """Named class so the app-wide popup sheet (W2a D2) can skin the reset:
    the sheet must never carry a generic ``QPushButton`` rule (canvas-proxy
    leak), so every popup-owned widget needs its own selector."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class _DateFilterPopup(QWidget):
    """Top-level two-calendar range popover behind the header chip (W3b D9).

    A ``Qt.Popup`` window — dismiss on click-outside and Esc come from Qt; the
    calendars are the game-skinned ``_CustomCalendar`` reused from
    ``custom_date_edit`` (custom month names included). Being top-level it is
    skinned by the application-wide popup sheet (named classes in
    ``compile_popup_qss``), not by an inline stylesheet, and it is not clipped
    by the panel's narrow minimum width.

    Picking (D9): the first click arms the start, the second applies
    ``range_applied(start, end)`` and closes; an earlier second tap re-arms a
    new start instead of emitting a backwards range. «Сбросить» closes with
    ``range_applied(None, None)`` (chip returns to «Все даты»). When the room
    under the chip cannot host both calendars only one stays visible and the
    two taps assign start/finish there — the tip label mirrors the assignment.
    """

    range_applied = Signal(object, object)  # (start date | None, end date | None)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("timelineDateFilterPopup")  # identifier, not style
        # A plain QWidget only paints the sheet's background with the flag on.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._pending_start: date | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        self.tip_label = QLabel(FILTER_PICK_START)
        layout.addWidget(self.tip_label)
        self.start_calendar = _CustomCalendar(self)
        self.end_calendar = _CustomCalendar(self)
        layout.addWidget(self.start_calendar)
        layout.addWidget(self.end_calendar)
        reset_row = QHBoxLayout()
        reset_row.addStretch()
        self.reset_button = _DateFilterResetButton(FILTER_RESET_TEXT)
        reset_row.addWidget(self.reset_button)
        layout.addLayout(reset_row)

        self.start_calendar.clicked.connect(self._on_day_clicked)
        self.end_calendar.clicked.connect(self._on_day_clicked)
        self.reset_button.clicked.connect(self._on_reset)

    # ── opening ─────────────────────────────────────────────────────────────

    def open_at(self, anchor: QWidget, current: tuple | None = None) -> None:
        """Arm a fresh pick and drop the popover under ``anchor`` (the chip).

        Month names are re-read on every open (``refresh_month_names`` reads
        the process-global map), so a rename while the panel stood idle is
        visible without any wiring around it.
        """
        self._pending_start = None
        self.tip_label.setText(FILTER_PICK_START)
        self.start_calendar.refresh_month_names()
        self.end_calendar.refresh_month_names()
        start, end = current or (None, None)
        for cal, day in ((self.start_calendar, start), (self.end_calendar, end)):
            if day is not None:
                qday = QDate(day.year, day.month, day.day)
                cal.setSelectedDate(qday)
                cal.setCurrentPage(qday.year(), qday.month())
        pos = anchor.mapToGlobal(QPoint(0, anchor.height() + 2))
        screen = anchor.screen()
        room = (
            screen.availableGeometry().bottom() - pos.y()
            if screen is not None else 0
        )
        self._fit_low_screen(room)
        self.adjustSize()
        if screen is not None:
            geo = screen.availableGeometry()
            pos.setX(max(geo.left(), min(pos.x(), geo.right() - self.width() + 1)))
        self.move(pos)
        self.show()

    def _fit_low_screen(self, available_below: int) -> None:
        """Low-screen fallback (D9 risk note): one calendar, taps assign both."""
        need = FILTER_DOUBLE_HEIGHT_FACTOR * self.start_calendar.sizeHint().height()
        self.end_calendar.setVisible(available_below >= need)

    # ── tap handling ────────────────────────────────────────────────────────

    def _on_day_clicked(self, qdate: QDate) -> None:
        chosen = qdate.toPython()
        if self._pending_start is None or chosen < self._pending_start:
            # First tap arms the start; a second tap *before* it re-arms a new
            # start rather than emitting a backwards range.
            self._pending_start = chosen
            self.start_calendar.setSelectedDate(qdate)
            self.end_calendar.setSelectedDate(qdate)
            self.tip_label.setText(FILTER_PICK_END)
            return
        self.range_applied.emit(self._pending_start, chosen)
        self.close()

    def _on_reset(self) -> None:
        self._pending_start = None
        self.range_applied.emit(None, None)
        self.close()


class TimelineWidget(QWidget):
    """Left-panel timeline: header (add, chip filter, jump row) above the list.

    The filter surface is the single chip (D9): the W3 date fields with
    «Применить»/«Очистить» are gone — the popover applies live and resets
    inside itself. The freed slot became the jump-navigation row (D8), paired
    with ``Alt+Up``/``Alt+Down`` scoped to the panel.
    """

    event_selected = Signal(int)  # event_id (W3 id-contract, preserved by W3b)
    event_double_clicked = Signal(int)  # event_id
    add_event_requested = Signal()
    add_entity_requested = Signal(str)  # entity_type: character/location/organization/item
    event_types_requested = Signal()  # W4 6.2: «Типы событий…» from the «+» menu
    filter_changed = Signal(object, object)  # (start_date | None, end_date | None)
    event_dates_moved = Signal(object, object, object)  # W5: (event_id, start, end|None)

    def __init__(
        self,
        timeline_vm,
        parent: QWidget | None = None,
        theme=None,
    ) -> None:
        super().__init__(parent)
        self._vm = timeline_vm
        self._theme = theme
        self._filter_range: tuple[date | None, date | None] = (None, None)
        self._init_ui()
        self._apply_theme()

    def _apply_theme(self) -> None:
        """One attach point: the chrome container carries the whole sheet.

        The list subscribes to the runtime itself (its delegates paint outside
        QSS); the header keeps the catalog sheet.
        """
        if self._theme is not None:
            attach_theme(self.chrome, self._theme)
            self._theme.apply()

    def _init_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.chrome = QWidget()
        self.chrome.setObjectName("timelineChrome")  # identifier, not style
        outer.addWidget(self.chrome)
        layout = QVBoxLayout(self.chrome)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Header row 1 — title, filter chip, «+» menu (task 3.1: the chip
        # replaces the CustomDateEdit pair; the «+» menu is untouched).
        header = QHBoxLayout()
        header.addWidget(title("Таймлайн событий"))
        header.addStretch()

        self.filter_chip = QPushButton(filter_chip_text(None, None))
        self.filter_chip.setToolTip("Фильтр по датам")
        self.filter_chip.clicked.connect(self._on_chip_clicked)
        header.addWidget(self.filter_chip)

        self.add_button = QPushButton("+")
        self.add_button.setFixedSize(30, 30)
        self.add_button.setToolTip("Добавить событие (правый клик — другие сущности)")
        self.add_button.clicked.connect(self.add_event_requested.emit)
        self.add_button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.add_button.customContextMenuRequested.connect(self._on_add_context_menu)
        header.addWidget(self.add_button)
        layout.addLayout(header)

        # W4 6.2: «Типы событий…» joins the «+» context menu (member action so
        # tests can enumerate it; the menu's own exec result drives the emit,
        # mirroring the five create items — the action itself stays unconnected
        # to avoid a double signal when Qt triggers it from the menu).
        self.event_types_action = QAction("Типы событий…", self)
        self.event_types_action.setObjectName("eventTypesAction")

        # Header row 2 (task 3.1/D8) — jump navigation in the slot the removed
        # «Применить»/«Очистить» pair occupied; shortcuts mirror the buttons.
        # W4 5.7: the ladder and grouping switchers join this row without
        # displacing the chip/«+»/jump controls; checked state mirrors the
        # ViewModel knobs and survives every re-model.
        nav_row = QHBoxLayout()
        self.scale_buttons: dict[ScaleUnit, QPushButton] = {}
        for unit, caption in LADDER_CAPTIONS:
            button = QPushButton(caption)
            button.setObjectName(f"scale{unit.value.title()}Button")
            button.setCheckable(True)
            button.setToolTip(f"Ступень шкалы: {caption}")
            button.clicked.connect(
                lambda _checked=False, u=unit: self._on_scale_chosen(u)
            )
            self.scale_buttons[unit] = button
            nav_row.addWidget(button)
        self.scale_buttons[ScaleUnit.DAY].setChecked(True)
        nav_row.addSpacing(6)
        self.group_button = QToolButton()
        self.group_button.setObjectName("groupSwitchButton")
        self.group_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.group_button.setToolTip("Группировка по сущностям")
        group_menu = QMenu(self.group_button)
        self.group_actions: dict = {}
        for kind in GROUPING_ORDER:
            action = group_menu.addAction(GROUPING_CAPTIONS[kind])
            action.setCheckable(True)
            action.triggered.connect(
                lambda _checked=False, k=kind: self._on_group_chosen(k)
            )
            self.group_actions[kind] = action
        self.group_actions[None].setChecked(True)
        self.group_button.setMenu(group_menu)
        self.group_button.setText(
            f"группа: {GROUPING_CAPTIONS[None]} \u25be"
        )
        nav_row.addWidget(self.group_button)
        nav_row.addStretch()
        self.jump_prev_button = QPushButton("⤒")
        self.jump_prev_button.setFixedSize(30, 30)
        self.jump_prev_button.setToolTip("К предыдущему событию (Alt+Up)")
        self.jump_prev_button.clicked.connect(self.jump_prev_event)
        nav_row.addWidget(self.jump_prev_button)
        self.jump_next_button = QPushButton("⤓")
        self.jump_next_button.setFixedSize(30, 30)
        self.jump_next_button.setToolTip("К следующему событию (Alt+Down)")
        self.jump_next_button.clicked.connect(self.jump_next_event)
        nav_row.addWidget(self.jump_next_button)
        layout.addLayout(nav_row)

        # Live range popover (task 3.2): top-level, skinned through the
        # app-wide popup sheet; parented to the panel for lifetime only.
        self.filter_popup = _DateFilterPopup(self)
        self.filter_popup.range_applied.connect(self._on_filter_range)

        # Jump shortcuts (task 3.3/D8): active only while focus is inside the
        # panel; Alt+Up/Alt+Down are free in the rest of the app (design D8).
        jump_prev_shortcut = QShortcut(QKeySequence("Alt+Up"), self)
        jump_prev_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        jump_prev_shortcut.activated.connect(self.jump_prev_event)
        jump_next_shortcut = QShortcut(QKeySequence("Alt+Down"), self)
        jump_next_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        jump_next_shortcut.activated.connect(self.jump_next_event)

        # Event scale (W3b: vertical day list replaces the Gantt canvas).
        self.rows_view = TimelineListView(theme=self._theme)
        self.rows_view.event_selected.connect(self.event_selected.emit)
        self.rows_view.event_double_clicked.connect(self.event_double_clicked.emit)
        # D7: the rail drag is the filter's second entrance — the exact same
        # apply path as the popover, so the chip mirrors it and the panel's
        # single filter_changed contract stays untouched.
        self.rows_view.day_range_applied.connect(self._on_filter_range)
        self.rows_view.event_dates_moved.connect(self.event_dates_moved.emit)
        # W4 5.4–5.5: a wheel/click ladder step inside the list is mirrored
        # into the ViewModel (its setter stays the single mutation point).
        self.rows_view.scale_changed.connect(self._on_view_scale_changed)
        layout.addWidget(self.rows_view, 1)

    # ── W4 ladder switchers (tasks 5.4/5.5/5.7) ──────────────────────────

    def _view_knobs(self) -> tuple | None:
        """The ViewModel's ladder knobs, or ``None`` while the VM is a stand-in
        (test doubles expose a MagicMock ``unit`` that no ladder recognizes)."""
        unit = getattr(self._vm, "unit", None)
        group_by = getattr(self._vm, "group_by", None)
        if not isinstance(unit, ScaleUnit):
            return None
        if group_by is not None and not isinstance(group_by, EntityKind):
            return None
        return unit, group_by

    def _sync_from_vm(self) -> None:
        """Reflect the ViewModel's knobs into the list and the switchers.

        The VM is the single mutation point: header clicks write ``vm.unit``
        /``vm.group_by`` (its setters rebuild rows, keep selection + filter —
        tasks 4.1/4.3) and this method mirrors the result into the list via
        :meth:`TimelineListView.set_view` (anchor-keeping, selection-pending).
        """
        knobs = self._view_knobs()
        if knobs is None:
            return
        unit, group_by = knobs
        self.rows_view.set_view(unit=unit, group_by=group_by)
        self._sync_switcher(unit, group_by)

    def _sync_switcher(self, unit: ScaleUnit, group_by) -> None:
        for rung, button in self.scale_buttons.items():
            button.setChecked(rung is unit)
        for kind, action in self.group_actions.items():
            action.setChecked(kind is group_by)
        self.group_button.setText(
            f"группа: {GROUPING_CAPTIONS[group_by]} \u25be"
        )

    def _on_scale_chosen(self, unit: ScaleUnit) -> None:
        """Header ladder click: write through the VM, then mirror (5.7)."""
        if self.rows_view.edit_preview() is not None:
            self._sync_from_vm()
            return
        self._vm.unit = unit
        self._sync_from_vm()

    def _on_group_chosen(self, kind) -> None:
        """Header grouping click: same write-through path as the ladder (5.7)."""
        if self.rows_view.edit_preview() is not None:
            self._sync_from_vm()
            return
        self._vm.group_by = kind
        self._sync_from_vm()

    def _on_view_scale_changed(self, unit) -> None:
        """The list stepped the ladder itself (Ctrl/Cmd wheel, unit click):
        mirror into the VM without echoing a re-model back into the list."""
        self._vm.unit = unit
        knobs = self._view_knobs()
        self._sync_switcher(*(knobs or (unit, None)))

    def _on_add_context_menu(self, pos) -> None:
        menu = QMenu(self)
        act_event = menu.addAction("Новое событие")
        act_char = menu.addAction("Новый персонаж")
        act_loc = menu.addAction("Новая локация")
        act_org = menu.addAction("Новая организация")
        act_item = menu.addAction("Новый предмет")
        menu.addSeparator()
        menu.addAction(self.event_types_action)

        global_pos = self.add_button.mapToGlobal(pos)
        action = menu.exec(global_pos)
        if action is act_event:
            self.add_event_requested.emit()
        elif action is act_char:
            self.add_entity_requested.emit("character")
        elif action is act_loc:
            self.add_entity_requested.emit("location")
        elif action is act_org:
            self.add_entity_requested.emit("organization")
        elif action is act_item:
            self.add_entity_requested.emit("item")
        elif action is self.event_types_action:
            self.event_types_requested.emit()

    # ── public panel API (task 2.5; mirrors the list's contract) ────────────

    def update_events(self, events: Sequence[Any]) -> None:
        """Refresh the scale; selection survives while the event stays visible.

        The panel's own filter window rides along: with a live chip range the
        scale enumerates exactly those days — the filter's empty days included
        (spec «Пустые и фильтрационные состояния»); without a filter the sample
        derives its own min–max. The ViewModel's ladder knobs ride along too
        (a reload never silently returns to «сутки»).
        """
        self._sync_from_vm()
        start, end = self._filter_range
        self.rows_view.update_events(events, start, end)

    def set_selected(self, event_id: int | None) -> None:
        """Highlight ``event_id`` (idempotent); revealed if not already visible.

        An external selection first mirrors the ViewModel's knobs: an id
        arriving from search/jump while the VM has descended the ladder (its
        ``_ensure_day_unit_for`` already moved ``unit`` to DAY) must find the
        EVENT row the descent just modelled (spec «Внешний выбор с крупной
        ступени спускает лестницу»).
        """
        self._sync_from_vm()
        self.rows_view.set_selected(event_id)

    def scroll_to_event(self, event_id: int) -> None:
        """Scroll the scale just enough to reveal the event's row."""
        self.rows_view.scroll_to_event(event_id)

    # ── ladder-aware jump commands (W4 «Прыжок с месяцной ступени») ────────

    def _descend_for_jump(self) -> None:
        """Unit rungs own no EVENT rows — drop the VM's ladder to DAY and
        re-model before retrying the jump (spec «Навигация к событиям»); a
        no-op when DAY is already current or the VM is a test stand-in."""
        self._vm.unit = ScaleUnit.DAY
        self._sync_from_vm()

    def jump_prev_event(self) -> None:
        """Scroll to the nearest EVENT row before the visible position."""
        if self.rows_view.jump_prev_event():
            return
        self._descend_for_jump()
        self.rows_view.jump_prev_event()

    def jump_next_event(self) -> None:
        """Scroll to the nearest EVENT row after the visible position."""
        if self.rows_view.jump_next_event():
            return
        self._descend_for_jump()
        self.rows_view.jump_next_event()

    def _on_chip_clicked(self) -> None:
        """Drop the live range popover under the chip, seeded with the filter."""
        self.filter_popup.open_at(self.filter_chip, self._filter_range)

    def _on_filter_range(self, start, end) -> None:
        """Popover live-apply (task 3.2): chip caption + the unchanged signal."""
        self._filter_range = (start, end)
        self.filter_chip.setText(filter_chip_text(start, end))
        self.filter_changed.emit(start, end)

    def cover_filter_for_span(self, start: date, end: date | None) -> None:
        """Widen a live chip filter so ``[start, end|start]`` stays inside it.

        No-op without a filter. Expansion uses the existing chip path
        (:meth:`_on_filter_range`) so the caption and ``filter_changed`` stay
        in lockstep (W5 D3).
        """
        fr_start, fr_end = self._filter_range
        if fr_start is None or fr_end is None:
            return
        span_end = start if end is None else end
        if start >= fr_start and span_end <= fr_end:
            return
        self._on_filter_range(min(start, fr_start), max(span_end, fr_end))
