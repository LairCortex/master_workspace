"""QTextEdit with @mention support — inline entity references."""
from __future__ import annotations

import re
from html import escape as html_escape

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QListWidget, QListWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

# Storage format: @[Display Name](entity_type:entity_id)
_MENTION_RE = re.compile(r"@\[([^\]]+)\]\((\w+):(\d+)\)")

_TYPE_ICONS = {
    "event": "\U0001f4c5",       # 📅
    "organization": "\U0001f465", # 👥
    "character": "\U0001f9d1",    # 🧑
    "item": "\U0001f4e6",         # 📦
    "location": "\U0001f4cd",     # 📍
}

_MENTION_STYLE = "color:#5b9bd5;font-weight:bold;text-decoration:none;"


# ── Conversion helpers ────────────────────────────────────────────────────

def mentions_to_html(text: str) -> str:
    """Convert plain text with @[Name](type:id) markers to HTML for QTextEdit."""
    if not text:
        return ""
    parts: list[str] = []
    last = 0
    for m in _MENTION_RE.finditer(text):
        # Plain text before the mention
        before = text[last:m.start()]
        parts.append(html_escape(before).replace("\n", "<br>"))
        name, etype, eid = m.group(1), m.group(2), m.group(3)
        parts.append(
            f'<a href="mention://{etype}/{eid}" style="{_MENTION_STYLE}">'
            f"{html_escape(name)}</a>"
        )
        last = m.end()
    # Tail
    parts.append(html_escape(text[last:]).replace("\n", "<br>"))
    return "".join(parts)


def html_to_mentions(doc) -> str:
    """Walk QTextDocument and reconstruct plain text with mention markers."""
    result: list[str] = []
    block = doc.begin()
    end_block = doc.end()
    first = True
    while block != end_block:
        if not first:
            result.append("\n")
        first = False
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid():
                fmt = frag.charFormat()
                href = fmt.anchorHref() if fmt.isAnchor() else ""
                if href.startswith("mention://"):
                    # Extract type/id from href
                    path = href[len("mention://"):]
                    slash = path.find("/")
                    if slash != -1:
                        etype = path[:slash]
                        eid = path[slash + 1:]
                        result.append(f"@[{frag.text()}]({etype}:{eid})")
                    else:
                        result.append(frag.text())
                else:
                    result.append(frag.text())
            it += 1
        block = block.next()
    return "".join(result)


# ── Popup widget ──────────────────────────────────────────────────────────

