"""SheetFrame — the widget-side sheet container (nri-0024, task 1.1, design Д1).

Island sheets (event, entity card) carry their header inside QML; the content
that stays widgets (documents, the table desk, the image viewer, the link
picker — this change's later slices) gets the same visible contract without
becoming an island. One header row «title + Закрыть» wears the library's
ThemeSheetHeader отступы (space.md flanking, space.sm vertical — the very
tokens.json numbers the QML resolves through Tokens.px), a content slot sits
under it, and the sheet-stack scrim dims the frame the way the islands'
sheetScrim layer dims theirs.

The close button performs exactly the cancel action Esc performs
(``QDialog.reject``) — spec modal-sheets «кнопку закрытия, выполняющую
отменяющее действие (как Esc)», one path, both outcomes pinned equal by
tests. Being a QDialog, the frame takes the connector's one sheet show-
contract (``ApplicationWiring.open_sheet``: WindowModal over its parent,
stack-owned, released on ``finished``) like every island sheet does.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.presentation.theme.catalog import attach_theme, set_role
from app.presentation.theme.qml_palette import SCRIM_COLOR

#: Fallbacks of the header отступы — the numbers tokens.json itself carries
#: (space.md / space.sm); only an off-skin sheet (design D7) ever reads them.
_SIDE_MARGIN_FALLBACK_PX = 16
_ROW_MARGIN_FALLBACK_PX = 8


class _SheetScrim(QWidget):
    """The stack-dim layer of a widget sheet: the ``color.scrim`` material
    over the whole frame, mouse-transparent like the islands' overlay — the
    dim must never trap the sheet's own input (EventDialogRoot's rule)."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("sheetFrameScrim")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._alpha = 0.0
        self.hide()

    @property
    def alpha(self) -> float:
        return self._alpha

    def set_alpha(self, alpha: float) -> None:
        self._alpha = alpha
        self.setVisible(alpha > 0.0)
        if alpha > 0.0:
            # The dim crowns the content exactly like the last sheetScrim
            # Rectangle crowns an island root; at zero it is not painted.
            self.raise_()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 — Qt API
        painter = QPainter(self)
        color = QColor(SCRIM_COLOR)
        color.setAlphaF(self._alpha)
        painter.fillRect(self.rect(), color)


class SheetFrame(QDialog):
    """Title row + «Закрыть» + content slot — the widget twin of the QML
    sheet chrome (see the module docstring for the contract it pins)."""

    def __init__(
        self,
        title: str,
        parent: QWidget | None = None,
        theme=None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        side_px = self._token_px("space.md", _SIDE_MARGIN_FALLBACK_PX)
        row_px = self._token_px("space.sm", _ROW_MARGIN_FALLBACK_PX)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget(self)
        self._header = header
        header.setObjectName("sheetFrameHeader")
        row = QHBoxLayout(header)
        # ThemeSheetHeader.qml: title at space.md from the left edge, close
        # at space.md from the right, the row breathed by space.sm vertically.
        row.setContentsMargins(side_px, row_px, side_px, row_px)
        self._title_label = QLabel(header)
        self._title_label.setObjectName("sheetFrameTitle")
        set_role(self._title_label, "title")
        close = QPushButton("Закрыть", header)
        close.setObjectName("sheetFrameCloseButton")
        # One cancel path with Esc: the dialog's own reject (spec «как Esc»).
        close.clicked.connect(self.reject)
        # The frame never volunteers this button as the dialog's default:
        # Enter inside a sheet's field must reach the field, not the exit
        # (the table desk pins Enter inert — TB5's contour, NRI-0024 task 5.1).
        close.setDefault(False)
        close.setAutoDefault(False)
        row.addWidget(self._title_label)
        row.addStretch(1)
        row.addWidget(close)
        layout.addWidget(header)

        # PR-005: Esc is the sheet's OWN result, not a favour of whatever widget
        # holds focus. QDialog answers Escape in its keyPressEvent — a route that
        # only runs if the key ARRIVES, and the live island sheets proved it does
        # not: a QQuickWidget forwards the key to its offscreen QQuickWindow,
        # which accepts it there (live trace 2026-10-05: «key-> QQuickWindow(
        # …OffscreenWindow) → accepted=True» with focus inside the document), so
        # the frame never saw the press and the sheet stayed open. The frame
        # therefore answers the key on the content itself (eventFilter below,
        # armed by add_content): Qt consults event filters BEFORE the widget's
        # own keyPressEvent, so Escape dies on the frame's terms instead of the
        # island's, and native popups (separate windows) keep their own Escape.

        content = QWidget(self)
        content.setObjectName("sheetFrameContent")
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(content, 1)

        self._scrim = _SheetScrim(self)
        self._scrim.setGeometry(self.rect())

        # The header names the sheet with the same text as windowTitle — one
        # threaded value (the EventDialog's sheetTitle rule, task 4.2 of the
        # sheet-header change): the label exists by now, later renames ride
        # the override below.
        self.setWindowTitle(title)

        if self._theme is not None:
            # The chrome catalog is the widget side of ThemeRuntime: one
            # attach gives the frame the button face and title role, live
            # re-theming for free (W2a), and — as a sheet — the SHEET canvas
            # (color.bg.surface) the island content continues, so no chrome
            # strip can sit above the header (live defect 2026-10-02).
            attach_theme(self, self._theme, sheet=True)
            self._theme.apply()

    def _token_px(self, key: str, fallback: int) -> int:
        """A size token as integer px from the runtime's loaded tokens;
        off-skin (D7 — no tokens) the sheet keeps the token's own number."""
        tokens = self._theme.tokens if self._theme is not None else None
        if tokens is None:
            return fallback
        return int(tokens[key][self._theme.theme].removesuffix("px"))

    # ── content slot ─────────────────────────────────────────────────────────

    @property
    def header(self) -> QWidget:
        """The header row widget — for sheets that size their content
        against the chrome (the calendar wizard's height fit, task 3.1)."""
        return self._header

    @property
    def content_layout(self) -> QVBoxLayout:
        """The frame's content area under the header (fill it yourself)."""
        return self._content_layout

    def add_content(self, widget: QWidget, stretch: int = 0) -> None:
        """Seat one content widget into the slot below the header."""
        # PR-005: arm the frame's own Escape answer on this widget (see the
        # eventFilter below) — Qt runs the filter before the widget's
        # keyPressEvent, so a content that eats the key (the island's
        # offscreen QQuickWindow) cannot keep the sheet open.
        widget.installEventFilter(self)
        self._content_layout.addWidget(widget, stretch)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 — Qt API
        if (
            event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Escape
        ):
            # The one cancel path shared with the header's «Закрыть» button.
            self.reject()
            return True
        return super().eventFilter(obj, event)

    # ── header ⇄ windowTitle (spec: «текст, соответствующий windowTitle») ───

    def setWindowTitle(self, title: str) -> None:  # noqa: N802 — Qt API
        super().setWindowTitle(title)
        self._title_label.setText(title)

    # ── sheet-stack contract (ApplicationWiring dims covered sheets through
    # it — the duck the island dialogs already answer; the connector never
    # asks what class a sheet is) ────────────────────────────────────────────

    def set_sheet_scrim_alpha(self, alpha: float) -> None:
        self._scrim.set_alpha(alpha)

    @property
    def sheet_scrim_alpha(self) -> float:
        return self._scrim.alpha

    def resizeEvent(self, event) -> None:  # noqa: N802 — Qt API
        super().resizeEvent(event)
        self._scrim.setGeometry(self.rect())
