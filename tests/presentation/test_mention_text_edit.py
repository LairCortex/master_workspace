"""Tests for MentionTextEdit — @mention widget."""
from __future__ import annotations

import pytest

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
