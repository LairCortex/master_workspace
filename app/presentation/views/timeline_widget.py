"""Timeline widget — vertical day-ladder event tape (redesign-timeline-day-ladder).

The panel keeps its name, header («+» menu, «Выбор даты» window button,
«Скрыть даты без событий» toggle and jump row) and the W3 id-contract signals. The body is a ``QListWidget`` whose rows come
from the Qt-free ladder core :func:`timeline_rows.build_rows`: one section per
day — a ``DayHeaderRow`` followed by one :class:`EventRow` card *per day the
event covers* (multi-day and open events repeat — every card leads to the same
record), an :class:`EmptyDayRow` placeholder for eventless days, a single
:class:`GapCollapsedRow` for eventless runs longer than
:data:`timeline_rows.GAP_COLLAPSE_DAYS`; the coarser rungs list
``PeriodHeaderRow`` + a per-period ``PeriodCardRow`` counter («N событий» /
«нет событий»). Every position is exactly :data:`ROW_HEIGHT` tall.

The pre-redesign side rail — its tick column, span ties, press-jump /
range-drag hit zones and the end-stretch handle — is gone from the painting
(task 3.1, design D9); ``EntityKind``/``group_by`` entity grouping is deleted
as well (task 8.1). A ``QStyledItemDelegate`` now paints each ladder row: the
event type dot (``color.chart.k`` token, muted for untyped events) + the event
name (open events carry the «бессрочно» mark; full name and date range live in
the tooltip), «+  нет события» placeholders, muted gap captions with
game-formatted bounds, section headers and «N событий» / «нет событий» period
counters. No per-row visibility roles.

The sticky layer is now TWO title labels with a ~120 ms push-out animation
(design D3, task 3.2): :func:`timeline_rows.sticky_state` (core) says which
section the tape's top edge sits under, and when that section changes the
incoming caption slides the current one out upward via a ``QPropertyAnimation``
pair — never an instant text swap. The labels are mouse-transparent children
pinned above the viewport (the viewport keeps a top margin of exactly their
height); the rail-follow mode is deleted — the sticky follows the scroll
position only. Hide-while-empty (with the text hint staying) is preserved
(spec «Липкий заголовок периода»).

The wheel scrolls exactly one position per notch; **Alt/Opt + wheel** steps the
ladder through the ViewModel knob anchored at the row under the cursor (design
D6, task 4.1), while Ctrl/Cmd + wheel is a dead gesture — accepted, no reaction
(spec «Alt-колесо вместо Ctrl»). Colors are token derivatives only (W3b D10): every paint
color is a ``token_rgb`` derivation, the off-skin fallback uses named Qt
globals, and nothing here contains a literal hex or reads the OS palette
(invariant of ``tests/presentation/test_no_chrome_hex.py``, which scans this
file).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Sequence

from PySide6.QtCore import (
    QAbstractAnimation, QDate, QEasingCurve, QEvent, QModelIndex,
    QPropertyAnimation, QPoint, QRect, QSize, QSignalBlocker, Qt, Signal,
)
from PySide6.QtGui import (
    QAction, QColor, QFontMetrics, QKeySequence, QPainter, QPen, QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMenu, QPushButton, QStyledItemDelegate,
    QVBoxLayout, QWidget,
)

from app.presentation.theme.catalog import attach_theme, hint, set_role, title
from app.presentation.theme.compiler import CHART_TOKEN_KEYS, token_rgb
from app.presentation.utils.date_utils import format_game_date
from app.presentation.views.custom_date_edit import _CustomCalendar
from app.presentation.views.timeline_rows import (
    DayHeaderRow, DropAction, EmptyDayRow, EventRow, GapCollapsedRow,
    PeriodCardRow, PeriodHeaderRow, ScaleUnit, apply_drop_action, build_rows,
    content_bottom, drill_target, drop_actions, header_caption, period_span,
    sticky_state, zoom_level, zoom_target,
)

#: Empty-selection hint shown while the list model is empty (spec: пустое
#: состояние — текстовая подсказка вместо пустого пространства).
EMPTY_HINT_TEXT = "Нет событий в диапазоне"

# ── module geometry constants (ladder revision, task 3.1) ───────────────────
ROW_HEIGHT = 24            # equal-height positions; the one density knob (D4)
STICKY_HEIGHT = 26         # sticky-date overlay band == top viewport margin (D7)
#: Push-out duration of the sticky pair (design D3: «~120 ms, ease-out»).
STICKY_PUSH_MS = 120
TEXT_LEFT_PAD = 8
PEN_WIDTH = 1

#: Event type-dot square side, painted left of the card name (over a selection
#: it keeps its token color and gets no outline — W4 D7).
DOT_SIZE = 8
DOT_TEXT_GAP = 4           # gap between the type dot and the line text
#: All text rungs (event cards, placeholders, headers, counters) share one
#: indent so the ladder reads as one column regardless of the row kind.
TEXT_INDENT = TEXT_LEFT_PAD + DOT_SIZE + DOT_TEXT_GAP

#: Fill alpha of the hovered card — an accent-token derivative spelled the way
#: ``accent_rgba`` derives the washes for stylesheets (W3b D10).
ROW_HOVER_ALPHA = 0.25

# ── date-drop gesture (task 5.1/5.2, design D5) ──────────────────────────────
#: Vertical press travel that turns a click on an event card into the drop
#: gesture (spec «Перетаскивание события с выбором действия»: below the
#: threshold the press stays a plain selection click). Also the travel budget
#: of a «Выбор даты» press on the collapsed-gap row: past it the release is a
#: drag, not the pre-filled window request (task 7.1).
DRAG_START_THRESHOLD_PX = 4
#: Alpha of the drop-ghost wash — a ``color.accent`` derivative, no new token
#: (spec «Оформление шкалы из токенов»: «призрак перетаскивания — производная
#: color.accent (альфа 0.35)»). The dragged-out card dims at the same alpha.
GHOST_ALPHA = 0.35
#: Release-menu captions keyed by the core's actions (D5), enumerated in the
#: spec's order: «Перенести» / «Расширить вниз до этого дня» / «Начать раньше
#: в этом дне». Presence per target day is the core's ``drop_actions`` call.
DROP_CAPTIONS: dict = {
    DropAction.MOVE: "Перенести",
    DropAction.EXTEND_DOWN: "Расширить вниз до этого дня",
    DropAction.START_EARLIER: "Начать раньше в этом дне",
}
#: Menu item order (mirrors the spec's listing of the actions).
DROP_ACTION_ORDER = (DropAction.MOVE, DropAction.EXTEND_DOWN, DropAction.START_EARLIER)

# ── ladder captions of the painted row kinds (task 3.1) ─────────────────────
#: Placeholder text of an eventless day, preceded by the «+» entry icon
#: (spec «Инлайн-создание события из пустого дня» — the entry point).
EMPTY_DAY_TEXT = "+  нет события"
#: Explicit open-end mark every card of an open event carries (spec
#: «Бессрочные события»: asserting any end date is not allowed).
OPEN_MARK = "бессрочно"
#: Separates the name from the open-end mark on an open event's card.
OPEN_MARK_SEP = " · "
#: Counter card of a period that no event crosses.
NO_EVENTS_TEXT = "нет событий"

# ── «Выбор даты» window button / popover (W3b D9, renamed «Выбор даты» in 7.1)
#: Button caption while no window is applied; the caret marks it as a dropdown
#: (spec «Выбор даты»: без окна кнопка отображает «Все дни»).
WINDOW_CHIP_ALL = "Все дни ▾"
#: The button's accessible identity — the panel's one date entry point
#: (proposal: the chip-фильтр became a navigation control).
WINDOW_BUTTON_TOOLTIP = "Выбор даты"
#: Popover hint line guiding the two taps that pick the range (D9).
WINDOW_PICK_START = "Кликните дату начала"
WINDOW_PICK_END = "Кликните дату окончания"
WINDOW_RESET_TEXT = "Сбросить"
#: Caption of the header toggle that cuts the empty positions (task 7.3, spec
#: «Скрытие дат без событий»); session-only state, never persisted.
HIDE_EMPTY_TOGGLE_TEXT = "Скрыть даты без событий"
#: The popover stacks its two calendars in one column, so both fit only when
#: the room under the chip covers ``2×`` a calendar's height — below that the
#: low-screen fallback keeps a single calendar and the taps assign the dates.
WINDOW_DOUBLE_HEIGHT_FACTOR = 2

#: itemData role of the row model built from ``timeline_rows`` ladder rows.
#: The LEGACY rail label/segment roles are deleted with the rail painting
#: (task 3.1).
ROLE_ROW = Qt.ItemDataRole.UserRole + 1

#: ``set_knobs`` sentinel discriminating "keep the knob" from an explicit
#: value — a plain ``None`` default could not clear the window knob.
_KEEP = object()

#: Window knob normalized: ``None`` and ``(None, None)`` both mean «Все дни».
_NO_WINDOW: tuple[date | None, date | None] = (None, None)


# ── token palette (W3b D10: derivatives only, named globals off-skin) ───────

@dataclass(frozen=True)
class _Palette:
    """QColors for one paint pass, all derived from tokens of the live theme."""

    background: QColor     # sticky band surface (color.bg.surface)
    row_text: QColor       # row captions (color.fg.primary)
    selected_fill: QColor  # selected card fill (color.accent)
    selected_text: QColor  # text over the accent fill (color.accent.fg)
    hover_fill: QColor     # accent derivative wash under the hovered card
    ghost: QColor          # drop-ghost wash and dimmed card (accent @ GHOST_ALPHA)
    hairline: QColor       # sticky band underline (color.accent)
    muted_text: QColor             # placeholders / gaps / empty counters (fg.muted)
    type_dot_muted: QColor         # type dot of an untyped event (fg.muted)
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
    """Derive every row/sticky color from the runtime's current tokens.

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
            row_text=_global(Qt.GlobalColor.black),
            selected_fill=_global(Qt.GlobalColor.gray),
            selected_text=_global(Qt.GlobalColor.white),
            hover_fill=_global(Qt.GlobalColor.gray, ROW_HOVER_ALPHA),
            ghost=_global(Qt.GlobalColor.gray, GHOST_ALPHA),
            hairline=_global(Qt.GlobalColor.gray),
            muted_text=_global(Qt.GlobalColor.gray),
            type_dot_muted=_global(Qt.GlobalColor.gray),
            # No tokens to derive chart colors from — every dot falls back to
            # the same named Qt global as the muted text (spec «Вне скина»).
            type_dots={key: _global(Qt.GlobalColor.gray) for key in CHART_TOKEN_KEYS},
        )
    tokens, theme = runtime.tokens, runtime.theme
    accent = token_rgb(tokens, theme, "color.accent")
    muted = token_rgb(tokens, theme, "color.fg.muted")
    return _Palette(
        background=_from_rgb(token_rgb(tokens, theme, "color.bg.surface")),
        row_text=_from_rgb(token_rgb(tokens, theme, "color.fg.primary")),
        selected_fill=_from_rgb(accent),
        selected_text=_from_rgb(token_rgb(tokens, theme, "color.accent.fg")),
        hover_fill=_from_rgb(accent, ROW_HOVER_ALPHA),
        ghost=_from_rgb(accent, GHOST_ALPHA),  # spec: accent derivative, α 0.35
        hairline=_from_rgb(accent),
        muted_text=_from_rgb(muted),
        type_dot_muted=_from_rgb(muted),
        # The mandatory chart palette: dot k of a typed card is exactly
        # ``color.chart.k`` of the live theme (spec «Цвет типа равен токену»).
        type_dots={
            key: _from_rgb(token_rgb(tokens, theme, key))
            for key in CHART_TOKEN_KEYS
        },
    )