class _MentionPopup(QWidget):
    """Floating list that shows search results for @-mention."""

    item_selected = Signal(dict)  # {type, id, name}

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMinimumWidth(260)
        self.setMaximumHeight(220)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._list = QListWidget()
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list.setStyleSheet(
            "QListWidget { font-size: 13px; }"
            "QListWidget::item { padding: 4px 8px; }"
            "QListWidget::item:selected { background: palette(highlight); color: palette(highlighted-text); }"
        )
        self._list.itemClicked.connect(self._on_click)
        lay.addWidget(self._list)

    def show_results(self, results: list[dict], global_pos: QPoint) -> None:
        self._list.clear()
        for r in results[:15]:
            icon = _TYPE_ICONS.get(r["type"], "")
            item = QListWidgetItem(f'{icon}  {r["name"]}')
            item.setData(Qt.ItemDataRole.UserRole, r)
            self._list.addItem(item)
        if self._list.count() == 0:
            self.hide()
            return
        self._list.setCurrentRow(0)
        self.move(global_pos)
        self.show()

    def select_next(self) -> None:
        row = self._list.currentRow()
        if row < self._list.count() - 1:
            self._list.setCurrentRow(row + 1)

    def select_prev(self) -> None:
        row = self._list.currentRow()
        if row > 0:
            self._list.setCurrentRow(row - 1)

    def confirm_selection(self) -> None:
        item = self._list.currentItem()
        if item:
            self._on_click(item)

    def _on_click(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        if data:
            self.item_selected.emit(data)


# ── MentionTextEdit ───────────────────────────────────────────────────────

class MentionTextEdit(QTextEdit):
    """QTextEdit that supports @mention autocomplete and clickable entity links."""

    mention_clicked = Signal(str, int)  # (entity_type, entity_id)
    mention_search_requested = Signal(str)  # query text after @

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._mention_start: int = -1  # cursor position of '@'
        self._popup = _MentionPopup()
        self._popup.item_selected.connect(self._insert_mention)
        self.setMouseTracking(True)
        # Make links clickable via cursor change
        self.viewport().setCursor(Qt.CursorShape.IBeamCursor)

    # ── Public API ────────────────────────────────────────────────────

    def setContent(self, text: str) -> None:
        """Load text with mention markers into the editor."""
        if _MENTION_RE.search(text or ""):
            self.setHtml(mentions_to_html(text))
        else:
            self.setPlainText(text or "")

    def getContent(self) -> str:
        """Return text with mention markers for DB storage."""
        return html_to_mentions(self.document())

    def show_mention_results(self, results: list[dict]) -> None:
        """Called externally (e.g. from main.py) with search results."""
        if not results or self._mention_start < 0:
            self._popup.hide()
            return
        rect = self.cursorRect()
        global_pos = self.mapToGlobal(QPoint(rect.x(), rect.y() + rect.height() + 4))
        self._popup.show_results(results, global_pos)

    # ── Keyboard handling ─────────────────────────────────────────────

    def keyPressEvent(self, event) -> None:
        # If popup is visible, handle navigation keys
        if self._popup.isVisible():
            if event.key() == Qt.Key.Key_Down:
                self._popup.select_next()
                return
            if event.key() == Qt.Key.Key_Up:
                self._popup.select_prev()
                return
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._popup.confirm_selection()
                return
            if event.key() == Qt.Key.Key_Escape:
                self._cancel_mention()
                return

        # Detect '@' start
        if event.text() == "@":
            super().keyPressEvent(event)
            self._mention_start = self.textCursor().position()
            return

        # If we are in mention-typing mode
        if self._mention_start >= 0:
            if event.key() in (Qt.Key.Key_Escape,):
                self._cancel_mention()
                super().keyPressEvent(event)
                return
            if event.key() == Qt.Key.Key_Space:
                self._cancel_mention()
                super().keyPressEvent(event)
                return

            super().keyPressEvent(event)
            self._check_mention_query()
            return

        super().keyPressEvent(event)

    # ── Mouse handling (link click) ───────────────────────────────────

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            anchor = self.anchorAt(event.pos())
            if anchor and anchor.startswith("mention://"):
                path = anchor[len("mention://"):]
                slash = path.find("/")
                if slash != -1:
                    etype = path[:slash]
                    try:
                        eid = int(path[slash + 1:])
                        self.mention_clicked.emit(etype, eid)
                        return
                    except ValueError:
                        pass
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        anchor = self.anchorAt(event.pos())
        if anchor and anchor.startswith("mention://"):
            self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.viewport().setCursor(Qt.CursorShape.IBeamCursor)
        super().mouseMoveEvent(event)

    # ── Internal ──────────────────────────────────────────────────────

    def _check_mention_query(self) -> None:
        """Extract text typed after @ and request search if >= 2 chars."""
        cursor = self.textCursor()
        pos = cursor.position()
        full_text = self.toPlainText()
        # mention_start points AFTER the @, so query is text[mention_start:pos]
        if self._mention_start > len(full_text) or pos > len(full_text):
            self._cancel_mention()
            return
        # User backspaced past the @ — cancel mention mode
        if pos <= self._mention_start - 1:
            self._cancel_mention()
            return
        query = full_text[self._mention_start:pos]
        if len(query) >= 2:
            self.mention_search_requested.emit(query)
        else:
            self._popup.hide()

    def _insert_mention(self, data: dict) -> None:
        """Insert selected mention, replacing @query text."""
        cursor = self.textCursor()
        # Select from @ (one char before _mention_start) to current position
        at_pos = self._mention_start - 1  # position of '@' character
        if at_pos < 0:
            at_pos = 0
        cursor.setPosition(at_pos)
        cursor.setPosition(self.textCursor().position(), QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        # Insert HTML anchor
        etype = data["type"]
        eid = data["id"]
        name = html_escape(data["name"])
        cursor.insertHtml(
            f'<a href="mention://{etype}/{eid}" style="{_MENTION_STYLE}">{name}</a>&nbsp;'
        )
        self._mention_start = -1
        self._popup.hide()

    def _cancel_mention(self) -> None:
        self._mention_start = -1
        self._popup.hide()
