"""Tests for MentionTextEdit — @mention widget."""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QMouseEvent, QTextCursor

from app.presentation.views.mention_text_edit import (
    MentionTextEdit,
    _MentionPopup,
    html_to_mentions,
    mentions_to_html,
)


# ── mentions_to_html ──────────────────────────────────────────────────────


class TestMentionsToHtml:
    def test_plain_text_unchanged(self):
        result = mentions_to_html("Просто текст без упоминаний")
        assert "Просто текст без упоминаний" in result
        assert "<a " not in result

    def test_single_mention(self):
        text = "Встреча с @[Артас](character:42) в таверне"
        result = mentions_to_html(text)
        assert 'href="mention://character/42"' in result
        assert "Артас" in result
        assert "в таверне" in result
        assert "@[" not in result

    def test_multiple_mentions(self):
        text = "@[Орда](organization:1) атаковала @[Штормград](location:5)"
        result = mentions_to_html(text)
        assert 'mention://organization/1' in result
        assert 'mention://location/5' in result
        assert "Орда" in result
        assert "Штормград" in result

    def test_empty_string(self):
        assert mentions_to_html("") == ""

    def test_none_string(self):
        assert mentions_to_html(None) == ""

    def test_html_chars_escaped(self):
        text = "A <b>bold</b> text with @[Персонаж](character:1)"
        result = mentions_to_html(text)
        assert "&lt;b&gt;" in result
        assert 'mention://character/1' in result


# ── html_to_mentions ──────────────────────────────────────────────────────


class TestHtmlToMentions:
    def test_plain_text_roundtrip(self, qtbot):
        edit = MentionTextEdit()
        qtbot.addWidget(edit)
        edit.setPlainText("Просто текст")
        result = html_to_mentions(edit.document())
        assert result == "Просто текст"

    def test_mention_roundtrip(self, qtbot):
        edit = MentionTextEdit()
        qtbot.addWidget(edit)
        original = "Встреча с @[Артас](character:42) в таверне"
        edit.setContent(original)
        result = edit.getContent()
        assert "@[Артас](character:42)" in result
        assert "Встреча с" in result
        assert "в таверне" in result

    def test_multiple_mentions_roundtrip(self, qtbot):
        edit = MentionTextEdit()
        qtbot.addWidget(edit)
        original = "@[Орда](organization:1) атаковала @[Штормград](location:5)"
        edit.setContent(original)
        result = edit.getContent()
        assert "@[Орда](organization:1)" in result
        assert "@[Штормград](location:5)" in result

    def test_plain_text_setContent_getContent(self, qtbot):
        edit = MentionTextEdit()
        qtbot.addWidget(edit)
        edit.setContent("Просто текст")
        result = edit.getContent()
        assert result == "Просто текст"


# ── MentionTextEdit ───────────────────────────────────────────────────────