# ── caption helpers of the painted row kinds (task 3.1) ─────────────────────

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


def _card_line(row: EventRow) -> str:
    """Card text: the event name; open events carry the explicit «бессрочно»
    mark instead of any asserted end (spec «Бессрочные события»)."""
    if row.end is None:
        return f"{row.name}{OPEN_MARK_SEP}{OPEN_MARK}"
    return row.name


def _range_text(start: date, end: date | None) -> str:
    """``start — end`` in the game format; an open end stays an explicit ``—``."""
    start_s = format_game_date(start)
    if end is None:
        return f"{start_s} —"
    return f"{start_s} — {format_game_date(end)}"


def _card_tooltip(row: EventRow) -> str:
    """Tooltip body: full name plus the game-formatted date range — set on
    every card (spec: подсказка «name + start — end» на любой карточке)."""
    return f"{row.name}\n{_range_text(row.start, row.end)}"


def _gap_line(row: GapCollapsedRow) -> str:
    """Collapsed-gap caption: «нет событий» with the gap's game-formatted
    bounds — muted (spec «Лента времени»: схлопнутая позиция провала)."""
    return (
        f"{NO_EVENTS_TEXT}: {format_game_date(row.date)} — "
        f"{format_game_date(row.end)}"
    )


def _counter_line(row: PeriodCardRow) -> str:
    """Period counter text: «N событий» / the muted «нет событий» stub."""
    if row.count:
        return f"{row.count} {_events_phrase(row.count)}"
    return NO_EVENTS_TEXT


class _RowDelegate(QStyledItemDelegate):
    """Paints one ladder position (task 3.1): the selection/hover wash, then
    the row kind's own body — the event type dot + name (open card with the
    muted «бессрочно» mark), the «+  нет события» placeholder, the muted gap
    caption, a section header or the period counter. The pre-redesign side
    rail and its per-row roles are gone; scrolling / focus / click dispatch
    stay the plain ``QListWidget`` machinery.
    """

    def __init__(self, view: "TimelineListView") -> None:
        super().__init__(view)
        self._view = view

    def sizeHint(self, option, index) -> QSize:  # Qt API name
        return QSize(0, ROW_HEIGHT)

    def paint(self, painter: QPainter, option, index) -> None:  # Qt API name
        row = index.data(ROLE_ROW)
        if row is None:  # defensive: an item without ladder data stays blank
            return
        view = self._view
        palette = view.paint_palette()
        event_row = isinstance(row, EventRow)
        # The selection wash covers *every* duplicate of the selected event
        # (one record, many cards) — driven by the view's id, not the Qt
        # selection bookkeeping.
        selected = (
            event_row
            and row.event_id == view.selected_id
        )
        hovered = (
            not selected
            and event_row
            and index.row() == view.hover_index()
        )
        # Drop-gesture states (task 5.1): the pressed card keeps its place
        # dimmed, the row under the cursor wears the accent ghost (no target →
        # no ghost, the ghost simply goes out over gaps and off-tape).
        drag = view.drag_preview
        dimmed = (
            event_row
            and drag is not None
            and row.event_id == drag.event_id
            and index.row() == drag.source_index
        )
        painter.save()
        if dimmed:
            painter.setOpacity(GHOST_ALPHA)
        if selected:
            painter.fillRect(option.rect, palette.selected_fill)
        elif hovered:
            painter.fillRect(option.rect, palette.hover_fill)
        if event_row:
            self._paint_card(
                painter, option, row, palette, selected, hovered=hovered
            )
        elif isinstance(row, EmptyDayRow):
            self._draw_text(painter, option, EMPTY_DAY_TEXT, palette.muted_text)
        elif isinstance(row, GapCollapsedRow):
            self._draw_text(painter, option, _gap_line(row), palette.muted_text)
        elif isinstance(row, PeriodCardRow):
            self._draw_text(
                painter, option, _counter_line(row),
                palette.row_text if row.count else palette.muted_text,
            )
        elif isinstance(row, DayHeaderRow | PeriodHeaderRow):
            # Section heads carry the primary text weight — the sticky pair
            # shows the same caption while the section tops the viewport.
            self._draw_text(
                painter, option, header_caption(row), palette.row_text
            )
        if drag is not None and drag.target_index == index.row():
            # The target-day ghost: one accent wash over the row the cursor
            # points at (cards, day heads and placeholders all materialize a
            # day; gaps and off-tape positions do not — no wash lands there).
            painter.fillRect(option.rect, palette.ghost)
        painter.restore()

    def _paint_card(
        self, painter, option, row: EventRow, palette: _Palette, selected: bool,
        *, hovered: bool,
    ) -> None:
        """Event card: the type-dot square + the name (open events append the
        muted «бессрочно» mark). The dot is a bare fill with no pen, so it
        survives the selection wash without an outline (W4 D7); its color is
        exactly ``color.chart.k`` of the live theme (spec «Цвет типа равен
        токену»)."""
        rect = option.rect
        dot_key = row.token_key
        dot = (
            palette.type_dots.get(dot_key, palette.type_dot_muted)
            if dot_key else palette.type_dot_muted
        )
        painter.fillRect(
            QRect(
                TEXT_LEFT_PAD,
                rect.center().y() - DOT_SIZE // 2,
                DOT_SIZE, DOT_SIZE,
            ),
            dot,
        )
        text_rect = rect.adjusted(TEXT_INDENT, 0, -TEXT_LEFT_PAD, 0)
        fm = QFontMetrics(option.font)
        name_color = palette.selected_text if selected else palette.row_text
        if row.end is None:
            # Name elided to the width left of the muted mark, mark appended
            # right behind it — the pair can never overflow the row: the
            # elided name is at most (width − mark width) wide.
            mark = f"{OPEN_MARK_SEP}{OPEN_MARK}"
            mark_w = fm.horizontalAdvance(mark)
            name = fm.elidedText(
                row.name, Qt.TextElideMode.ElideRight,
                max(text_rect.width() - mark_w, 0),
            )
            painter.setPen(QPen(name_color))
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                name,
            )
            mark_x = text_rect.left() + fm.horizontalAdvance(name)
            painter.setPen(QPen(palette.muted_text))
            painter.drawText(
                QRect(mark_x, text_rect.top(),
                      text_rect.right() - mark_x + 1, text_rect.height()),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                mark,
            )
            return
        elided = fm.elidedText(
            row.name, Qt.TextElideMode.ElideRight, max(text_rect.width(), 0)
        )
        painter.setPen(QPen(name_color))
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            elided,
        )

    def _draw_text(self, painter, option, text: str, color) -> None:
        """One elided text run at the shared ladder indent (tooltip holds all)."""
        rect = option.rect.adjusted(TEXT_INDENT, 0, -TEXT_LEFT_PAD, 0)
        fm = QFontMetrics(option.font)
        elided = fm.elidedText(text, Qt.TextElideMode.ElideRight, max(rect.width(), 0))
        painter.setPen(QPen(color))
        painter.drawText(
            rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            elided,
        )


@dataclass
class _DragGesture:
    """Widget-side state of one in-flight date-drop gesture (task 5.1).

    Recorded on a left press over an :class:`EventRow` at the DAY rung; below
    :data:`DRAG_START_THRESHOLD_PX` of vertical travel it is still a plain
    click. ``active`` means the delegate paints the dimmed source card and,
    while the cursor sits on a materialized day, the accent ghost on
    ``target_index`` (``target_day`` — the sticky caption rides it). A
    collapsed gap or an off-tape point clears both target fields (no
    extrapolation past the edges — design D5), which turns the release into a
    cancel.
    """

    event_id: int
    source_index: int
    source_day: date
    start_pos: QPoint
    active: bool = False
    target_day: date | None = None
    target_index: int | None = None


