"""Tests for AiAssistButton — states, messages, progress."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QLineEdit, QMessageBox, QTextEdit

from app.presentation.views.ai_assist_button import AiAssistButton


@pytest.fixture
def text_edit(qtbot):
    w = QTextEdit()
    qtbot.addWidget(w)
    w.show()
    return w


@pytest.fixture
def line_edit(qtbot):
    w = QLineEdit()
    qtbot.addWidget(w)
    w.show()
    return w


@pytest.fixture
def btn_on_text(text_edit):
    return AiAssistButton(text_edit, "character", "backstory", "Предыстория")


@pytest.fixture
def btn_on_line(line_edit):
    return AiAssistButton(line_edit, "event", "name", "Название")


def test_default_state_is_not_configured(btn_on_text):
    assert btn_on_text._llm_status == "not_configured"


def test_button_disabled_when_not_configured(btn_on_text):
    btn_on_text.update_llm_state("not_configured", False)
    assert "128,128,128" in btn_on_text.styleSheet()


def test_button_disabled_when_no_world_prompt(btn_on_text):
    btn_on_text.update_llm_state("ready", False)
    assert "128,128,128" in btn_on_text.styleSheet()


def test_button_enabled_when_ready(btn_on_text):
    btn_on_text.update_llm_state("ready", True)
    assert "91,155,213" in btn_on_text.styleSheet()


def test_click_when_not_configured_mentions_setup(btn_on_text):
    btn_on_text.update_llm_state("not_configured", False)
    with patch.object(QMessageBox, "information") as mock_msg:
        btn_on_text._on_clicked()
        mock_msg.assert_called_once()
        text = mock_msg.call_args[0][2]
        assert "Настройка LLM" in text
        assert "не настроен" in text


def test_click_when_no_world_prompt_shows_message(btn_on_text):
    btn_on_text.update_llm_state("ready", False)
    with patch.object(QMessageBox, "information") as mock_msg:
        btn_on_text._on_clicked()
        mock_msg.assert_called_once()
        assert "промт мира" in mock_msg.call_args[0][2]


def test_click_when_ready_emits_generate(btn_on_text, text_edit):
    btn_on_text.update_llm_state("ready", True)
    text_edit.setPlainText("Герой родился в деревне")

    emitted: list[tuple] = []
    btn_on_text.generate_requested.connect(lambda *args: emitted.append(args))
    btn_on_text._on_clicked()

    assert len(emitted) == 1
    et, fn, fl, ct = emitted[0]
    assert et == "character"
    assert fn == "backstory"
    assert fl == "Предыстория"
    assert "Герой родился" in ct


def test_field_disabled_during_generation(btn_on_text, text_edit):
    btn_on_text.set_generating(True)
    assert text_edit.isReadOnly()
    assert btn_on_text.is_generating


def test_field_reenabled_after_generation(btn_on_text, text_edit):
    btn_on_text.set_generating(True)
    btn_on_text.set_generating(False)
    assert not text_edit.isReadOnly()
    assert not btn_on_text.is_generating


def test_set_result_text_on_textedit(btn_on_text, text_edit):
    btn_on_text.set_generating(True)
    btn_on_text.set_result_text("AI generated text")
    assert text_edit.toPlainText() == "AI generated text"
    assert not text_edit.isReadOnly()


def test_set_result_text_on_lineedit(btn_on_line, line_edit):
    btn_on_line.set_generating(True)
    btn_on_line.set_result_text("New Name")
    assert line_edit.text() == "New Name"
    assert not line_edit.isReadOnly()


def test_progress_bar_shown_during_generation(btn_on_text):
    assert not btn_on_text._progress.isVisible()
    btn_on_text.set_generating(True)
    assert btn_on_text._progress.isVisible()
    btn_on_text.set_generating(False)
    assert not btn_on_text._progress.isVisible()


def test_properties(btn_on_text):
    assert btn_on_text.entity_type == "character"
    assert btn_on_text.field_name == "backstory"
    assert btn_on_text.field_label == "Предыстория"