class TestMentionTextEdit:
    def test_creates(self, qtbot):
        edit = MentionTextEdit()
        qtbot.addWidget(edit)
        assert edit is not None

    def test_setContent_plain(self, qtbot):
        edit = MentionTextEdit()
        qtbot.addWidget(edit)
        edit.setContent("Просто текст")
        assert "Просто текст" in edit.toPlainText()

    def test_setContent_with_mention_renders_name(self, qtbot):
        edit = MentionTextEdit()
        qtbot.addWidget(edit)
        edit.setContent("Текст @[Персонаж](character:1) ещё")
        plain = edit.toPlainText()
        # The plain text should contain the entity name without markers
        assert "Персонаж" in plain
        assert "@[" not in plain

    def test_getContent_preserves_mentions(self, qtbot):
        edit = MentionTextEdit()
        qtbot.addWidget(edit)
        edit.setContent("Перед @[Локация](location:5) после")
        content = edit.getContent()
        assert "@[Локация](location:5)" in content

    def test_mention_clicked_signal(self, qtbot):
        edit = MentionTextEdit()
        qtbot.addWidget(edit)
        # Emitting manually for signal test
        with qtbot.waitSignal(edit.mention_clicked, timeout=1000):
            edit.mention_clicked.emit("character", 42)

    def test_show_mention_results_hides_on_empty(self, qtbot):
        edit = MentionTextEdit()
        qtbot.addWidget(edit)
        edit._mention_start = 5
        edit.show_mention_results([])
        assert not edit._popup.isVisible()

    def test_get_mention_edits_event_dialog(self, qtbot):
        """EventDialog.get_mention_edits returns MentionTextEdit instances."""
        from unittest.mock import MagicMock
        from app.presentation.views.event_dialog import EventDialog

        vm = MagicMock()
        vm.is_valid = False
        d = EventDialog(vm)
        qtbot.addWidget(d)
        edits = d.get_mention_edits()
        assert len(edits) == 2
        for e in edits:
            assert isinstance(e, MentionTextEdit)

    def test_get_mention_edits_entity_card_dialog_character(self, qtbot):
        """EntityCardDialog for character has 4 MentionTextEdit fields."""
        from app.presentation.views.entity_card_dialog import EntityCardDialog

        d = EntityCardDialog(None, entity_type="character")
        qtbot.addWidget(d)
        edits = d.get_mention_edits()
        # character: characteristics, backstory, personality, tasks
        assert len(edits) == 4
        for e in edits:
            assert isinstance(e, MentionTextEdit)

    def test_get_mention_edits_entity_card_dialog_item(self, qtbot):
        """EntityCardDialog for item has 2 MentionTextEdit fields."""
        from app.presentation.views.entity_card_dialog import EntityCardDialog

        d = EntityCardDialog(None, entity_type="item")
        qtbot.addWidget(d)
        edits = d.get_mention_edits()
        # item: characteristics, backstory
        assert len(edits) == 2


# ── MentionPopup ──────────────────────────────────────────────────────────


class TestMentionPopup:
    def test_creates(self, qtbot):
        popup = _MentionPopup()
        qtbot.addWidget(popup)
        assert popup is not None

    def test_show_results_populates_list(self, qtbot):
        popup = _MentionPopup()
        qtbot.addWidget(popup)
        results = [
            {"type": "character", "id": 1, "name": "Артас"},
            {"type": "location", "id": 2, "name": "Штормград"},
        ]
        from PySide6.QtCore import QPoint
        popup.show_results(results, QPoint(100, 100))
        assert popup._list.count() == 2

    def test_show_results_empty_hides(self, qtbot):
        popup = _MentionPopup()
        qtbot.addWidget(popup)
        from PySide6.QtCore import QPoint
        popup.show_results([], QPoint(100, 100))
        assert not popup.isVisible()

    def test_select_next_prev(self, qtbot):
        popup = _MentionPopup()
        qtbot.addWidget(popup)
        results = [
            {"type": "character", "id": 1, "name": "A"},
            {"type": "character", "id": 2, "name": "B"},
            {"type": "character", "id": 3, "name": "C"},
        ]
        from PySide6.QtCore import QPoint
        popup.show_results(results, QPoint(100, 100))
        assert popup._list.currentRow() == 0
        popup.select_next()
        assert popup._list.currentRow() == 1
        popup.select_next()
        assert popup._list.currentRow() == 2
        popup.select_next()
        assert popup._list.currentRow() == 2  # stays at last
        popup.select_prev()
        assert popup._list.currentRow() == 1
        popup.select_prev()
        assert popup._list.currentRow() == 0
        popup.select_prev()
        assert popup._list.currentRow() == 0  # stays at first


# ── Mention typing (keyboard) ─────────────────────────────────────────────


def _key(qtbot, edit, text=None, key=None, modifiers=Qt.KeyboardModifier.NoModifier):
    """Send a crafted QKeyEvent directly (deterministic, no keyboard layout)."""
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent

    k = key if key is not None else Qt.Key.Key_A
    return QKeyEvent(QEvent.Type.KeyPress, k, modifiers, text if text is not None else "")


