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
    QPointF, QSize, QSignalBlocker, Qt, Signal,
)
from PySide6.QtGui import QColor, QFontMetrics, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMenu, QPushButton, QStyledItemDelegate,
    QStyle, QVBoxLayout, QWidget,
)

from app.presentation.theme.catalog import attach_theme, hint, set_role, title
from app.presentation.theme.compiler import token_rgb
from app.presentation.utils.date_utils import format_game_date, month_name
from app.presentation.views.custom_date_edit import _CustomCalendar
from app.presentation.views.timeline_rows import (
    Row, RowKind, build_rows, index_at_y, next_event_index, normalize_range,
    prev_event_index,
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
BRACKET_X0 = 6             # first bracket lane x
BRACKET_LANE_STEP = 5      # overlapping brackets take neighbouring lanes (D6)
BRACKET_SERIF_W = 6        # horizontal serif at the span's start/end day
BRACKET_MAX_LANES = 4      # lanes before assignment wraps around
MONTH_SHORT_FORM = 3       # first letters of a month name in the short form
TEXT_LEFT_PAD = 8
PEN_WIDTH = 1

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
        )
    tokens, theme = runtime.tokens, runtime.theme
    accent = token_rgb(tokens, theme, "color.accent")
    return _Palette(
        background=_from_rgb(token_rgb(tokens, theme, "color.bg.surface")),
        rail=_from_rgb(token_rgb(tokens, theme, "color.border")),
        bracket=_from_rgb(token_rgb(tokens, theme, "color.border")),
        row_text=_from_rgb(token_rgb(tokens, theme, "color.fg.primary")),
        selected_fill=_from_rgb(accent),
        selected_text=_from_rgb(token_rgb(tokens, theme, "color.accent.fg")),
        hover_fill=_from_rgb(accent, ROW_HOVER_ALPHA),
        drag_fill=_from_rgb(accent, DRAG_WASH_ALPHA),
        month_text=_from_rgb(token_rgb(tokens, theme, "color.fg.muted")),
        hairline=_from_rgb(accent),
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


def _row_tooltip(row: Row) -> str:
    """Tooltip body: full name plus the game-formatted date range (spec)."""
    return f"{row.name}\n{_range_text(row)}"


def _month_labels(day: date) -> tuple[str, str]:
    """(full, short) rail label of the month ``day`` belongs to (game names)."""
    full = format_game_date(day)
    short = f"{month_name(day.month)[:MONTH_SHORT_FORM]} {day.year}"
    return full, short


def bracket_lanes(events: Sequence[Any], range_end: date | None) -> dict[int, int]:
    """Deterministic rail lane per event bracket.

    Brackets spanning the same day must not collide (spec «Пересекающиеся
    привязки»): events are taken in ``(start, id)`` order and each takes the
    first lane whose last bracket already ended before its start; when all
    :data:`BRACKET_MAX_LANES` lanes are busy the assignment wraps — the
    overlap is then visually accepted, still deterministically.

    An open end reaches ``range_end`` without asserting a "current" date; a
    one-day span owns no bracket lane (its day tick already marks it, spec
    «Привязка событий к рейке»).
    """
    spans: list[tuple[Any, date]] = []
    for event in events:
        if range_end is None:
            continue
        eff_end = range_end if event.end_date is None else min(event.end_date, range_end)
        if eff_end > event.start_date:
            spans.append((event, eff_end))
    spans.sort(key=lambda pair: (pair[0].start_date, pair[0].id))
    lane_free_until: dict[int, date] = {}
    lanes: dict[int, int] = {}
    for event, eff_end in spans:
        lane = next(
            (cand for cand in range(BRACKET_MAX_LANES)
             if lane_free_until.get(cand, event.start_date) < event.start_date),
            len(lanes) % BRACKET_MAX_LANES,
        )
        lane_free_until[lane] = eff_end
        lanes[event.id] = lane
    return lanes


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
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = not selected and index.row() == view.hover_index()
        painter.save()
        if selected:
            painter.fillRect(option.rect, palette.selected_fill)
        elif hovered:
            painter.fillRect(option.rect, palette.hover_fill)
        drag = view.drag_range()
        if drag is not None and drag[0] <= row.date <= drag[1]:
            # D6: the live range-drag band over every day it covers — the same
            # view state the hover wash reads; each covered row fills its own
            # slice, so partially visible rows clip the band automatically.
            painter.fillRect(option.rect, palette.drag_fill)
        self._paint_rail(painter, option, index, row, palette)
        if row.kind is RowKind.EVENT:
            self._paint_line(painter, option, row, palette, selected)
        painter.restore()

    def _paint_rail(self, painter, option, index, row: Row, palette: _Palette) -> None:
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
        for seg in index.data(ROLE_BRACKETS) or ():
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
        if index.data(ROLE_SHOW_MONTH):
            self._paint_month_label(painter, option, index, row, rail_w, palette)

    def _paint_month_label(self, painter, option, index, row, rail_w, palette) -> None:
        """Rotated month label climbing from the month's first-day tick (D6).

        Drawn bottom-to-top so it bleeds into the already-painted rows above
        instead of being overpainted by the next row; when the headroom above
        is not enough for the full label, the short form is used.
        """
        full, short = _month_labels(row.date)
        fm = QFontMetrics(option.font)
        label = full if option.rect.top() >= fm.horizontalAdvance(full) else short
        painter.setPen(QPen(palette.month_text))
        painter.save()
        painter.translate(rail_w - RAIL_LABEL_INSET, option.rect.top() + 3)
        painter.rotate(-90)  # local +x runs up ⇒ text reads bottom-to-top
        painter.drawText(0, 0, label)
        painter.restore()

    def _paint_line(self, painter, option, row: Row, palette: _Palette, selected: bool) -> None:
        """The ``start — end · name`` line, elided at the panel edge (tooltip holds all)."""
        rail_w = self._view.rail_width()
        rect = option.rect.adjusted(rail_w + TEXT_LEFT_PAD, 0, -TEXT_LEFT_PAD, 0)
        fm = QFontMetrics(option.font)
        line = _row_line(row)
        elided = fm.elidedText(line, Qt.TextElideMode.ElideRight, max(rect.width(), 0))
        painter.setPen(QPen(palette.selected_text if selected else palette.row_text))
        painter.drawText(
            rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            elided,
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
    stays mute (D8). Selection and scrolling are the view's own; the panel
    drives them through the public API below.
    """

    event_selected = Signal(int)  # event_id
    event_double_clicked = Signal(int)  # event_id
    day_range_applied = Signal(object, object)  # rail drag range (start, end)

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
        self._follow_day: date | None = None  # sticky follow while on the rail (D5)

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
        events: Sequence[Any], range_start: date | None, range_end: date | None
    ) -> tuple:
        """The rebuild key: the ``(id, start, end, name)`` set plus its window.

        The visible range is part of the version (not just the events): the
        same sample under a different filter range is a different scale — the
        filter's empty days must appear whether or not the events moved.
        """
        return (
            tuple((e.id, e.start_date, e.end_date, e.name) for e in events),
            range_start,
            range_end,
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
        version = self._version_of(events, range_start, range_end)
        if version == self._version:
            # Same set — but game month names can move while no event does
            # (month settings reload identical events): repaint the rail
            # labels and the sticky date, rows/selection/scroll stay as they are.
            self._sync_overlays()
            self.viewport().update()
            return
        self._rebuild(events, range_start, range_end)
        if self._selected_id is not None and self._selected_id not in self._index_by_event:
            self._selected_id = None  # excluded from the visible sample (spec)
        if self._selected_id is not None:
            self._apply_selection(scroll=True)
        else:
            with QSignalBlocker(self.verticalScrollBar()):
                self.verticalScrollBar().setValue(0)
            self._sync_overlays()

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

    def jump_prev_event(self) -> None:
        """Scroll to the nearest EVENT row before the visible position (D8).

        Runs of empty days are skipped; at the head of the sample the command
        is inert (``prev_event_index`` returns ``None``).
        """
        idx = prev_event_index(self._rows, self._jump_base_index())
        if idx is not None:
            self._reveal_row(idx)

    def jump_next_event(self) -> None:
        """Mirror of :meth:`jump_prev_event` towards the tail of the sample."""
        idx = next_event_index(self._rows, self._jump_base_index())
        if idx is not None:
            self._reveal_row(idx)

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

        Explicit bounds (a live filter) enumerate exactly those days, empty
        ones included; omitted, the sample's own min–max owns the range.
        """
        self._events = events
        self._version = self._version_of(events, range_start, range_end)
        rows = build_rows(events, range_start, range_end)
        self._rows = tuple(rows)
        # Open-end brackets reach the last day of the visible range — the
        # filter bound when one is live, otherwise what build_rows derived
        # (max(end|start)). The last row is exactly that edge.
        range_end_eff = rows[-1].date if rows else None
        self._lanes = bracket_lanes(events, range_end_eff)

        indices_by_day: dict[date, list[int]] = defaultdict(list)
        self._index_by_event = {}
        self._rail_press = None  # stale day anchors must not outlive the model
        self._drag_range = None  # ...nor may a wash band paint onto a new scale
        self._follow_day = None
        for idx, row in enumerate(self._rows):
            indices_by_day[row.date].append(idx)
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

        with QSignalBlocker(self):
            self.clear()
            for idx, row in enumerate(self._rows):
                item = QListWidgetItem()
                item.setSizeHint(QSize(0, ROW_HEIGHT))
                if row.kind is RowKind.EVENT:
                    item.setToolTip(_row_tooltip(row))
                else:
                    # Empty days are not selectable, not clickable, not even
                    # keyboard-reachable (spec «Пустая позиция не выбирается»).
                    item.setFlags(Qt.ItemFlag.NoItemFlags)
                item.setData(ROLE_ROW, row)
                item.setData(ROLE_BRACKETS, tuple(segs_by_row.get(idx, ())))
                prev_row = self._rows[idx - 1] if idx else None
                first_of_day = prev_row is None or prev_row.date != row.date
                item.setData(ROLE_SHOW_TICK, first_of_day)
                # One month label per month, only at its first day (spec).
                item.setData(ROLE_SHOW_MONTH, first_of_day and row.date.day == 1)
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

        Only the *current* index and the scroll move — the selection (and
        with it the detail panel, which listens to the id signals) stays
        untouched: the jump commands navigate, they do not select.
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
        """The sticky date: the top row's day (sync) with the follow day over
        it while the rail hover is active (W3c D5).

        One funnel for both writers — a scroll/reload sync and a hover update
        can never leave each other's text stale (design risk note): sync runs
        first, follow wins while set.
        """
        if self._follow_day is not None:
            text = format_game_date(self._follow_day)
        else:
            item = self.itemAt(self.viewport().rect().topLeft())
            if item is None:  # scrolled fully past the end — keep the last date
                self._sticky.show()
                return
            row = item.data(ROLE_ROW)
            if not isinstance(row, Row):
                self._sticky.show()
                return
            text = format_game_date(row.date)
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

    def mousePressEvent(self, event) -> None:  # Qt API name
        if (
            event.button() == Qt.MouseButton.LeftButton
            and event.position().x() < self.rail_width()
        ):
            # W3c D1: the rail owns its zone — the press arms the click/drag
            # gesture on the day under the cursor and never reaches the base
            # class, so a rail press selects nothing and emits no ``clicked``.
            anchor = self._rail_index_at(int(event.position().y()))
            self._rail_press = None if anchor is None else _RailPress(
                anchor_index=anchor, press_y=int(event.position().y()),
            )
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
                    self.day_range_applied.emit(start, end)
                if self.count():  # the emit path may have rebuilt the model
                    self._update_follow_day(event.position().toPoint())
            elif abs(y - press.press_y) < DRAG_START_THRESHOLD_PX:
                # D2: the release decision splits on the drag threshold —
                # under it this is the click-jump (D4).
                self._jump_to_day_row(press.anchor_index)
            # D2: a past-threshold release with no drag move under it stays
            # consumed inert — the base class never sees any rail release, so
            # the list can neither select nor start a gesture from the rail.
            self.viewport().update()
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
        self._update_follow_day(pos)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # Qt API name
        if self._hover_row != -1:
            self._hover_row = -1
            self.viewport().update()
        if self._follow_day is not None and self._drag_range is None:
            # No gesture is active: leaving the list hands the sticky overlay
            # back to the top row's date (D5). An active range drag keeps the
            # follow flag set across the leave (spec «Follow во время drag'а»).
            self._follow_day = None
            self._refresh_sticky_text()
        super().leaveEvent(event)

    def wheelEvent(self, event) -> None:  # Qt API name
        """One notch == exactly one row (spec «Шаг прокрутки колеса»).

        ``ScrollPerItem`` alone is not enough: Qt multiplies a notch by the
        platform's wheel-scroll-lines setting (3 lines/notch on macOS), so the
        step is pinned here to a single row in either direction. Zoom does not
        exist (spec): modifiers do not change the step either.
        """
        angle = event.angleDelta().y()
        if angle == 0:  # e.g. a horizontal trackpad glide — leave it to Qt
            super().wheelEvent(event)
            return
        bar = self.verticalScrollBar()
        bar.setValue(bar.value() + (1 if angle < 0 else -1))
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
    filter_changed = Signal(object, object)  # (start_date | None, end_date | None)

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

        # Header row 2 (task 3.1/D8) — jump navigation in the slot the removed
        # «Применить»/«Очистить» pair occupied; shortcuts mirror the buttons.
        nav_row = QHBoxLayout()
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
        layout.addWidget(self.rows_view, 1)

    def _on_add_context_menu(self, pos) -> None:
        menu = QMenu(self)
        act_event = menu.addAction("Новое событие")
        act_char = menu.addAction("Новый персонаж")
        act_loc = menu.addAction("Новая локация")
        act_org = menu.addAction("Новая организация")
        act_item = menu.addAction("Новый предмет")

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

    # ── public panel API (task 2.5; mirrors the list's contract) ────────────

    def update_events(self, events: Sequence[Any]) -> None:
        """Refresh the scale; selection survives while the event stays visible.

        The panel's own filter window rides along: with a live chip range the
        scale enumerates exactly those days — the filter's empty days included
        (spec «Пустые и фильтрационные состояния»); without a filter the sample
        derives its own min–max.
        """
        start, end = self._filter_range
        self.rows_view.update_events(events, start, end)

    def set_selected(self, event_id: int | None) -> None:
        """Highlight ``event_id`` (idempotent); revealed if not already visible."""
        self.rows_view.set_selected(event_id)

    def scroll_to_event(self, event_id: int) -> None:
        """Scroll the scale just enough to reveal the event's row."""
        self.rows_view.scroll_to_event(event_id)

    def jump_prev_event(self) -> None:
        """Scroll to the nearest EVENT row before the visible position."""
        self.rows_view.jump_prev_event()

    def jump_next_event(self) -> None:
        """Scroll to the nearest EVENT row after the visible position."""
        self.rows_view.jump_next_event()

    def _on_chip_clicked(self) -> None:
        """Drop the live range popover under the chip, seeded with the filter."""
        self.filter_popup.open_at(self.filter_chip, self._filter_range)

    def _on_filter_range(self, start, end) -> None:
        """Popover live-apply (task 3.2): chip caption + the unchanged signal."""
        self._filter_range = (start, end)
        self.filter_chip.setText(filter_chip_text(start, end))
        self.filter_changed.emit(start, end)
