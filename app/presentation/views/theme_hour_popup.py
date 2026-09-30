"""Top-level hour-list popup for the fixed-height search island (task 12.6).

The A1 host half of design Д14.1 (re-audit
docs/qa/2026-09-29-now-hour-chip-fixes.md): the ``ThemeComboBox`` drop-down
is a QQuickPopup and always paints inside its host, and the search-island
facade fixes the widget to the island's implicit height
(``search_bar._sync_island_height``) — inside that low host the 25-value hour
list collapses to ~2 visible rows and hours 18…23 are unreachable by mouse.
The fix follows the date chip sitting on the very same row: the picker goes
through the widgets bridge as a parent-less ``Qt.WindowType.Popup`` top level
that no host can clip. The list rows are the hour list the VM serves
(«—» head, hour H at index H + 1); this widget knows no calendar — the pick
travels back as a list index and the VM re-applies its bounds (design Д5).
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

#: The same cap Д14.1 gave the component's own pop-up (maxRows of
#: ``ThemeComboBox``): eight rows paint, the rest are wheel- and key-reachable.
MAX_VISIBLE_ROWS = 8

#: The vertical band one row adds around its text line — the ``space.xs`` the
#: component's rowHeight math uses (line + 2 bands), kept in lockstep here so
#: the bridge window measures like the themed list it stands in for.
ROW_BAND = 4

#: The horizontal inset of one row (``space.sm``) — same lockstep.
ROW_SIDE = 8

#: The width floor's rounding band (the A11 lesson from
#: docs/qa/2026-09-29-now-hour-chip-fixes.md: a laid-out glyph run lands a
#: hair wider than the metrics' advance) — a row whose text equals the floor
#: must never lose its last pixel to the clip.
WIDTH_BAND = 1


class ThemeHourListView(QListWidget):
    """Named style-facing class of the hour list (the ``_MentionPopup``/
    ``GameCalendarGrid`` recipe of :func:`compile_popup_qss` — the rules live
    in the popup sheet and a rename silently drops the theme; the pair test
    in ``tests/presentation/test_theme_hour_popup.py`` guards both sides).

    Enter/Return activates the highlighted row: ``QAbstractItemView`` emits
    ``activated`` from a double click but not from the return key, while a
    keyboard pick is half of the spec scenario «Все значения часов достижимы»
    — so the key lands on the same ``itemActivated`` channel the mouse uses.
    """

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            item = self.currentItem()
            if item is not None:
                self.itemActivated.emit(item)
                return
        super().keyPressEvent(event)


class ThemeHourPopup(QWidget):
    """One reusable hour list, positioned wholly inside available geometry
    (the placement rule of :class:`ThemeDatePopup`, kept line-for-line)."""

    #: The picked row of the option list («—» heads it, hour H is index
    #: H + 1) — the wiring feeds it to ``NowDateViewModel.requestHour``,
    #: which maps the index onto the hour and bounds-checks it again.
    hour_selected = Signal(int)

    def __init__(self) -> None:
        # Parent-less on purpose, exactly like ThemeDatePopup's P3 rule: a
        # widget-parented top level would inherit the chrome stylesheet chain
        # of its ancestors; only the application-wide popup sheet skins this
        # window, and the opener keeps it alive through its own attribute.
        super().__init__(None, Qt.WindowType.Popup)
        self.setObjectName("themeHourPopup")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        # The window size is the layout's declared contract, min == max ==
        # the list plus its one-pixel frame (user report 2026-09-30): the
        # live popup painted an enormous empty band to the right of the rows
        # because adjustSize() does not clamp a top level whose content is a
        # QAbstractScrollArea — on this Qt the window inflated to 200 px
        # around a fixed-width 70 px list (measured offscreen; the scroll
        # areas inflate, a plain-label window adjusts correctly). Declaring
        # SetFixedSize leaves adjustSize nothing to inflate: the window hugs
        # the list and the list alone decides its width.
        layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetFixedSize)
        self.list = ThemeHourListView(self)
        self.list.setObjectName("themeHourList")
        self.list.setFrameShape(QFrame.Shape.NoFrame)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setUniformItemSizes(True)
        self.list.setWordWrap(False)
        # A single click applies (the combo posture — like the date grid,
        # this window has no accept button), and so does Enter on a row the
        # arrows moved onto.
        self.list.itemClicked.connect(self._on_row_picked)
        self.list.itemActivated.connect(self._on_row_picked)
        layout.addWidget(self.list)

    def open_at(
        self, anchor_global: QRect, options: list[str], current_index: int
    ) -> None:
        """Rebuild the list and open it below a global QML anchor rectangle.

        The rows are the VM's live hour options (the bounds follow the ACTIVE
        calendar, nothing hardcodes 24 — the caller re-reads them on every
        open); ``current_index`` is the highlighted row, clamped into the
        list because a narrowed day can no longer host the stored hour (the
        same sanitisation design Д5 applies to the value itself).
        """
        self.list.clear()
        row_height = self._row_height()
        for text in options:
            item = QListWidgetItem(text, self.list)
            item.setSizeHint(QSize(0, row_height))
        row = min(max(int(current_index), 0), self.list.count() - 1)
        self.list.setCurrentRow(row)

        rows = min(self.list.count(), MAX_VISIBLE_ROWS)
        self.list.setFixedHeight(rows * row_height)
        # The width is the CONTENT column and nothing else: the widest row
        # of the model measured worst-case (the Д14.1/Д14.3 measuring rule —
        # never the realized rows), its two insets, the vertical scrollbar
        # the overflow brings and the A11 rounding band. The anchor's width
        # is NOT a floor: the list must not wear the geometry of the control
        # it hangs under (user report 2026-09-30: the window read host-wide
        # with the rows only a narrow column — empty band to the right).
        fm = self.list.fontMetrics()
        widest = max((fm.horizontalAdvance(text) for text in options), default=0)
        if self.list.count() > MAX_VISIBLE_ROWS:
            widest += self.list.verticalScrollBar().sizeHint().width()
        self.list.setFixedWidth(widest + 2 * ROW_SIDE + WIDTH_BAND)

        position = QPoint(
            anchor_global.x(),
            anchor_global.y() + anchor_global.height() + 2,
        )
        screen = QApplication.screenAt(position) or QApplication.primaryScreen()
        self.adjustSize()
        if screen is not None:
            geometry = screen.availableGeometry()
            position.setX(
                max(
                    geometry.left(),
                    min(position.x(), geometry.right() - self.width() + 1),
                )
            )
            position.setY(
                max(
                    geometry.top(),
                    min(position.y(), geometry.bottom() - self.height() + 1),
                )
            )
        self.move(position)
        self.show()
        # The highlighted row is visible without manual scrolling (A2's rule
        # for the component popup, mirrored): PositionAtTop is the bridge's
        # reading of positionViewAtIndex(currentIndex, ListView.Beginning),
        # clamped by Qt itself at the bottom of a long list.
        self.list.scrollToItem(
            self.list.item(row), QAbstractItemView.ScrollHint.PositionAtTop
        )
        if screen is not None:
            frame = self.frameGeometry()
            dx = max(geometry.left() - frame.left(), 0)
            dx += min(geometry.right() - (frame.right() + dx), 0)
            dy = max(geometry.top() - frame.top(), 0)
            dy += min(geometry.bottom() - (frame.bottom() + dy), 0)
            if dx or dy:
                self.move(self.pos() + QPoint(dx, dy))
        self.list.setFocus(Qt.OtherFocusReason)

    def _row_height(self) -> int:
        """One row: one text line plus the ``space.xs`` bands top and bottom
        — measured from the widget's own font, never from realized items."""
        return self.list.fontMetrics().height() + 2 * ROW_BAND

    def _on_row_picked(self, item: QListWidgetItem) -> None:
        self.hour_selected.emit(self.list.row(item))
        self.close()