class TestMentionTyping:
    def test_at_key_starts_mention_mode(self, qtbot):
        edit = MentionTextEdit()
        qtbot.addWidget(edit)
        ev = _key(qtbot, edit, text="@", modifiers=Qt.KeyboardModifier.ShiftModifier)
        edit.keyPressEvent(ev)
        assert edit.toPlainText() == "@"
        assert edit._mention_start == 1

    def test_typing_two_chars_emits_search_request(self, qtbot):
        edit = MentionTextEdit()
        qtbot.addWidget(edit)
        queries = []
        edit.mention_search_requested.connect(queries.append)
        edit.keyPressEvent(_key(qtbot, edit, text="@", modifiers=Qt.KeyboardModifier.ShiftModifier))
        edit.keyPressEvent(_key(qtbot, edit, text="a"))
        # one char after @ — no search yet
        assert queries == []
        edit.keyPressEvent(_key(qtbot, edit, text="b"))
        assert queries == ["ab"]

    def test_single_char_does_not_emit(self, qtbot):
        edit = MentionTextEdit()
        qtbot.addWidget(edit)
        queries = []
        edit.mention_search_requested.connect(queries.append)
        edit.keyPressEvent(_key(qtbot, edit, text="@", modifiers=Qt.KeyboardModifier.ShiftModifier))
        edit.keyPressEvent(_key(qtbot, edit, text="a"))
        assert queries == []
        assert not edit._popup.isVisible()

    def test_space_cancels_mention_mode_and_inserts_space(self, qtbot):
        edit = MentionTextEdit()
        qtbot.addWidget(edit)
        edit.keyPressEvent(_key(qtbot, edit, text="@", modifiers=Qt.KeyboardModifier.ShiftModifier))
        edit.keyPressEvent(_key(qtbot, edit, key=Qt.Key.Key_Space, text=" "))
        assert edit._mention_start == -1
        assert edit.toPlainText() == "@ "
        assert not edit._popup.isVisible()

    def test_escape_cancels_mention_mode(self, qtbot):
        edit = MentionTextEdit()
        qtbot.addWidget(edit)
        edit.keyPressEvent(_key(qtbot, edit, text="@", modifiers=Qt.KeyboardModifier.ShiftModifier))
        edit.keyPressEvent(_key(qtbot, edit, key=Qt.Key.Key_Escape))
        assert edit._mention_start == -1
        assert not edit._popup.isVisible()

    def test_backspace_past_at_sign_cancels(self, qtbot):
        edit = MentionTextEdit()
        qtbot.addWidget(edit)
        edit.keyPressEvent(_key(qtbot, edit, text="@", modifiers=Qt.KeyboardModifier.ShiftModifier))
        edit.keyPressEvent(_key(qtbot, edit, text="a"))
        # backspace 'a' — still in mode, no search (empty query)
        edit.keyPressEvent(_key(qtbot, edit, key=Qt.Key.Key_Backspace))
        assert edit._mention_start == 1
        # backspace '@' — cancels mention mode
        edit.keyPressEvent(_key(qtbot, edit, key=Qt.Key.Key_Backspace))
        assert edit._mention_start == -1
        assert edit.toPlainText() == ""

    def test_check_query_out_of_range_cancels(self, qtbot):
        edit = MentionTextEdit()
        qtbot.addWidget(edit)
        edit.setPlainText("x")
        cur = edit.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        edit.setTextCursor(cur)
        edit._mention_start = 99  # stale position past end of text
        edit._check_mention_query()
        assert edit._mention_start == -1


# ── Popup display and selection ───────────────────────────────────────────

_RESULTS = [
    {"type": "character", "id": 7, "name": "Артас"},
    {"type": "item", "id": 8, "name": "Меч"},
    {"type": "location", "id": 9, "name": "Штормград"},
]


