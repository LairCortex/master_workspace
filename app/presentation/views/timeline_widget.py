"""Timeline widget — Gantt-like event scale (W3) with the panel header.

The panel keeps its name, header («+» menu, date-range filter) and signals;
the ``QListWidget`` body was replaced by ``TimelineCanvas`` — a QWidget that
paints one bar per event over a linear day scale. All geometry math lives in
the Qt-free :mod:`track_layout` core; this file only renders a ``TrackPlan``
and maps mouse events back to event ids. Colors are token derivatives only
(W3 D4): nothing here hardcodes a hex value or reads the OS palette.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from PySide6.QtCore import QDate, QPointF, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QToolTip, QVBoxLayout, QWidget, QMenu,
)

from app.presentation.theme.catalog import attach_theme, title
from app.presentation.theme.compiler import token_rgb
from app.presentation.utils.date_utils import format_game_date
from app.presentation.views.custom_date_edit import CustomDateEdit
from app.presentation.views.track_layout import (
    SKEW_W,
    EventSpan,
    TrackMetrics,
    TrackPlan,
    build_plan,
)

#: Empty-selection hint painted centered on the canvas (spec: пустое состояние).
EMPTY_HINT_TEXT = "Нет событий в диапазоне"

#: ``set_events`` default: keep the current selection (mutation reloads).
_KEEP = object()

#: Fill alphas of the bar states — derivatives of the accent token (W3 D4).
BAR_FILL_ALPHA = 0.35
BAR_HOVER_ALPHA = 0.6
BAR_BORDER_ALPHA = 0.8
BAR_RADIUS = 3.0
PEN_WIDTH = 1

#: angleDelta units of one wheel notch (Qt convention) — see ``wheelEvent``.
WHEEL_ANGLE_NOTCH = 120.0


@dataclass(frozen=True)
class _Palette:
    """QColors for one paint pass, all derived from tokens of the live theme."""

    background: QColor
    grid: QColor
    axis_text: QColor
    bar_fill: QColor
    bar_hover: QColor
    bar_border: QColor
    bar_selected: QColor
    bar_text: QColor
    bar_text_selected: QColor
    hint: QColor


def _from_rgb(rgb, alpha: float = 1.0) -> QColor:
    """Token RGB → QColor with an explicit alpha (None → neutral Qt global)."""
    color = QColor(*rgb) if rgb is not None else QColor(Qt.GlobalColor.gray)
    color.setAlphaF(alpha)
    return color


def _global(name: Qt.GlobalColor, alpha: float = 1.0) -> QColor:
    """Named Qt global → QColor: the only paint source without live tokens.

    Off-skin (no runtime / unparsable token) the canvas still has to be
    legible, and inventing a hex for that moment would break the ui-theme
    invariant — named Qt globals are theme-neutral constants, not colors this
    app owns (spec scenario «Вне скина», design D4).
    """
    color = QColor(name)
    color.setAlphaF(alpha)
    return color


def canvas_palette(runtime) -> _Palette:
    """Derive every canvas color from the runtime's current tokens (W3 D4).

    On-skin every entry is a token derivation. Off-skin (no runtime / invalid
    tokens) the canvas falls back to named Qt globals only — neutral paint for
    a state where no token exists to derive from, never an app-owned hex.
    """
    off_skin = runtime is None or not getattr(runtime, "is_valid", False)
    if off_skin:
        return _Palette(
            background=_from_rgb(None, 0.15),
            grid=_global(Qt.GlobalColor.gray, 0.4),
            axis_text=_global(Qt.GlobalColor.gray),
            bar_fill=_global(Qt.GlobalColor.gray, BAR_FILL_ALPHA),
            bar_hover=_global(Qt.GlobalColor.gray, BAR_HOVER_ALPHA),
            bar_border=_global(Qt.GlobalColor.gray, BAR_BORDER_ALPHA),
            bar_selected=_global(Qt.GlobalColor.gray),
            bar_text=_global(Qt.GlobalColor.black),
            bar_text_selected=_global(Qt.GlobalColor.white),
            hint=_global(Qt.GlobalColor.gray),
        )
    tokens, theme = runtime.tokens, runtime.theme
    accent = token_rgb(tokens, theme, "color.accent")
    return _Palette(
        background=_from_rgb(token_rgb(tokens, theme, "color.bg.surface")),
        grid=_from_rgb(token_rgb(tokens, theme, "color.border"), 0.6),
        axis_text=_from_rgb(token_rgb(tokens, theme, "color.fg.muted")),
        bar_fill=_from_rgb(accent, BAR_FILL_ALPHA),
        bar_hover=_from_rgb(accent, BAR_HOVER_ALPHA),
        bar_border=_from_rgb(accent, BAR_BORDER_ALPHA),
        bar_selected=_from_rgb(accent),
        bar_text=_from_rgb(token_rgb(tokens, theme, "color.fg.primary")),
        bar_text_selected=_from_rgb(token_rgb(tokens, theme, "color.accent.fg")),
        hint=_from_rgb(token_rgb(tokens, theme, "color.fg.muted")),
    )


class TimelineCanvas(QWidget):
    """The event scale itself: paints a TrackPlan, maps clicks to event ids.

    Signals carry **event ids** (the W3 id-contract, design D3); selection
    state lives in the ViewModel, this widget only renders what it is given
    and stays idempotent on repeated identical input.
    """

    event_selected = Signal(int)  # event_id
    event_double_clicked = Signal(int)  # event_id

    def __init__(self, theme=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._events: tuple[Any, ...] = ()
        self._event_ids: tuple[int, ...] = ()
        self._selected_id: int | None = None
        self._hover_id: int | None = None
        self._scroll_y = 0.0
        # Layout/text caches: a paint pass must not re-measure every label or
        # re-pack lanes unless the input (events, size, font) actually moved.
        self._events_epoch = 0
        self._layout_key: tuple | None = None
        self._text_key: tuple | None = None
        self._text_cache: dict[int, float] = {}
        self._plan = build_plan((), self._metrics())
        self.setMouseTracking(True)
        if theme is not None:
            # Live re-theme (D4): repaint with the new tokens, keeping the
            # selection and the scroll offset exactly where they were.
            theme.add_listener(self._retheme)

    # ── public API (task 2.4) ───────────────────────────────────────────────

    @property
    def events(self) -> tuple[Any, ...]:
        """The events currently rendered (test/E2E introspection)."""
        return self._events

    @property
    def plan(self) -> TrackPlan:
        """The last laid-out plan (bars, scale, vertical metrics)."""
        return self._plan

    @property
    def selected_id(self) -> int | None:
        return self._selected_id

    def set_events(self, events: Sequence[Any], selected_id: Any = _KEEP) -> None:
        """Replace the rendered selection; ``selected_id`` defaults to keeping.

        Without the argument the current selection is kept when the event is
        still among ``events`` (mutation-reload paths, task 3.3) and dropped
        otherwise — the ViewModel prunes its own selection the same way, so
        canvas and VM never disagree about what is highlighted.

        A different set of event ids also rewinds the vertical scroll: a new
        packing (typically another filter result) must always open from the
        first lane. Reloading the same ids (create/edit of one event) keeps
        the reading position.
        """
        new_events = tuple(events)
        new_ids = tuple(e.id for e in new_events)
        membership_changed = new_ids != self._event_ids
        self._events = new_events
        self._event_ids = new_ids
        self._events_epoch += 1
        if selected_id is not _KEEP:
            self._selected_id = selected_id
        if self._selected_id is not None:
            if not any(e.id == self._selected_id for e in self._events):
                self._selected_id = None
        if membership_changed:
            self._scroll_y = 0.0
        self._plan = self._layout()
        self._scroll_y = self._plan.clamped_scroll(self._scroll_y)
        self.update()

    def set_selected(self, event_id: int | None) -> None:
        """Highlight ``event_id``; idempotent — the same id never relayouts."""
        if event_id == self._selected_id:
            return
        self._selected_id = event_id
        self.update()

    def scroll_to_event(self, event_id: int) -> None:
        """Scroll the lane area just enough to reveal the bar (search jump)."""
        self._plan = self._layout()
        self._scroll_y = self._plan.required_scroll(event_id, self._scroll_y)
        self.update()

    def tooltip_text(self, event_id: int) -> str:
        """Tooltip body: name plus the game-formatted date range (D5)."""
        event = self._event_by_id(event_id)
        if event is None:
            return ""
        start = format_game_date(event.start_date)
        end = format_game_date(event.end_date, "—")
        return f"{event.name}\n{start} — {end}"

    def axis_labels(self) -> list[str]:
        """Month-boundary labels of the current layout (re-lays out first)."""
        self._plan = self._layout()
        return [format_game_date(tick) for tick in self._plan.ticks]

    # ── layout / painting ───────────────────────────────────────────────────

    def _metrics(self) -> TrackMetrics:
        return TrackMetrics(
            viewport_w=max(1.0, float(self.width())),
            viewport_h=max(1.0, float(self.height())),
        )

    def _font_key(self) -> tuple:
        """Hashable identity of the font the labels are measured with."""
        font = self.font()
        return (font.family(), round(font.pointSizeF(), 3), int(font.weight()), font.italic())

    def _text_widths(self) -> dict[int, float]:
        """Measured label widths, cached until the events or the font change."""
        key = (self._events_epoch, self._font_key())
        if key != self._text_key:
            fm = QFontMetrics(self.font())
            self._text_cache = {
                event.id: float(fm.horizontalAdvance(event.name)) for event in self._events
            }
            self._text_key = key
        return self._text_cache

    def _layout(self) -> TrackPlan:
        """The current plan, rebuilt only when its inputs actually changed.

        Painting, wheeling and hit-testing all go through here many times per
        second; packing plus label measuring is O(N log N), so the result is
        cached against (event set version, viewport size, font).
        """
        key = (self._events_epoch, float(self.width()), float(self.height()), self._font_key())
        if key != self._layout_key:
            spans = tuple(
                EventSpan(event.id, event.start_date, event.end_date) for event in self._events
            )
            self._plan = build_plan(spans, self._metrics(), self._text_widths())
            self._layout_key = key
        return self._plan

    def _retheme(self) -> None:
        """Repaint from the new tokens; selection/scroll deliberately untouched."""
        self.update()

    def _event_by_id(self, event_id: int) -> Any | None:
        return next((e for e in self._events if e.id == event_id), None)

    def paintEvent(self, event) -> None:  # Qt API name
        painter = QPainter(self)
        palette = canvas_palette(self._theme)
        painter.fillRect(self.rect(), palette.background)
        plan = self._plan
        if plan.is_empty:
            self._paint_hint(painter, palette)
            return
        # Relayout for the live widget size: a cache hit unless the event set,
        # the viewport or the font changed since the last pass (see _layout).
        plan = self._plan = self._layout()
        self._paint_grid_and_axis(painter, plan, palette)
        self._paint_bars(painter, plan, palette)

    def _paint_hint(self, painter: QPainter, palette: _Palette) -> None:
        """The one-line hint when the selection (or the filter) is empty."""
        painter.setPen(QPen(palette.hint))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, EMPTY_HINT_TEXT)

    def _paint_grid_and_axis(self, painter: QPainter, plan: TrackPlan, palette: _Palette) -> None:
        """Month-boundary hairlines + axis labels, clipped label collisions (D6)."""
        fm = QFontMetrics(painter.font())
        axis_h = plan.metrics.axis_h
        pen = QPen(palette.grid)
        pen.setWidthF(1.0)
        painter.setPen(pen)
        next_allowed_x = 0.0
        for tick in plan.ticks:
            x = round(plan.x_of(tick)) + 0.5
            painter.drawLine(
                QPointF(x, axis_h),
                QPointF(x, float(self.height())),
            )
            label = format_game_date(tick)
            label_w = fm.horizontalAdvance(label)
            if x < next_allowed_x:
                continue  # never overlap the drawn neighbor (D6 label clipping)
            painter.setPen(QPen(palette.axis_text))
            painter.drawText(
                QRect(int(x) + 2, 0, self.width(), int(axis_h)),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                label,
            )
            next_allowed_x = x + label_w + plan.metrics.padding
            painter.setPen(pen)

    def _paint_bars(self, painter: QPainter, plan: TrackPlan, palette: _Palette) -> None:
        """Lane bars with hover/selected states, skew marker and clipped text."""
        axis_h = plan.metrics.axis_h
        lane_view = plan.lane_viewport_h
        painter.setClipRect(QRect(0, int(axis_h), self.width(), int(lane_view)))
        for bar in plan.bars:
            top = axis_h + bar.y_top - self._scroll_y
            if top > axis_h + lane_view or top + bar.height < axis_h:
                continue  # fully scrolled out of the lane viewport
            rect_f = (bar.x0, top, bar.width, bar.height - PEN_WIDTH)
            if bar.event_id == self._selected_id:
                fill = palette.bar_selected
                text_color = palette.bar_text_selected
            elif bar.event_id == self._hover_id:
                fill = palette.bar_hover
                text_color = palette.bar_text
            else:
                fill = palette.bar_fill
                text_color = palette.bar_text
            path = self._bar_path(bar.open_end, rect_f)
            painter.setPen(QPen(palette.bar_border, PEN_WIDTH))
            painter.setBrush(fill)
            painter.drawPath(path)
            if bar.text_fits:
                self._paint_bar_label(painter, bar, rect_f, text_color)

    @staticmethod
    def _bar_path(open_end: bool, rect: tuple[float, float, float, float]) -> QPainterPath:
        """Rounded bar, or an arrow right edge marking an open end (D2)."""
        x, y, w, h = rect
        path = QPainterPath()
        if open_end:
            slant = min(SKEW_W, w / 2.0)
            right = x + w
            path.moveTo(x, y)
            path.lineTo(right - slant, y)
            path.lineTo(right, y + h / 2.0)
            path.lineTo(right - slant, y + h)
            path.lineTo(x, y + h)
            path.closeSubpath()
        else:
            path.addRoundedRect(x, y, w, h, BAR_RADIUS, BAR_RADIUS)
        return path

    def _paint_bar_label(
        self,
        painter: QPainter,
        bar,
        rect: tuple[float, float, float, float],
        color: QColor,
    ) -> None:
        x, y, w, h = rect
        inset = self._plan.metrics.text_inset
        painter.setPen(QPen(color))
        painter.drawText(
            QRect(int(x + inset / 2), int(y), int(w - inset), int(h)),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self._event_by_id(bar.event_id).name,
        )

    # ── mouse interaction ───────────────────────────────────────────────────

    def _event_at(self, pos: QPointF) -> int | None:
        if pos.y() < self._plan.metrics.axis_h:
            return None  # the pinned axis strip is not lanes
        return self._plan.event_at_viewport(
            pos.x(), pos.y() - self._plan.metrics.axis_h, self._scroll_y
        )

    def mousePressEvent(self, event) -> None:  # Qt API name
        if event.button() == Qt.MouseButton.LeftButton:
            event_id = self._event_at(event.position())
            if event_id is not None:
                self.set_selected(event_id)
                self.event_selected.emit(event_id)

    def mouseDoubleClickEvent(self, event) -> None:  # Qt API name
        event_id = self._event_at(event.position())
        if event_id is not None:
            self.event_double_clicked.emit(event_id)

    def mouseMoveEvent(self, event) -> None:  # Qt API name
        # The tooltip follows the cursor on any bar (design D5: it always
        # carries the date range, which the in-bar label never shows), but a
        # repaint is only worth scheduling when the hovered bar actually changed.
        event_id = self._event_at(event.position())
        if event_id is not None:
            QToolTip.showText(event.globalPosition().toPoint(), self.tooltip_text(event_id), self)
        else:
            QToolTip.hideText()
        if event_id != self._hover_id:
            self._hover_id = event_id
            self.update()

    def leaveEvent(self, event) -> None:  # Qt API name
        if self._hover_id is not None:
            self._hover_id = None
            self.update()
        QToolTip.hideText()

    def wheelEvent(self, event) -> None:  # Qt API name
        # One wheel notch scrolls exactly one lane row: raw angleDelta (120
        # notch-units) would jump 5–8 lanes at a 14–26 px lane height.
        plan = self._layout()
        row_h = plan.lane_h + plan.metrics.lane_gap
        notches = event.angleDelta().y() / WHEEL_ANGLE_NOTCH
        self._scroll_y = plan.clamped_scroll(self._scroll_y - row_h * notches)
        self.update()

    # ── Qt plumbing ─────────────────────────────────────────────────────────

    def resizeEvent(self, event) -> None:  # Qt API name
        super().resizeEvent(event)
        self._plan = self._layout()
        self._scroll_y = self._plan.clamped_scroll(self._scroll_y)

    def minimumSizeHint(self) -> QSize:  # Qt API name
        return QSize(120, 60)


class TimelineWidget(QWidget):
    """Left-panel timeline: header (add + date filter) above the canvas."""

    event_selected = Signal(int)  # event_id (W3 breaking contract)
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
        self._filter_active = False
        self._init_ui()
        self._apply_theme()

    def _apply_theme(self) -> None:
        """One attach point: the chrome container carries the whole sheet (D1).

        The canvas subscribes to the runtime itself (its painting lives outside
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

        # Header
        header = QHBoxLayout()
        header.addWidget(title("Таймлайн событий"))
        header.addStretch()

        self.add_button = QPushButton("+")
        self.add_button.setFixedSize(30, 30)
        self.add_button.setToolTip("Добавить событие (правый клик — другие сущности)")
        self.add_button.clicked.connect(self.add_event_requested.emit)
        self.add_button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.add_button.customContextMenuRequested.connect(self._on_add_context_menu)
        header.addWidget(self.add_button)
        layout.addLayout(header)

        # Date range filter
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(4)

        filter_layout.addWidget(QLabel("С:"))
        self.filter_start = CustomDateEdit()
        self.filter_start.setDate(QDate(100, 1, 1))
        filter_layout.addWidget(self.filter_start, 1)

        filter_layout.addWidget(QLabel("По:"))
        self.filter_end = CustomDateEdit()
        self.filter_end.setDate(QDate.currentDate())
        filter_layout.addWidget(self.filter_end, 1)

        self.filter_button = QPushButton("▶")
        self.filter_button.setFixedSize(30, 30)
        self.filter_button.setToolTip("Применить фильтр по датам")
        self.filter_button.clicked.connect(self._on_apply_filter)
        filter_layout.addWidget(self.filter_button)

        self.clear_filter_button = QPushButton("✕")
        self.clear_filter_button.setFixedSize(30, 30)
        self.clear_filter_button.setToolTip("Сбросить фильтр")
        self.clear_filter_button.clicked.connect(self._on_clear_filter)
        self.clear_filter_button.setEnabled(False)
        filter_layout.addWidget(self.clear_filter_button)

        layout.addLayout(filter_layout)

        # Event scale (W3: Gantt-like canvas replaces the old QListWidget)
        self.canvas = TimelineCanvas(theme=self._theme)
        self.canvas.event_selected.connect(self.event_selected.emit)
        self.canvas.event_double_clicked.connect(self.event_double_clicked.emit)
        layout.addWidget(self.canvas, 1)

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

    def update_events(self, events: Sequence[Any]) -> None:
        """Refresh the scale; the current selection survives when still visible."""
        self.canvas.set_events(events)

    def _on_apply_filter(self) -> None:
        start = self.filter_start.date().toPython()
        end = self.filter_end.date().toPython()
        self._filter_active = True
        self.clear_filter_button.setEnabled(True)
        self.filter_changed.emit(start, end)

    def _on_clear_filter(self) -> None:
        self._filter_active = False
        self.clear_filter_button.setEnabled(False)
        self.filter_changed.emit(None, None)
