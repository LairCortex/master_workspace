"""QTextEdit with @mention support — inline entity references."""
from __future__ import annotations

import re
from html import escape as html_escape

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor, QTextCursor
from PySide6.QtWidgets import (
    QListWidget, QListWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from app.presentation.theme.compiler import mention_style

# Storage format: @[Display Name](entity_type:entity_id)
_MENTION_RE = re.compile(r"@\[([^\]]+)\]\((\w+):(\d+)\)")

_TYPE_ICONS = {
    "event": "\U0001f4c5",       # 📅
    "organization": "\U0001f465", # 👥
    "character": "\U0001f9d1",    # 🧑
    "item": "\U0001f4e6",         # 📦
    "location": "\U0001f4cd",     # 📍
}


# ── Conversion helpers ────────────────────────────────────────────────────

def mention_anchor_style(runtime) -> str:
    """Inline style for mention anchors from the theme runtime (W2b D2).

    Off-skin (no runtime / invalid tokens) returns an empty attribute value:
    links stay functional but carry no invented color (D7 — never a
    half-applied theme)."""
    if runtime is None or not getattr(runtime, "is_valid", False):
        return ""
    return mention_style(runtime.tokens, runtime.theme)


def mentions_to_html(text: str, style: str = "") -> str:
    """Convert plain text with @[Name](type:id) markers to HTML for QTextEdit.

    ``style`` is the inline-HTML style for the anchor (accent from the tokens,
    D2); an empty style emits a bare anchor — the marker format itself is
    storage and stays untouched.
    """
    if not text:
        return ""
    style_attr = f' style="{style}"' if style else ""
    parts: list[str] = []
    last = 0
    for m in _MENTION_RE.finditer(text):
        # Plain text before the mention
        before = text[last:m.start()]
        parts.append(html_escape(before).replace("\n", "<br>"))
        name, etype, eid = m.group(1), m.group(2), m.group(3)
        parts.append(
            f'<a href="mention://{etype}/{eid}"{style_attr}>'
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

class MentionPopupListView(QListWidget):
    """Mention result list — named class so the app-wide popup sheet (W2a D2)
    styles it (surface/bg, item padding, accent selection) without any inline
    table here; anything else stays on the OS palette until migrated."""


class _MentionPopup(QWidget):
    """Floating list that shows search results for @-mention.

    Also a named class: the popup sheet paints its own background with
    ``color.bg.surface``, so no OS-palette strip is left where the list is
    shorter than the popup (``setMaximumHeight`` + resize).
    """

    item_selected = Signal(dict)  # {type, id, name}

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        # Required for a plain QWidget to paint the background from a sheet.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.setMinimumWidth(260)
        self.setMaximumHeight(220)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._list = MentionPopupListView()
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
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
    """QTextEdit that supports @mention autocomplete and clickable entity links.

    ``theme`` (optional W2b runtime): mention anchors are colored with the
    ``color.accent`` token via the compiler's inline style, and the editor
    subscribes ``refresh_content`` as a retheme callback, so a live theme
    switch recolors existing mentions without any screen-side edits (D2).
    """

    mention_clicked = Signal(str, int)  # (entity_type, entity_id)
    mention_search_requested = Signal(str)  # query text after @

    def __init__(self, parent: QWidget | None = None, theme=None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._mention_start: int = -1  # cursor position of '@'
        self._popup = _MentionPopup()
        self._popup.item_selected.connect(self._insert_mention)
        self.setMouseTracking(True)
        # Make links clickable via cursor change
        self.viewport().setCursor(Qt.CursorShape.IBeamCursor)
        if theme is not None:
            # The editor is the widget itself, not a chrome root, so there is
            # no ``attach_theme`` call to hang the retheme callback on (panels
            # use that sugar); the runtime listener is the same path.
            theme.add_listener(self.refresh_content)

    # ── Public API ────────────────────────────────────────────────────

    def setContent(self, text: str) -> None:
        """Load text with mention markers into the editor."""
        if _MENTION_RE.search(text or ""):
            self.setHtml(mentions_to_html(text, mention_anchor_style(self._theme)))
        else:
            self.setPlainText(text or "")

    def refresh_content(self) -> None:
        """Re-tint existing mention anchors with the current accent token.

        Called by the runtime after a live theme switch. Formats are edited
        in place instead of rebuilding the document (W2b review): a
        ``setHtml`` roundtrip would wipe the caret, the selection *and* the
        whole undo history of what the user typed.

        A theme switch is a repaint, not user content: the document must not
        end up ``modified`` because of it, or every open entity card goes
        "dirty" on a theme toggle and closing it warns about colors the user
        never typed. The flag is captured before the edit block and restored
        after it (undo still rolls the tint back with the typing).

        Two passes: collect the anchor ranges first — re-formatting fragments
        while iterating may split them and invalidate the fragment iterator.
        """
        runtime = self._theme
        if runtime is None or not getattr(runtime, "is_valid", False):
            return  # off-skin: anchors carry no invented color (D7)
        accent = QColor(runtime.tokens["color.accent"][runtime.theme])
        if not accent.isValid():
            return
        doc = self.document()
        ranges: list[tuple[int, int]] = []
        block = doc.begin()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                if frag.isValid():
                    fmt = frag.charFormat()
                    if fmt.isAnchor() and fmt.anchorHref().startswith("mention://"):
                        ranges.append((frag.position(), frag.length()))
                it += 1
            block = block.next()
        if not ranges:
            return
        was_modified = doc.isModified()
        cursor = QTextCursor(doc)
        cursor.beginEditBlock()
        for position, length in ranges:
            cursor.setPosition(position)
            cursor.setPosition(position + length, QTextCursor.MoveMode.KeepAnchor)
            fmt = cursor.charFormat()
            fmt.setForeground(accent)
            cursor.mergeCharFormat(fmt)
        cursor.endEditBlock()
        doc.setModified(was_modified)

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
        style = mention_anchor_style(self._theme)
        style_attr = f' style="{style}"' if style else ""
        cursor.insertHtml(
            f'<a href="mention://{etype}/{eid}"{style_attr}>{name}</a>&nbsp;'
        )
        self._mention_start = -1
        self._popup.hide()

    def _cancel_mention(self) -> None:
        self._mention_start = -1
        self._popup.hide()