class TestPopupDisplayAndSelection:
    def _show_popup(self, qtbot, edit, results=_RESULTS):
        edit._mention_start = 1
        edit.show_mention_results(results)
        assert edit._popup.isVisible()
        assert edit._popup._list.count() == min(len(results), 15)
        assert edit._popup._list.currentRow() == 0

    def test_show_results_displays_popup_with_icons(self, qtbot):
        edit = MentionTextEdit()
        qtbot.addWidget(edit)
        self._show_popup(qtbot, edit)
        # First item text includes the type icon + name
        first = edit._popup._list.item(0).text()
        assert "Артас" in first

    def test_show_results_more_than_15_are_truncated(self, qtbot):
        edit = MentionTextEdit()
        qtbot.addWidget(edit)
        many = [{"type": "item", "id": i, "name": f"I{i}"} for i in range(20)]
        self._show_popup(qtbot, edit, many)
        assert edit._popup._list.count() == 15

    def test_show_results_without_mention_mode_hides(self, qtbot):
        edit = MentionTextEdit()
        qtbot.addWidget(edit)
        edit._mention_start = -1
        edit.show_mention_results(_RESULTS)
        assert not edit._popup.isVisible()

    def test_show_results_empty_hides(self, qtbot):
        edit = MentionTextEdit()
        qtbot.addWidget(edit)
        edit._mention_start = 1
        edit.show_mention_results([])
        assert not edit._popup.isVisible()

    def test_enter_inserts_selected_mention(self, qtbot):
        edit = MentionTextEdit()
        qtbot.addWidget(edit)
        # Simulate "@ar" typed: text present, cursor at end, mention mode on.
        edit.setPlainText("@ar")
        cur = edit.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        edit.setTextCursor(cur)
        self._show_popup(qtbot, edit)
        # Navigate to second item and confirm with Enter.
        with qtbot.waitSignal(edit._popup.item_selected, timeout=1000):
            edit.keyPressEvent(_key(qtbot, edit, key=Qt.Key.Key_Down))
            edit.keyPressEvent(_key(qtbot, edit, key=Qt.Key.Key_Return))
        plain = edit.toPlainText()
        assert "@" not in plain
        assert "Меч" in plain
        assert edit._mention_start == -1
        assert not edit._popup.isVisible()
        # Roundtrip back to storage format
        assert edit.getContent().startswith("@[Меч](item:8)")

    def test_click_selects_item(self, qtbot):
        edit = MentionTextEdit()
        qtbot.addWidget(edit)
        edit.setPlainText("@ar")
        cur = edit.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        edit.setTextCursor(cur)
        self._show_popup(qtbot, edit)
        with qtbot.waitSignal(edit._popup.item_selected, timeout=1000):
            edit._popup._list.item(0).setSelected(True)
            edit._popup._on_click(edit._popup._list.item(0))
        assert edit.getContent().startswith("@[Артас](character:7)")

    def test_down_up_navigation_with_popup_visible(self, qtbot):
        edit = MentionTextEdit()
        qtbot.addWidget(edit)
        edit.setPlainText("@ar")
        self._show_popup(qtbot, edit)
        edit.keyPressEvent(_key(qtbot, edit, key=Qt.Key.Key_Down))
        assert edit._popup._list.currentRow() == 1
        edit.keyPressEvent(_key(qtbot, edit, key=Qt.Key.Key_Up))
        assert edit._popup._list.currentRow() == 0
        edit.keyPressEvent(_key(qtbot, edit, key=Qt.Key.Key_Down))
        edit.keyPressEvent(_key(qtbot, edit, key=Qt.Key.Key_Up))
        edit.keyPressEvent(_key(qtbot, edit, key=Qt.Key.Key_Up))  # clamped at 0
        assert edit._popup._list.currentRow() == 0

    def test_escape_hides_popup(self, qtbot):
        edit = MentionTextEdit()
        qtbot.addWidget(edit)
        edit.setPlainText("@ar")
        self._show_popup(qtbot, edit)
        edit.keyPressEvent(_key(qtbot, edit, key=Qt.Key.Key_Escape))
        assert not edit._popup.isVisible()
        assert edit._mention_start == -1

    def test_insert_mention_clamps_negative_at_pos(self, qtbot):
        edit = MentionTextEdit()
        qtbot.addWidget(edit)
        edit.setPlainText("abc")
        cur = edit.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        edit.setTextCursor(cur)
        edit._mention_start = 0  # at_pos would be -1 → clamped to 0
        edit._insert_mention({"type": "item", "id": 1, "name": "Товар"})
        assert "Товар" in edit.toPlainText()
        assert edit._mention_start == -1


# ── Link click / cursor (mouse) ───────────────────────────────────────────