class TimelineListView(QListWidget):
    """The vertical day-ladder tape: the Qt shell of the ``timeline_rows`` row
    model (design D1/D2).

    Signals carry **event ids** (the W3 id-contract): a click on an
    :class:`EventRow` card emits ``event_selected(id)`` (the whole record, no
    matter which duplicate was clicked), a double-click emits
    ``event_double_clicked``. A :class:`PeriodCardRow` click is a *drill*, never
    a selection (task 4.2, design D6): the tape re-models one rung down with
    ``window`` = the card's period and the id-protocol stays silent — the
    previous selection, if still pictured, survives. A collapsed-gap click
    emits ``gap_window_requested`` with the gap's bounds (task 7.1) — a
    pre-fill request, never a selection. Every other non-event position (day
    header, empty day, period header) answers no event selection
    (spec «Пустая позиция не выбирается»). The panel drives selection and
    scrolling through
    the public API below; the sticky pair and the empty hint paint themselves.

    The W5 rail gesture machinery (rail jump, range drag, end-stretch handle)
    is deleted together with the rail (tasks 3.1/3.2, design D9). The body
    gesture is the new date drop (tasks 5.1/5.2, design D5): press on an
    :class:`EventRow` past a :data:`DRAG_START_THRESHOLD_PX` vertical
    threshold dims that card, the row under the cursor materializes the drop
    target (day header / card / empty day; a collapsed gap or off-tape point
    invalidates it), the sticky band reads the target date, and releasing on
    another day opens the ``drop_actions`` menu at the cursor — a chosen item
    commits through ``event_dates_moved``, everything else cancels without a
    write. The gesture never arms on the period rungs (task 5.4).
    """

    event_selected = Signal(object)  # event_id
    event_double_clicked = Signal(object)  # event_id
    event_dates_moved = Signal(object, object, object)  # (id, start, end|None)
    # Emitted by the drop gesture exactly once per chosen release-menu action
    # (task 5.2); a cancelled gesture (Esc, gap, off-tape, closed menu,
    # same-day release, external rebuild) never reaches it.
    scale_changed = Signal(object)  # ScaleUnit after Alt/Opt + wheel stepped
                                    # the ladder (the panel mirrors it into the
                                    # VM — the single mutation point)
    period_drilled = Signal(object, object)  # (ScaleUnit, window pair) after a
                                             # PeriodCardRow drill click (4.2)
    # Emitted when a collapsed-gap row is clicked (task 7.1, spec «Схлопнутый
    # провал кликабелен для окна»): the gap's bounds pre-fill the «Выбор даты»
    # popover the panel owns — the row itself never selects or applies.
    gap_window_requested = Signal(object, object)  # (gap start, gap end)
    # Emitted once when the inline empty-day editor commits a name on Enter
    # (task 6.1, design D4): ``(day, name)`` for the panel to write through
    # ``vm.create_event_at``. An empty field never reaches it (the editor hides
    # silently), and Esc / blur without a committed Enter never emits either.
    event_create_requested = Signal(object, str)  # (day, name)

    def __init__(self, theme=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._events: tuple[Any, ...] = ()
        self._rows: tuple[Any, ...] = ()
        self._version: tuple | None = None
        self._selected_id: int | None = None
        # event id → (first duplicate row, ...) — the scroll anchor is the
        # first card, the wash paints them all.
        self._indexes_by_event: dict[int, tuple[int, ...]] = {}
        self._hover_row = -1
        self._palette = rows_palette(None)
        # In-flight date-drop gesture (task 5.1), ``None`` while idle.
        self._drag: _DragGesture | None = None
        # Day-ladder view knobs (mirror of the ViewModel's — the VM setter
        # stays the single mutation point; these drive build_rows):
        self._level: ScaleUnit = ScaleUnit.DAY
        self._window: tuple[date | None, date | None] = _NO_WINDOW
        self._hide_empty: bool = False

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
        self.setMouseTracking(True)  # hover wash under the cursor
        self.setItemDelegate(_RowDelegate(self))

        # D7: the sticky pair are scroll-area children pinned above the
        # viewport; the viewport gets a top margin of exactly their height, so
        # nothing is ever hidden behind them.
        self.setViewportMargins(0, STICKY_HEIGHT, 0, 0)
        self._sticky_current = title("")
        self._sticky_current.setParent(self)
        self._sticky_current.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        self._sticky_next = title("")
        self._sticky_next.setParent(self)
        self._sticky_next.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        self._sticky_next.hide()
        self._sticky_text: str = ""
        self._sticky_target: str = ""
        self._push_anims: tuple[QPropertyAnimation, ...] = ()
        self._hint = hint(EMPTY_HINT_TEXT)
        self._hint.setParent(self)
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        # Inline create-from-empty-day editor (task 6.1, design D4): ONE reused
        # QLineEdit parked over the viewport at the clicked empty-day row's
        # coordinates (a delegate editor is rejected — the rows are no Qt
        # model). It stays hidden until an EmptyDayRow is clicked; Enter
        # commits, Esc / blur-without-a-committed-Enter hides it.
        self._editor = QLineEdit(self.viewport())
        self._editor.setObjectName("timelineInlineEditor")  # identifier, not style
        self._editor.setPlaceholderText(EMPTY_DAY_TEXT)
        self._editor.setClearButtonEnabled(False)
        self._editor.hide()
        self._editor.returnPressed.connect(self._on_editor_enter)
        self._editor.installEventFilter(self)  # Esc + focus-out dismissal
        # Day the editor currently stands on (``None`` while hidden).
        self._editor_day: date | None = None

        self.verticalScrollBar().valueChanged.connect(self._on_scroll_value)
        self.clicked.connect(self._on_clicked)
        self.doubleClicked.connect(self._on_double_clicked)
        self._rebuild_palette()
        self._sync_overlays()
        if theme is not None:
            # Live re-theme (D10): rebuild the paint palette and repaint the
            # rows — selection and scroll position are deliberately untouched.
            theme.add_listener(self._retheme)

    # ── public API ───────────────────────────────────────────────────────────

    @property
    def events(self) -> tuple[Any, ...]:
        """The events currently rendered (test/E2E introspection)."""
        return self._events

    @property
    def rows(self) -> tuple[Any, ...]:
        """The current ladder position model (pure ``timeline_rows`` data)."""
        return self._rows

    @property
    def level(self) -> ScaleUnit:
        """The ladder rung the tape currently renders."""
        return self._level

    @property
    def window(self) -> tuple[date | None, date | None]:
        """The «Выбор даты» window knob ((``None``, ``None``) = «Все дни»)."""
        return self._window

    @property
    def hide_empty(self) -> bool:
        """The «Скрыть даты без событий» knob."""
        return self._hide_empty

    @property
    def selected_id(self) -> int | None:
        """The id whose cards paint the selection wash (``None`` = none)."""
        return self._selected_id

    @property
    def sticky_label(self) -> QLabel:
        """The current sticky caption (test/E2E introspection)."""
        return self._sticky_current

    @property
    def sticky_next(self) -> QLabel:
        """The chasing sticky caption mid-push (``hidden`` while at rest)."""
        return self._sticky_next

    @property
    def hint_label(self) -> QLabel:
        """The empty-state hint overlay (test/E2E introspection)."""
        return self._hint

    def index_for_event(self, event_id: int) -> int | None:
        """Row index of the event's first card (``None`` → not pictured)."""
        indexes = self._indexes_by_event.get(event_id)
        return indexes[0] if indexes else None

    def indexes_for_event(self, event_id: int) -> tuple[int, ...]:
        """All duplicate card rows of one event — in ``start_date``-ordered
        day sequence (the wash and the jump anchor read this)."""
        return self._indexes_by_event.get(event_id, ())

    def set_selected(self, event_id: int | None) -> None:
        """Highlight every duplicate card of ``event_id`` (idempotent).

        A non-``None`` id also scrolls its first card into view; an id the
        model does not picture keeps the highlight pending invisible (the ladder
        may be on a period rung) without moving anything.
        """
        if event_id == self._selected_id:
            return
        self._selected_id = event_id
        self._apply_selection(scroll=True)

    def scroll_to_event(self, event_id: int) -> None:
        """Scroll just enough to reveal the event's first card (search jump)."""
        idx = self.index_for_event(event_id)
        if idx is None:
            return
        self.scrollToItem(
            self.item(idx), QAbstractItemView.ScrollHint.PositionAtCenter
        )

    def jump_prev_event(self) -> bool:
        """Scroll to the nearest EventRow card before the reading position.

        Headers, placeholders and gaps are skipped (only cards hold events);
        at the head of the tape the command is inert (``False`` — the panel
        then descends the ladder, spec «Прыжок с месяцной ступени»).
        """
        idx = self._scan_event_index(back=True)
        if idx is not None:
            self._reveal_row(idx)
            return True
        return False

    def jump_next_event(self) -> bool:
        """Mirror of :meth:`jump_prev_event` towards the tail of the tape."""
        idx = self._scan_event_index(back=False)
        if idx is not None:
            self._reveal_row(idx)
            return True
        return False

    def top_visible_index(self) -> int:
        """Index of the row under the viewport's top edge (``-1`` when empty).

        The equal-height contract makes this the index the core's
        :func:`timeline_rows.sticky_state` takes as the tape's top edge.
        """
        item = self.itemAt(self.viewport().rect().topLeft())
        return self.row(item) if item is not None else -1

    def paint_palette(self) -> _Palette:
        """The palette the delegate paints with (rebuilt on every re-theme)."""
        return self._palette

    def hover_index(self) -> int:
        return self._hover_row

    @property
    def drag_preview(self) -> "_DragGesture | None":
        """The armed date-drop gesture mid-flight (test/E2E introspection).

        ``None`` while idle or still below :data:`DRAG_START_THRESHOLD_PX` —
        below the threshold the press is a plain click, not a gesture. While
        active, the record carries the dimmed source card (``source_index``),
        the ghost row and its day (``target_index``/``target_day``, both
        ``None`` while the cursor points at a gap or off the tape)."""
        drag = self._drag
        return drag if drag is not None and drag.active else None

    def update_events(self, events: Sequence[Any]) -> None:
        """Reload the tape — but only when the sample or the knobs moved.

        The "version" is the ``(id, start, end, name, color)`` set plus the
        ``(window, level, hide_empty, bottom)`` knobs: an identical sample at
        identical knobs must not rebuild (and thus must not touch focus or the
        scroll position). After a real rebuild the reading position is restored
        from the selected id when that event is still pictured, and the tape
        rewinds to the top otherwise (a selection the ViewModel pruned never
        keeps a stale offset).
        """
        events = tuple(events)
        version = self._version_of(
            events, self._window, self._level, self._hide_empty
        )
        if version == self._version:
            # Same set — but game month names can move while no event does
            # (month settings reload identical events): repaint the captions
            # and the sticky date; rows/selection/scroll stay as they are.
            self._sync_overlays()
            self.viewport().update()
            return
        self._rebuild(events)
        visible_ids = {e.id for e in events}
        if self._selected_id is not None and self._selected_id not in visible_ids:
            self._selected_id = None  # excluded from the visible sample (spec)
        if self._selected_id is not None:
            self._apply_selection(scroll=True)
        else:
            with QSignalBlocker(self.verticalScrollBar()):
                self.verticalScrollBar().setValue(0)
            self._sync_overlays()

    def set_knobs(
        self,
        window=_KEEP,
        level=_KEEP,
        hide_empty=_KEEP,
    ) -> None:
        """Mirror the ViewModel's ladder knobs without touching selection.

        A changed knob re-models the tape keeping the reading position: the
        position that owned the pre-switch top date lands back under the
        sticky band, and a still-pictured selection keeps its card washed.
        """
        window = self._window if window is _KEEP else _normalized_window(window)
        level = self._level if level is _KEEP else level
        hide_empty = self._hide_empty if hide_empty is _KEEP else bool(hide_empty)
        if (
            level is self._level
            and window == self._window
            and hide_empty is self._hide_empty
        ):
            return
        anchor = self._top_date()
        self._level = level
        self._window = window
        self._hide_empty = hide_empty
        self._rebuild(self._events)
        if anchor is not None:
            idx = self._index_at_date(anchor)
            if idx is not None:
                self._scroll_row_to_top(idx)
        self._reassert_selection()

    # ── row model construction ──────────────────────────────────────────────

    @staticmethod
    def _version_of(
        events: Sequence[Any],
        window: tuple[date | None, date | None],
        level: ScaleUnit,
        hide_empty: bool,
    ) -> tuple:
        """The rebuild key: the ``(id, start, end, name, color)`` set plus the
        ``(window, level, hide_empty, bottom)`` knobs.

        The knobs join the key so a window/ladder/toggle change is never
        swallowed by the identical-sample fast path — and so does the type's
        palette index (assigning a type recolors the dots without any name or
        date moving) and the content bottom (extending an event grows more days
        under the same days-only sample).
        """
        return (
            tuple(
                (
                    e.id, e.start_date, e.end_date, e.name,
                    getattr(getattr(e, "event_type", None), "color_index", None),
                )
                for e in events
            ),
            window,
            level,
            hide_empty,
            content_bottom(events),
        )

    def _rebuild(self, events: tuple[Any, ...]) -> None:
        """Repopulate the Qt list from ``build_rows`` at the current knobs.

        The day-ladder positions are never selectable: the rows carry the
        ladder's own row objects, so ``NoItemFlags`` is what stops Qt's selection
        machinery from driving an id that does not exist (the list paints its
        own selection wash from ``_selected_id``). ``ItemIsEnabled`` stays on
        for the clickable kinds — only Qt's *user interaction* gate needs it,
        which is how :meth:`_on_clicked` reaches a collapsed gap while
        :meth:`_on_double_clicked` still yields no id for it (task 7.1).
        """
        self._events = events
        self._version = self._version_of(
            events, self._window, self._level, self._hide_empty
        )
        self._rows = tuple(
            build_rows(
                events,
                window=self._window,
                level=self._level,
                hide_empty=self._hide_empty,
            )
        )
        self._indexes_by_event = {}
        for idx, row in enumerate(self._rows):
            if isinstance(row, EventRow):
                self._indexes_by_event.setdefault(row.event_id, []).append(idx)
        self._indexes_by_event = {
            event_id: tuple(indexes)
            for event_id, indexes in self._indexes_by_event.items()
        }
        self._hover_row = -1
        # An external re-model cancels any press-drag in flight (task 5.1):
        # the source index and the ghost row it painted do not survive the
        # rebuild, and a cancelled gesture never reaches the release menu.
        self._drag = None
        # …and the inline editor too (task 6.1): the empty day it stood on may
        # no longer exist after the reload (a created event replaces it), so
        # the transient field goes back to the placeholder before repainting.
        self._hide_editor()

        with QSignalBlocker(self):
            self.clear()
            for row in self._rows:
                item = QListWidgetItem()
                item.setSizeHint(QSize(0, ROW_HEIGHT))
                if isinstance(row, EventRow):
                    item.setToolTip(_card_tooltip(row))
                elif isinstance(row, PeriodCardRow):
                    # The one non-card position with a gesture: enabled so Qt
                    # delivers the click, but NOT selectable — the drill writes
                    # knobs, never a selection (spec «Клик по месяцу
                    # приближает»; task 4.2).
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                elif isinstance(row, EmptyDayRow):
                    # The empty day is a create entry point: enabled so Qt
                    # delivers the click that opens the inline editor, but NOT
                    # selectable — clicking it never selects (spec «Пустая
                    # позиция не выбирается», task 6.1).
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                elif isinstance(row, GapCollapsedRow):
                    # The collapsed gap is the window entry point (task 7.1):
                    # enabled so Qt delivers the click that drops the
                    # pre-filled «Выбор даты» popover, but NOT selectable —
                    # a gap answers no event selection (spec «Пустая позиция
                    # не выбирается»).
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                else:
                    # Headers stay inert: not selectable, not clickable, not
                    # even keyboard-reachable (spec).
                    item.setFlags(Qt.ItemFlag.NoItemFlags)
                item.setData(ROLE_ROW, row)
                self.addItem(item)
        # A re-modeled tape re-reads its sticky section from the top edge —
        # without an animated push (animation belongs to scrolls, task 3.2).
        self._cancel_sticky_push()
        self._sticky_text = ""
        self._sync_overlays()
        self.viewport().update()

    # ── selection / navigation internals ────────────────────────────────────

    def _apply_selection(self, scroll: bool) -> None:
        """Repaint the duplicate wash and anchor the jump base (no signals)."""
        idx = self.index_for_event(self._selected_id) \
            if self._selected_id is not None else None
        with QSignalBlocker(self):
            if idx is not None:
                # The current row follows the selection — it is the anchor the
                # jump commands start from (D8).
                self.setCurrentIndex(self.model().index(idx, 0))
            else:
                self.setCurrentIndex(QModelIndex())
        if idx is not None and scroll:
            # Selection from outside also reveals the card (spec «Выбор из
            # поиска»).
            self.scrollToItem(
                self.item(idx), QAbstractItemView.ScrollHint.PositionAtCenter
            )
        self.viewport().update()

    def _reassert_selection(self) -> None:
        """Re-highlight the pending selection after a ladder re-model."""
        if self._selected_id is None:
            return
        self._apply_selection(scroll=False)
        idx = self.index_for_event(self._selected_id)
        if idx is not None:
            self.scrollToItem(
                self.item(idx), QAbstractItemView.ScrollHint.EnsureVisible
            )

    def _reveal_row(self, idx: int) -> None:
        """Move the reading position to ``idx``: scroll + jump anchor.

        The id-contract stays untouched — ``_selected_id`` is not moved and no
        id-signal fires, so the detail panel keeps its event: the jump commands
        navigate, they do not select.
        """
        with QSignalBlocker(self):
            self.setCurrentIndex(self.model().index(idx, 0))
        self.scrollToItem(
            self.item(idx), QAbstractItemView.ScrollHint.PositionAtCenter
        )

    def _scan_event_index(self, *, back: bool) -> int | None:
        """Nearest *other* event's card before/after the reading position.

        The base is the selected card when the selection is pictured, else the
        top visible row (the D8 reading anchor). A multi-day event duplicates
        into one card per day, so cards of the anchor event itself are skipped
        — the jumps walk between events (W3b corridor semantics), not between a
        single event's day cards.
        """
        if not self._rows:
            return None
        own = (
            self.index_for_event(self._selected_id)
            if self._selected_id is not None else None
        )
        if own is not None:
            base = own
        else:
            current = self.currentRow()
            base = current if current >= 0 else max(self.top_visible_index(), 0)
        base_row = self._rows[base] if 0 <= base < len(self._rows) else None
        anchor_event = (
            self._selected_id
            if self._selected_id is not None
            else base_row.event_id
            if isinstance(base_row, EventRow) else None
        )
        rng = range(min(base, len(self._rows)) - 1, -1, -1) if back \
            else range(max(base, -1) + 1, len(self._rows))
        for idx in rng:
            row = self._rows[idx]
            if isinstance(row, EventRow) and row.event_id != anchor_event:
                return idx
        return None

    def _top_date(self) -> date | None:
        """Date of the position under the sticky band (re-entry anchor)."""
        if not self._rows:
            return None
        return self._rows[max(self.top_visible_index(), 0)].date

    def _index_at_date(self, day: date) -> int | None:
        """Index of the first position at/after ``day`` (nearest re-entry).

        Row dates are chronologically ordered (day ladder and period rungs
        alike), so this maps any pre-switch top date back onto the re-modeled
        tape: its own day/section, else the first section that starts behind
        it; a date past the tail lands on the last position.
        """
        if not self._rows:
            return None
        for idx, row in enumerate(self._rows):
            if row.date >= day:
                return idx
        return len(self._rows) - 1

    def _scroll_row_to_top(self, idx: int) -> None:
        """Pin ``idx`` to the viewport's top edge (the sticky-band anchor)."""
        item = self.item(idx)
        if item is None:
            return
        self.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtTop)

    def _on_clicked(self, index: QModelIndex) -> None:
        if not index.isValid():
            return
        row = index.data(ROLE_ROW)
        if isinstance(row, PeriodCardRow):
            self._drill_into(row)
            return  # a drill is never a selection — no id, no wash change
        if isinstance(row, EmptyDayRow):
            # Task 6.1: the empty day is a create entry point, never a
            # selection — the inline editor takes the row's coordinates.
            self._show_editor(row.date, index.row())
            return
        if isinstance(row, GapCollapsedRow):
            # Task 7.1, spec «Схлопнутый провал кликабелен для окна»: the
            # collapsed gap opens «Выбор даты» pre-filled with its bounds —
            # it answers no selection, so the panel owns the popover.
            self.gap_window_requested.emit(row.date, row.end)
            return
        if not isinstance(row, EventRow):
            return  # headers stay inert (spec)
        self._selected_id = row.event_id  # the click already landed in the model
        self._apply_selection(scroll=False)
        self.event_selected.emit(row.event_id)

    def _drill_into(self, row: PeriodCardRow) -> None:
        """Period-card click (task 4.2, design D6): one rung down with the
        card's whole period as the window — year → months, month → days
        (spec «Проваливание выставляет окно»). The tape re-models locally with
        the reading position kept; the pair is *emitted* for the panel to
        write through the ViewModel (the single mutation point). Selection is
        deliberately untouched — any still-pictured card keeps its wash."""
        level, window = drill_target(row)
        self.set_knobs(level=level, window=window)
        self.period_drilled.emit(level, window)

    def _on_double_clicked(self, index: QModelIndex) -> None:
        event_id = self._event_id_at(index)
        if event_id is not None:
            self.event_double_clicked.emit(event_id)

    @staticmethod
    def _event_id_at(index: QModelIndex) -> int | None:
        if not index.isValid():
            return None
        row = index.data(ROLE_ROW)
        return row.event_id if isinstance(row, EventRow) else None

    # ── inline creation from an empty day (task 6.1, design D4) ──────────────

    @property
    def inline_editor(self) -> QLineEdit:
        """The reusable inline create field (test/E2E introspection)."""
        return self._editor

    @property
    def editing_day(self) -> date | None:
        """The day the inline editor stands on (``None`` while hidden)."""
        return self._editor_day

    def _show_editor(self, day: date, index_row: int) -> None:
        """Park the one editor over the clicked empty-day row (design D4).

        The field is a ``viewport()`` child, so the row's ``visualItemRect`` —
        already in viewport coordinates — maps onto it directly; it spans the
        row's full width and height. Re-clicking another empty day just moves
        the same widget (there is never a second one)."""
        item = self.item(index_row)
        if item is None:
            return
        rect = self.visualItemRect(item)
        if not rect.isValid():
            return
        self._editor_day = day
        self._editor.setText("")
        self._editor.setGeometry(
            0, rect.top(), self.viewport().width(), rect.height()
        )
        self._editor.show()
        self._editor.raise_()
        self._editor.setFocus()

    def _hide_editor(self) -> None:
        """Return the row to its «нет события» placeholder: no text committed,
        no signal — idempotent (safe to call from a rebuild where it was never
        shown)."""
        if self._editor_day is None and not self._editor.isVisible():
            return
        self._editor.setText("")
        self._editor_day = None
        self._editor.clearFocus()
        self._editor.hide()

    def _on_editor_enter(self) -> None:
        """Enter commits the name (spec «Enter SHALL создавать»); an empty (or
        whitespace-only) field creates nothing (spec «Пустое поле не создаёт»)
        — the row simply falls back to its placeholder."""
        day = self._editor_day
        name = self._editor.text().strip()
        if day is not None and name:
            self.event_create_requested.emit(day, name)
        self._hide_editor()

    def eventFilter(self, obj, event) -> bool:  # Qt API name
        if obj is self._editor:
            if (
                event.type() == QEvent.Type.KeyPress
                and event.key() == Qt.Key.Key_Escape
            ):
                # Esc discards the draft regardless of text (spec «Escape …
                # SHALL возвращать строку в состояние плейсхолдера»).
                self._hide_editor()
                return True
            if event.type() == QEvent.Type.FocusOut and not self._editor.text():
                # Losing focus WITHOUT text returns the placeholder; a draft
                # is kept on screen and only Enter or Esc resolves it (spec
                # «потеря фокуса без текста»).
                self._hide_editor()
        return super().eventFilter(obj, event)

    def _on_scroll_value(self, _value: int) -> None:
        """Scrolling dismisses the editor (its row slides out from under the
        one absolute-positioned overlay) and refreshes the sticky pair. A
        reload-driven hide is independent of this."""
        self._hide_editor()
        self._sync_overlays()

    # ── themes / overlays / sticky push-out (tasks 3.1/3.2, design D3) ──────

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
        sheet = (
            "QLabel { background-color: " + bg + ";"
            " border-bottom: 1px solid " + hairline + ";"
            " padding-left: 8px; }"
        )
        self._sticky_current.setStyleSheet(sheet)
        self._sticky_next.setStyleSheet(sheet)

    def _sync_overlays(self) -> None:
        """Reposition the overlays and refresh the sticky pair (D7)."""
        width = self.width()
        anim_running = any(
            anim.state() == QPropertyAnimation.State.Running
            for anim in self._push_anims
        )
        for label in (self._sticky_current, self._sticky_next):
            # Mid-push the ``pos`` animations own both y coordinates — a
            # resize may only follow them with the width, never fight them.
            y = label.y() if anim_running else (
                0 if label is self._sticky_current else STICKY_HEIGHT
            )
            label.setGeometry(0, y, width, STICKY_HEIGHT)
        viewport = self.viewport()
        self._hint.setGeometry(
            viewport.x(), viewport.y(), viewport.width(), viewport.height()
        )
        self._hint.setVisible(self.count() == 0)
        if self.count() == 0:
            # Hidden while empty, the hint stays (spec «Липкий заголовок»).
            self._cancel_sticky_push()
            self._sticky_text = ""
            self._sticky_current.hide()
            self._sticky_next.hide()
            return
        self._sync_sticky()

    def _sync_sticky(self) -> None:
        """Drive the two sticky labels from the core's sticky truth (D3).

        ``sticky_state`` names the section the tape's top edge sits under; when
        that caption changes while the band was already showing one, the change
        plays as a push-out — never an instant text swap. Scrolling inside a
        section, or a section-less head of the tape, is a no-op; a section
        change that overtakes an unfinished push rewinds the pair first (the
        position always follows the model; the animation is cosmetic).
        """
        drag = self.drag_preview
        if drag is not None and drag.target_day is not None:
            # While the ghost is lit the band follows the GESTURE, not the
            # scroll edge (spec «Перетаскивание события с выбором действия»:
            # sticky-заголовок SHALL показывать целевую дату).
            text = header_caption(DayHeaderRow(date=drag.target_day))
        else:
            state = sticky_state(self._rows, self.top_visible_index())
            text = state.current_text if state.current_index is not None else ""
        if self._push_anims:
            if text == self._sticky_target:
                return  # the running push already heads for this caption
            self._cancel_sticky_push()  # scroll moved on: snap back, re-drive
        if text == self._sticky_text:
            if text and not self._sticky_current.isVisible():
                self._commit_sticky(text)
            return
        was_showing = bool(self._sticky_text) and self._sticky_current.isVisible()
        self._sticky_text = text
        if was_showing and text:
            self._push_out_sticky(text)
        elif text:
            self._commit_sticky(text)
        else:
            self._sticky_current.hide()
            self._sticky_next.hide()

    def _push_out_sticky(self, text: str) -> None:
        """Animate the pair: current slides out up, next slides in from below.

        Both moves are ``pos`` property animations of :data:`STICKY_PUSH_MS`
        with an ease-out curve (design D3); the next label rides *above* the
        current one so the band reads as one caption being pushed out.
        """
        cur, nxt = self._sticky_current, self._sticky_next
        self._sticky_target = text
        nxt.setText(text)
        nxt.setGeometry(0, STICKY_HEIGHT, self.width(), STICKY_HEIGHT)
        nxt.show()
        nxt.raise_()
        out = QPropertyAnimation(cur, b"pos", self)
        out.setDuration(STICKY_PUSH_MS)
        out.setStartValue(cur.pos())
        out.setEndValue(QPoint(0, -STICKY_HEIGHT))
        out.setEasingCurve(QEasingCurve.Type.OutQuad)
        move_in = QPropertyAnimation(nxt, b"pos", self)
        move_in.setDuration(STICKY_PUSH_MS)
        move_in.setStartValue(QPoint(0, STICKY_HEIGHT))
        move_in.setEndValue(QPoint(0, 0))
        move_in.setEasingCurve(QEasingCurve.Type.OutQuad)
        move_in.finished.connect(self._finish_sticky_push)
        self._push_anims = (out, move_in)
        out.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
        move_in.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def _finish_sticky_push(self) -> None:
        """Commit a finished (natural or interrupted) push: next becomes
        current. Re-entrant ``finished`` deliveries — ``stop()`` emits it too —
        find ``_push_anims`` already cleared and return quietly."""
        anims, self._push_anims = self._push_anims, ()
        if not anims:
            return
        for anim in anims:
            anim.stop()
        self._sticky_text = self._sticky_target
        self._commit_sticky(self._sticky_target)

    def _cancel_sticky_push(self) -> None:
        """Abandon an unfinished push: rewind the pair to its resting state.

        The animation is cosmetic (design D3) — the caller re-drives the pair
        from the core's truth immediately after, so no text is committed here.
        """
        anims, self._push_anims = self._push_anims, ()
        for anim in anims:  # finished() re-entry sees the cleared tuple
            anim.stop()
        if anims:
            self._commit_sticky(self._sticky_text)

    def _commit_sticky(self, text: str) -> None:
        """Park the pair at rest: current shows ``text`` in the band."""
        self._sticky_current.setText(text)
        self._sticky_current.setGeometry(0, 0, self.width(), STICKY_HEIGHT)
        self._sticky_current.show()
        self._sticky_current.raise_()
        self._sticky_next.hide()
        self._sticky_next.setGeometry(
            0, STICKY_HEIGHT, self.width(), STICKY_HEIGHT
        )

    # ── Qt plumbing ─────────────────────────────────────────────────────────

    def leaveEvent(self, event) -> None:  # Qt API name
        if self._hover_row != -1:
            self._hover_row = -1
            self.viewport().update()
        super().leaveEvent(event)

    # ── date-drop gesture (tasks 5.1/5.2/5.4, design D5) ────────────────────

    def mousePressEvent(self, event) -> None:  # Qt API name
        """Arms the gesture on a left press over a DAY-rung event card.

        A card press on the period rungs is never a gesture start — a
        press-drag on «месяц»/«год» stays a no-op (spec «Жестов нет на
        крупных уровнях», task 5.4), and non-card positions keep their own
        click roles. While the cursor stays under :data:`DRAG_START_THRESHOLD_PX`
        the base machinery still turns press+release into the ordinary
        selection click, so arming early is harmless."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = self._arm_gesture(event.position().toPoint())
        super().mousePressEvent(event)

    def _arm_gesture(self, pos: QPoint) -> "_DragGesture | None":
        """The gesture record for a press at ``pos``, ``None`` when it arms
        nothing (period rung, header/placeholder/gap row, off-tape point)."""
        if self._level is not ScaleUnit.DAY:
            return None
        item = self.itemAt(pos)
        if item is None:
            return None
        idx = self.row(item)
        if not 0 <= idx < len(self._rows):
            return None
        row = self._rows[idx]
        if not isinstance(row, EventRow):
            return None
        return _DragGesture(
            event_id=row.event_id,
            source_index=idx,
            source_day=row.date,
            start_pos=pos,
        )

    def mouseMoveEvent(self, event) -> None:  # Qt API name
        pos = event.position().toPoint()
        row = self.indexAt(pos).row()
        if row != self._hover_row:
            self._hover_row = row
            self.viewport().update()
        drag = self._drag
        if (
            drag is not None
            and drag.active
            or drag is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and abs(pos.y() - drag.start_pos.y()) >= DRAG_START_THRESHOLD_PX
        ):
            if not drag.active:  # vertical threshold crossed: the drop lives
                drag.active = True
            self._update_drag_target(drag, pos)
            self.viewport().update()
            self._sync_sticky()  # the band rides the target date (spec 5.1)
            event.accept()
            return  # the base drag bookkeeping must never see the gesture
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # Qt API name
        drag = self._drag
        if drag is None:
            super().mouseReleaseEvent(event)
            return
        self._drag = None
        if drag.active:
            # The gesture consumed this press: the base release runs only to
            # clear the internal press state, its click signals must not leak
            # (a drag is never a selection — spec «Drag строки не есть выбор»).
            with QSignalBlocker(self):
                super().mouseReleaseEvent(event)
            if event.button() == Qt.MouseButton.LeftButton:
                self._finish_drag(drag, event)
            else:  # released a different button mid-gesture — inert cancel
                self.viewport().update()
                self._sync_sticky()
            event.accept()
            return
        super().mouseReleaseEvent(event)  # below threshold: the plain click

    def keyPressEvent(self, event) -> None:  # Qt API name
        if self._drag is not None and event.key() == Qt.Key.Key_Escape:
            # Esc cancels the pre-release gesture (spec «Отмена по Esc»):
            # no menu, no signal, no write — the ghost and dim wash out and
            # the band falls back to the scroll position's caption.
            self._drag = None
            self.viewport().update()
            self._sync_sticky()
            event.accept()
            return
        super().keyPressEvent(event)

    def _update_drag_target(self, drag: "_DragGesture", pos: QPoint) -> None:
        """Re-points the gesture at the row under the cursor (design D5).

        A materialized day — day header, event card or empty-day placeholder
        — owns the target: the ghost lights that row and the sticky caption
        shows its date. Past the row block there is NO extrapolation (the
        deleted rail gesture's trick): off-tape points and collapsed gaps
        clear the target pair, the ghost goes out and a release there lands
        on the cancel branch."""
        target = self._row_at(pos)
        if isinstance(target, DayHeaderRow | EventRow | EmptyDayRow):
            drag.target_day = target.date
            item = self.itemAt(pos)
            drag.target_index = self.row(item) if item is not None else None
        else:  # collapsed gap, period rung or no row at all — invalid drop
            drag.target_day = None
            drag.target_index = None

    def _finish_drag(self, drag: "_DragGesture", event) -> None:
        """Release branch of an active gesture (task 5.1).

        The target under the cursor decides: gap / off-tape / the event's own
        day → silent cancel (no menu, no write; specs «Промах на схлопнутый
        провал отменяет», «Дроп на свой день без меню», «Цель ограничена
        календарём» by construction); another materialized day → the release
        menu at the cursor (task 5.2)."""
        self._update_drag_target(drag, event.position().toPoint())
        target_day = drag.target_day
        self.viewport().update()  # ghost and dim wash out on any release
        self._sync_sticky()
        if target_day is None or target_day == drag.source_day:
            return
        source = next(
            (record for record in self._events if record.id == drag.event_id),
            None,
        )
        if source is None:
            return  # the sample no longer holds the record — nothing to write
        self._open_drop_menu(source, target_day, event.globalPosition().toPoint())

    def _open_drop_menu(self, source, target_day: date, global_pos: QPoint) -> None:
        """The release menu at the cursor (task 5.2, design D5).

        The items are exactly the core's ``drop_actions`` verdict for this
        event and day (same-day drops never reach here — the view skips the
        menu against the source day). Choosing an item applies
        :func:`apply_drop_action` and commits through the single
        ``event_dates_moved`` channel — one write, one rebuild downstream;
        closing the menu without a choice (Esc, a click past the items) is a
        cancel: no signal, nothing touched."""
        actions = drop_actions(source, target_day)
        menu = QMenu(self)
        item_actions: dict = {}
        for action in DROP_ACTION_ORDER:
            if actions.get(action):
                item_actions[menu.addAction(DROP_CAPTIONS[action])] = action
        picked = menu.exec(global_pos)
        if picked is None or picked not in item_actions:
            return  # «Закрытие меню без действия … не SHALL менять ничего»
        start, end = apply_drop_action(source, item_actions[picked], target_day)
        self.event_dates_moved.emit(source.id, start, end)

    def wheelEvent(self, event) -> None:  # Qt API name
        """One notch == exactly one row (spec «Шаг прокрутки колеса»).

        ``ScrollPerItem`` alone is not enough: Qt multiplies a notch by the
        platform's wheel-scroll-lines setting (3 lines/notch on macOS), so the
        step is pinned here to a single row in either direction. Alt/Opt
        (macOS Option) + wheel steps the ladder instead — anchored at the row
        under the cursor (design D6, task 4.1); Ctrl/Cmd + wheel is the dead
        legacy gesture: the event is eaten, nothing happens (spec «Alt-колесо
        вместо Ctrl»); the other modifiers keep the plain one-row step
        (spec «иные модификаторы шаг прокрутки менять НЕ SHALL»).
        """
        angle = event.angleDelta().y()
        if event.modifiers() & Qt.KeyboardModifier.AltModifier:
            if angle != 0:
                self._zoom(finer=angle > 0, cursor=event.position().toPoint())
            event.accept()  # the wheel belongs to the ladder while Alt rides
            return
        if event.modifiers() & (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier
        ):
            event.accept()  # deleted interaction — no reaction on any layer
            return
        if angle == 0:  # e.g. a horizontal trackpad glide — leave it to Qt
            super().wheelEvent(event)
            return
        bar = self.verticalScrollBar()
        bar.setValue(bar.value() + (1 if angle < 0 else -1))
        event.accept()

    def _zoom(self, finer: bool, cursor: QPoint) -> None:
        """Alt/Opt + wheel one notch (design D6): one ladder step anchored at
        the row under the cursor — zooming out pins that row's coarser unit on
        top (:func:`zoom_target`: card/header → its month, month → its year),
        zooming in pins the row's own day/period; a gap row or a cursor past
        the tape rows falls back to the first-visible row as the anchor, which
        is the spec's «верхняя позиция» rule. The knob change is *emitted* for
        the panel to write through the ViewModel (the single mutation point);
        clamped notches (past «сутки»/«год») are silent.

        Zooming in is a descent, so it also installs the anchor period as the
        «Выбор даты» window (:func:`period_span`, spec «Приближение от карточки
        события»: «ступень — сутки, окно — август»; «Проваливание по уровням
        SHALL выставлять окно, равное периоду проваливания»). When the window
        moved the pair rides the drill channel so the panel writes window-then-
        rung and the chip caption follows (a drill and an inward wheel are the
        same descent). Zooming OUT never touches the window — «Якорь при
        отдалении» pins only the top unit.
        """
        target = zoom_level(self._level, 1 if finer else -1)
        if target is self._level:
            return  # the ladder clamps at «сутки» and «год»
        top_row = self._row_at_top()
        row = self._row_at(cursor) or top_row
        anchor = row.date if (finer and row is not None) \
            else zoom_target(self._level, row)
        if anchor is None and top_row is not None and row is not top_row:
            # a gap row (or no row at all) under the cursor — fall back onto
            # the first-visible row, the spec's «верхняя позиция» anchor
            anchor = top_row.date if finer \
                else zoom_target(self._level, top_row)
        window = self._window
        if finer:
            span = period_span(row) or (
                period_span(top_row) if row is not top_row else None
            )
            if span is not None:
                window = span
        window_moved = window != self._window
        self._level = target
        self._window = window
        self._rebuild(self._events)
        if anchor is not None:
            idx = self._index_at_date(anchor)
            if idx is not None:
                self._scroll_row_to_top(idx)
        self._reassert_selection()
        self.scale_changed.emit(target)
        if window_moved:
            self.period_drilled.emit(target, window)

    def _row_at(self, viewport_pos: QPoint):
        """The ladder row sitting under a viewport coordinate (``None`` off
        the row block)."""
        item = self.itemAt(viewport_pos)
        if item is None:
            return None
        idx = self.row(item)
        return self._rows[idx] if 0 <= idx < len(self._rows) else None

    def _row_at_top(self):
        """The ladder row under the viewport's top edge (the anchor fallback)."""
        return self._rows[max(self.top_visible_index(), 0)] if self._rows else None

    def resizeEvent(self, event) -> None:  # Qt API name
        super().resizeEvent(event)
        self._sync_overlays()


def _normalized_window(window) -> tuple[date | None, date | None]:
    """Normalize the window knob: ``None`` means «Все дни» == (None, None)."""
    if window is None:
        return _NO_WINDOW
    start, end = window
    return (start, end)


def window_chip_text(start: date | None, end: date | None) -> str:
    """Button caption for the active window: «Все дни▾» or game-formatted bounds."""
    if start is None or end is None:
        return WINDOW_CHIP_ALL
    return f"{format_game_date(start)} — {format_game_date(end)} ▾"


class _DateWindowResetButton(QPushButton):
    """Named class so the app-wide popup sheet (W2a D2) can skin the reset:
    the sheet must never carry a generic ``QPushButton`` rule (canvas-proxy
    leak), so every popup-owned widget needs its own selector."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class _DateWindowPopup(QWidget):
    """Top-level two-calendar range popover behind the «Выбор даты» button
    (W3b D9, renamed from the LEGACY pop-under by task 7.2).

    A ``Qt.Popup`` window — dismiss on click-outside and Esc come from Qt; the
    calendars are the game-skinned ``_CustomCalendar`` reused from
    ``custom_date_edit`` (custom month names included). Being top-level it is
    skinned by the application-wide popup sheet (named classes in
    ``compile_popup_qss``), not by an inline stylesheet, and it is not clipped
    by the panel's narrow minimum width.

    Picking (D9): the first click arms the start, the second applies
    ``range_applied(start, end)`` and closes — the window lands LIVE, there is
    no «Применить» button; an earlier second tap re-arms a new start instead of
    emitting a backwards range. «Сбросить» closes with ``range_applied(None,
    None)`` (button returns to «Все дни» — the window's only reset, spec
    «Живое применение и сброс»). When the room under the button cannot host
    both calendars only one stays visible and the two taps assign start/finish
    there — the tip label mirrors the assignment.
    """

    range_applied = Signal(object, object)  # (start date | None, end date | None)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("timelineDateWindowPopup")  # identifier, not style
        # A plain QWidget only paints the sheet's background with the flag on.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._pending_start: date | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        self.tip_label = QLabel(WINDOW_PICK_START)
        layout.addWidget(self.tip_label)
        self.start_calendar = _CustomCalendar(self)
        self.end_calendar = _CustomCalendar(self)
        layout.addWidget(self.start_calendar)
        layout.addWidget(self.end_calendar)
        reset_row = QHBoxLayout()
        reset_row.addStretch()
        self.reset_button = _DateWindowResetButton(WINDOW_RESET_TEXT)
        reset_row.addWidget(self.reset_button)
        layout.addLayout(reset_row)

        self.start_calendar.clicked.connect(self._on_day_clicked)
        self.end_calendar.clicked.connect(self._on_day_clicked)
        self.reset_button.clicked.connect(self._on_reset)

    # ── opening ─────────────────────────────────────────────────────────────

    def open_at(self, anchor: QWidget, current: tuple | None = None) -> None:
        """Arm a fresh pick and drop the popover under ``anchor`` (the button).

        ``current`` pre-fills the two calendars (the active window on a chip
        click, the gap bounds on a collapsed-gap click — task 7.1), without
        applying anything: only taps inside the popover mutate the window.
        Month names are re-read on every open (``refresh_month_names`` reads
        the process-global map), so a rename while the panel stood idle is
        visible without any wiring around it.
        """
        self._pending_start = None
        self.tip_label.setText(WINDOW_PICK_START)
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
        need = WINDOW_DOUBLE_HEIGHT_FACTOR * self.start_calendar.sizeHint().height()
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
            self.tip_label.setText(WINDOW_PICK_END)
            return
        self.range_applied.emit(self._pending_start, chosen)
        self.close()

    def _on_reset(self) -> None:
        self._pending_start = None
        self.range_applied.emit(None, None)
        self.close()


class TimelineWidget(QWidget):
    """Left-panel timeline: header (add, «Выбор даты» + «Скрыть даты без
    событий», jump row) above the day-ladder tape.

    The popover behind the «Выбор даты» button applies the window live (task
    7.1 — the LEGACY chip naming is retired): the panel writes it
    through the ViewModel, whose ``window`` is the single mutation point, and
    re-reads it on every refresh; a collapsed-gap click reopens the same
    popover pre-filled with the gap bounds (spec «Схлопнутый провал кликабелен
    для окна»). The toggle writes ``vm.hide_empty`` — session-only, nothing is
    persisted. The rung is not a header control anymore
    (task 4.1): the Alt/Opt wheel and drill clicks step it inside the list,
    and the panel only mirrors those moves into the VM.
    """

    event_selected = Signal(int)  # event_id (W3 id-contract)
    event_double_clicked = Signal(int)  # event_id
    add_event_requested = Signal()
    add_entity_requested = Signal(str)  # entity_type: character/location/organization/item
    event_types_requested = Signal()  # W4 6.2: «Типы событий…» from the «+» menu
    window_changed = Signal(object, object)  # window pair (start|None, end|None)
    event_dates_moved = Signal(object, object, object)  # (event_id, start, end|None)
    # Inline creation from an empty day (task 6.1): the list forwards the one
    # committed name; the wiring turns it into ``vm.create_event_at``.
    event_create_requested = Signal(object, str)  # (day, name)

    def __init__(
        self,
        timeline_vm,
        parent: QWidget | None = None,
        theme=None,
    ) -> None:
        super().__init__(parent)
        self._vm = timeline_vm
        self._theme = theme
        self._window_range: tuple[date | None, date | None] = (None, None)
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

        # Header row 1 — title, «Выбор даты» + hide toggle (spec «Скрытие дат
        # без событий»: the toggle sits next to the button), «+» menu.
        header = QHBoxLayout()
        header.addWidget(title("Таймлайн событий"))
        header.addStretch()

        self.window_chip = QPushButton(window_chip_text(None, None))
        self.window_chip.setToolTip(WINDOW_BUTTON_TOOLTIP)
        self.window_chip.clicked.connect(self._on_window_chip_clicked)
        header.addWidget(self.window_chip)

        # Session-only knob (task 7.3, spec «Скрытие дат без событий»):
        # default off, nothing persists it — a fresh panel re-reads the VM's
        # ``hide_empty`` (always False in a fresh ViewModel).
        self.hide_empty_toggle = QCheckBox(HIDE_EMPTY_TOGGLE_TEXT)
        self.hide_empty_toggle.setObjectName("hideEmptyToggle")  # id, not style
        self.hide_empty_toggle.setToolTip(
            "Скрыть пустые дни, схлопнутые провалы и пустые периоды"
        )
        self.hide_empty_toggle.toggled.connect(self._on_hide_empty_toggled)
        # Mirror a REAL bool only: test doubles expose truthy stand-in
        # attributes for every knob, and «off by default» must survive them.
        vm_hide = getattr(self._vm, "hide_empty", False)
        self.hide_empty_toggle.setChecked(vm_hide is True)
        header.addWidget(self.hide_empty_toggle)

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

        # Header row 2 — jump navigation. The ladder switcher and the entity
        # grouping button are gone (tasks 4.1/8.1): the rung moves via Alt/Opt
        # + wheel and drill clicks only, and the ladder never groups.
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

        # Live window popover behind the «Выбор даты» button: top-level,
        # skinned through the app-wide popup sheet; parented to the panel for
        # lifetime only.
        self.window_popup = _DateWindowPopup(self)
        self.window_popup.range_applied.connect(self._on_window_range)

        # Jump shortcuts (D8): active only while focus is inside the panel;
        # Alt+Up/Alt+Down are free in the rest of the app.
        jump_prev_shortcut = QShortcut(QKeySequence("Alt+Up"), self)
        jump_prev_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        jump_prev_shortcut.activated.connect(self.jump_prev_event)
        jump_next_shortcut = QShortcut(QKeySequence("Alt+Down"), self)
        jump_next_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        jump_next_shortcut.activated.connect(self.jump_next_event)

        # The day-ladder tape (redesign-timeline-day-ladder).
        self.rows_view = TimelineListView(theme=self._theme)
        self.rows_view.event_selected.connect(self.event_selected.emit)
        self.rows_view.event_double_clicked.connect(self.event_double_clicked.emit)
        # The rail drag died with the rail (task 3.1); the window's second
        # entrance is the collapsed-gap click (task 7.1) — it only seeds the
        # popover, the panel's single ``window_changed`` contract stays the
        # one channel a window reaches the ViewModel through.
        self.rows_view.event_dates_moved.connect(self.event_dates_moved.emit)
        self.rows_view.gap_window_requested.connect(self._on_gap_window_requested)
        # The empty-day inline editor committed a name (task 6.1): forward the
        # pair to the wiring, which drives ``vm.create_event_at`` under the
        # session lock just like the date-move commit.
        self.rows_view.event_create_requested.connect(self.event_create_requested.emit)
        # An Alt/Opt wheel step or a period drill inside the list mirrors into
        # the ViewModel (its setters stay the single mutation point, tasks
        # 4.1/4.2): the list has already re-modelled locally, the write here
        # keeps the VM's knobs (and its selection pruning) in lockstep.
        self.rows_view.scale_changed.connect(self._on_view_scale_changed)
        self.rows_view.period_drilled.connect(self._on_period_drilled)
        layout.addWidget(self.rows_view, 1)

    # ── knob mirroring (VM is the single mutation point, design D7) ──────────

    def _view_knobs(self) -> tuple | None:
        """The ViewModel's ladder knobs, or ``None`` while the VM is a stand-in
        (test doubles expose MagicMock attributes no ladder recognizes)."""
        level = getattr(self._vm, "level", None)
        window = getattr(self._vm, "window", None)
        hide_empty = getattr(self._vm, "hide_empty", None)
        if not isinstance(level, ScaleUnit):
            return None
        if window is not None and (
            not isinstance(window, tuple) or len(window) != 2
        ):
            return None
        if not isinstance(hide_empty, bool):
            return None
        return level, window, hide_empty

    def _sync_from_vm(self) -> None:
        """Reflect the ViewModel's knobs into the list.

        The VM is the single mutation point: the panel's apply paths write its
        knobs (whose setters re-model rows and prune selections), and this
        method mirrors the result into the list via
        :meth:`TimelineListView.set_knobs` (anchor-keeping, selection-pending).
        """
        knobs = self._view_knobs()
        if knobs is None:
            return
        level, window, hide_empty = knobs
        self.rows_view.set_knobs(window=window, level=level, hide_empty=hide_empty)
        # The caption is a mirror of the ViewModel's window, not of the last
        # popover apply: an external descent (search selecting an id outside
        # the window resets it to «Все дни») moves ``vm.window`` past the
        # chip, and the chip must follow on the next sync (defect: a drilled
        # window once left the chip on «Все дни»).
        self._set_window_caption(window)

    def _on_view_scale_changed(self, unit) -> None:
        """The list stepped the ladder itself (Alt/Opt wheel, task 4.1):
        mirror into the VM without echoing a re-model back into the list —
        the list re-modelled (cursor-anchored) before emitting, and the VM's
        level setter re-projects its own rows from there."""
        self._vm.level = unit

    def _on_period_drilled(self, level, window) -> None:
        """A drill click (or an inward Alt/Opt wheel, whose descent reaches the
        panel on the same channel) re-modelled the list locally (tasks 4.1/4.2):
        write the pair through the VM — the window first, so a selection it
        excludes is pruned exactly like the chip path prunes it, then the
        deeper rung. The drill does not re-sync knobs into the list (its
        local re-model already stands), so the caption is pinned right here."""
        self._vm.window = window
        self._vm.level = level
        self._set_window_caption(window)

    # ── «+» menu ─────────────────────────────────────────────────────────────

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

    # ── public panel API (mirrors the list's contract) ──────────────────────

    def update_events(self, events: Sequence[Any]) -> None:
        """Refresh the tape; selection survives while the event stays visible.

        The ViewModel's knobs (window/level/hide_empty) ride along: they are
        mirrored into the list before the sample lands, so a reload never
        silently resets the ladder or drops the «Выбор даты» window (the
        ``level`` re-default to DAY is the ViewModel's own load behavior).
        """
        self._sync_from_vm()
        self.rows_view.update_events(events)

    def set_selected(self, event_id: int | None) -> None:
        """Highlight ``event_id`` (idempotent); revealed if not already visible.

        An external selection first mirrors the ViewModel's knobs: an id
        arriving from search while the VM has descended the ladder (its
        ``select_event_by_id`` already moved ``level``/``window``) must find
        the cards that descent just modelled (spec «Внешний выбор с крупной
        ступени спускает лестницу»).
        """
        self._sync_from_vm()
        self.rows_view.set_selected(event_id)

    def scroll_to_event(self, event_id: int) -> None:
        """Scroll the tape just enough to reveal the event's first card."""
        self.rows_view.scroll_to_event(event_id)

    # ── ladder-aware jump commands ─────────────────────────────────────────

    def _descend_for_jump(self) -> None:
        """Period rungs own no event cards — drop the VM's ladder to DAY and
        re-model before retrying the jump; a no-op when DAY is already current
        or the VM is a test stand-in."""
        self._vm.level = ScaleUnit.DAY
        self._sync_from_vm()

    def jump_prev_event(self) -> None:
        """Scroll to the nearest event card before the reading position."""
        if self.rows_view.jump_prev_event():
            return
        self._descend_for_jump()
        self.rows_view.jump_prev_event()

    def jump_next_event(self) -> None:
        """Scroll to the nearest event card after the reading position."""
        if self.rows_view.jump_next_event():
            return
        self._descend_for_jump()
        self.rows_view.jump_next_event()

    # ── «Выбор даты» button + hide toggle (tasks 7.1–7.3) ───────────────────

    def _on_window_chip_clicked(self) -> None:
        """Drop the live range popover under the button, seeded with the window."""
        self.window_popup.open_at(self.window_chip, self._window_range)

    def _set_window_caption(self, window) -> None:
        """The ONE writer of the chip caption and the popover's pre-fill seed.

        Every path that moves the window — popover apply, drill click, inward
        wheel, an external selection reset — lands the caption here, so the
        chip never reads «Все дни» under an active window. ``None`` bounds are
        «Все дни» (:func:`_normalized_window`)."""
        start, end = _normalized_window(window)
        self._window_range = (start, end)
        self.window_chip.setText(window_chip_text(start, end))

    def _on_window_range(self, start, end) -> None:
        """Popover live-apply: button caption + the panel's single signal."""
        self._set_window_caption((start, end))
        self.window_changed.emit(start, end)

    def _on_gap_window_requested(self, start, end) -> None:
        """A collapsed gap was clicked (task 7.1, spec «Схлопнутый провал
        кликабелен для окна»): reopen the same popover PRE-FILLED with the
        gap's bounds under the «Выбор даты» button. Pre-fill only — the window
        itself lands when a tap inside the popover completes the range."""
        self.window_popup.open_at(self.window_chip, (start, end))

    def _on_hide_empty_toggled(self, checked: bool) -> None:
        """Header toggle (task 7.3, spec «Скрытие дат без событий»): the write
        goes through the ViewModel — the single mutation point — and its knobs
        are mirrored back into the tape (empty positions cut, the reading
        position kept). Session-only state: nothing is persisted."""
        self._vm.hide_empty = bool(checked)
        self._sync_from_vm()

    def cover_window_for_span(self, start: date, end: date | None) -> None:
        """Widen the ACTIVE «Выбор даты» window so ``[start, end|start]``
        lands inside it (task 5.3, spec «Унос за окно расширяет окно»).

        The wiring calls this *before* a drop commit writes the new dates, so
        the moved event can never land outside the visible tape. No-op
        without a window. The expansion rides the existing window path
        (:meth:`_on_window_range`) so caption and ``window_changed`` stay in
        lockstep.
        """
        wn_start, wn_end = self._window_range
        if wn_start is None or wn_end is None:
            return
        span_end = start if end is None else end
        if start >= wn_start and span_end <= wn_end:
            return
        self._on_window_range(min(start, wn_start), max(span_end, wn_end))