class TestLinkClick:
    def _mouse_event(self, type_, button, buttons):
        from PySide6.QtCore import QPointF

        return QMouseEvent(
            type_, QPointF(1, 1), button, buttons, Qt.KeyboardModifier.NoModifier,
        )

    def test_click_on_mention_link_emits(self, qtbot, mocker):
        edit = MentionTextEdit()
        qtbot.addWidget(edit)
        edit.setContent("Привет @[Артас](character:42)")
        received = []
        edit.mention_clicked.connect(lambda t, i: received.append((t, i)))
        mocker.patch.object(MentionTextEdit, "anchorAt", return_value="mention://character/42")
        edit.mousePressEvent(
            self._mouse_event(QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
        )
        assert received == [("character", 42)]

    def test_click_on_non_numeric_id_falls_through(self, qtbot, mocker):
        edit = MentionTextEdit()
        qtbot.addWidget(edit)
        received = []
        edit.mention_clicked.connect(lambda t, i: received.append((t, i)))
        mocker.patch.object(MentionTextEdit, "anchorAt", return_value="mention://character/abc")
        edit.mousePressEvent(
            self._mouse_event(QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
        )
        assert received == []

    def test_click_outside_mention_falls_through(self, qtbot, mocker):
        edit = MentionTextEdit()
        qtbot.addWidget(edit)
        received = []
        edit.mention_clicked.connect(lambda t, i: received.append((t, i)))
        mocker.patch.object(MentionTextEdit, "anchorAt", return_value="")
        edit.mousePressEvent(
            self._mouse_event(QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
        )
        assert received == []

    def test_right_click_never_emits(self, qtbot, mocker):
        edit = MentionTextEdit()
        qtbot.addWidget(edit)
        received = []
        edit.mention_clicked.connect(lambda t, i: received.append((t, i)))
        mocker.patch.object(MentionTextEdit, "anchorAt", return_value="mention://character/42")
        edit.mousePressEvent(
            self._mouse_event(QEvent.Type.MouseButtonPress, Qt.MouseButton.RightButton, Qt.MouseButton.RightButton)
        )
        assert received == []

    def test_mouse_move_over_mention_changes_cursor(self, qtbot, mocker):
        edit = MentionTextEdit()
        qtbot.addWidget(edit)
        mocker.patch.object(MentionTextEdit, "anchorAt", return_value="mention://character/42")
        edit.mouseMoveEvent(self._mouse_event(QEvent.Type.MouseMove, Qt.MouseButton.NoButton, Qt.MouseButton.NoButton))
        assert edit.viewport().cursor().shape() == Qt.CursorShape.PointingHandCursor
        mocker.patch.object(MentionTextEdit, "anchorAt", return_value="")
        edit.mouseMoveEvent(self._mouse_event(QEvent.Type.MouseMove, Qt.MouseButton.NoButton, Qt.MouseButton.NoButton))
        assert edit.viewport().cursor().shape() == Qt.CursorShape.IBeamCursor


# ── Remaining branches: multi-block docs, degenerate anchors, plain keys ──

class TestMentionEdgeBranches:
    def test_multi_block_document_joined_with_newline(self, qtbot):
        edit = MentionTextEdit()
        qtbot.addWidget(edit)
        edit.setHtml("<p>Первый блок</p><p>Второй блок</p>")
        assert edit.getContent() == "Первый блок\nВторой блок"

    def test_anchor_without_slash_renders_plain_text(self, qtbot):
        edit = MentionTextEdit()
        qtbot.addWidget(edit)
        edit.setHtml('<a href="mention://x">без пары</a>')
        assert edit.getContent() == "без пары"

    def test_key_press_outside_mention_mode_type(self, qtbot):
        """A normal keystroke outside mention mode just types (no mention state)."""
        edit = MentionTextEdit()
        qtbot.addWidget(edit)
        ev = _key(qtbot, edit, text="x")
        edit.keyPressEvent(ev)
        assert edit.toPlainText() == "x"
        assert edit._mention_start == -1
        assert not edit._popup.isVisible()

    def test_cursor_before_at_sign_cancels_mention_mode(self, qtbot):
        """pos <= mention_start - 1 (cursor back before the @) cancels the mode."""
        edit = MentionTextEdit()
        qtbot.addWidget(edit)
        edit.keyPressEvent(_key(qtbot, edit, text="@", modifiers=Qt.KeyboardModifier.ShiftModifier))
        edit.keyPressEvent(_key(qtbot, edit, text="a"))
        assert edit._mention_start == 1
        # Move the cursor to the very start (before '@') while still in mode
        cur = edit.textCursor()
        cur.setPosition(0)
        edit.setTextCursor(cur)
        edit._check_mention_query()
        assert edit._mention_start == -1
        assert edit.toPlainText() == "@a"  # text untouched, only the mode cancelled
