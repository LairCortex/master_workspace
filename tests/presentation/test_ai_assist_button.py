"""Tests for AiAssistButton — states, messages, progress."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLineEdit, QMessageBox, QTextEdit

from app.presentation.views.ai_assist_button import (
    AI_STATE_ACTIVE,
    AI_STATE_DISABLED,
    AiAssistButton,
    ai_state_is,
)


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


@pytest.fixture
def runtime(tmp_path):
    from app.infrastructure.ui_prefs.config import UiPrefsManager
    from app.presentation.theme import ThemeRuntime
    from app.presentation.theme.compiler import tokens_file_path

    return ThemeRuntime(
        prefs=UiPrefsManager(tmp_path / "ui.json"), tokens_path=tokens_file_path()
    )


def test_default_state_is_not_configured(btn_on_text):
    assert btn_on_text._llm_status == "not_configured"


def test_button_disabled_when_not_configured(btn_on_text):
    btn_on_text.update_llm_state("not_configured", False)
    # Off-skin (no theme): state marker only, no invented colors (D7).
    assert "rgba" not in btn_on_text.styleSheet()


def test_button_disabled_when_no_world_prompt(btn_on_text):
    btn_on_text.update_llm_state("ready", False)
    assert "rgba" not in btn_on_text.styleSheet()


def test_button_enabled_when_ready(btn_on_text):
    btn_on_text.update_llm_state("ready", True)
    assert "rgba" not in btn_on_text.styleSheet()


def test_ai_styles_are_accent_and_muted_derivatives(text_edit, runtime):
    # W2b D3: ACTIVE = accent alphas from the tokens, DISABLED = muted alphas.
    from app.presentation.theme.compiler import accent_rgba, load_tokens, tokens_file_path

    tokens = load_tokens(tokens_file_path())
    accent_rgb = accent_rgba(tokens, runtime.theme, 0.25)
    muted = QColor(tokens["color.fg.muted"][runtime.theme])
    btn = AiAssistButton(text_edit, "character", "backstory", "П", theme=runtime)
    btn.update_llm_state("ready", True)
    assert accent_rgb in btn.styleSheet()
    btn.update_llm_state("not_configured", False)
    assert f"rgba({muted.red()}, {muted.green()}, {muted.blue()}, 0.15)" in btn.styleSheet()
    # The fixed blue/fixed grey literals are gone for good.
    assert "91,155,213" not in btn.styleSheet()
    assert "128,128,128" not in btn.styleSheet()


def test_ai_styles_rebuild_on_live_theme_switch(text_edit, runtime):
    from app.presentation.theme.compiler import accent_rgba, load_tokens, tokens_file_path

    tokens = load_tokens(tokens_file_path())
    btn = AiAssistButton(text_edit, "character", "backstory", "П", theme=runtime)
    btn.update_llm_state("ready", True)
    before = btn.styleSheet()
    assert runtime.set_theme("light")
    assert accent_rgba(tokens, "light", 0.25) in btn.styleSheet()
    assert btn.styleSheet() != before


def test_ai_state_marker_is_read_by_the_marker_helper(btn_on_text):
    # The e2e selector for the AI button is this marker, read through
    # ai_state_is (Qt's marker check; W2a D5) — never the rgba colors of the
    # stylesheet, and a widget without the marker must read as False.
    btn_on_text.update_llm_state("not_configured", False)
    assert ai_state_is(btn_on_text, AI_STATE_DISABLED)
    assert not ai_state_is(btn_on_text, AI_STATE_ACTIVE)
    btn_on_text.update_llm_state("ready", True)
    assert ai_state_is(btn_on_text, AI_STATE_ACTIVE)
    assert not ai_state_is(btn_on_text, AI_STATE_DISABLED)
    assert not ai_state_is(QLineEdit(), AI_STATE_DISABLED)


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


def test_button_disabled_in_place_during_generation(btn_on_text):
    """The button is layout-managed: it is disabled, not hidden, while generating."""
    btn_on_text.set_generating(True)
    assert not btn_on_text.isEnabled()
    btn_on_text.set_generating(False)
    assert btn_on_text.isEnabled()


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


# ── _get_current_text branches and click-while-generating ──────────────────


def _plain_text_edit(qtbot):
    w = QTextEdit()
    qtbot.addWidget(w)
    w.show()
    return w


def test_get_current_text_from_mention_edit_uses_getcontent(qtbot):
    """MentionTextEdit targets report their storage format (markers preserved)."""
    from app.presentation.views.mention_text_edit import MentionTextEdit

    edit = MentionTextEdit()
    qtbot.addWidget(edit)
    edit.show()
    btn = AiAssistButton(edit, "event", "backstory", "Предыстория")
    edit.setContent("Был @[Артас](character:7) в деревне")
    assert btn._get_current_text() == "Был @[Артас](character:7) в деревне"


def test_get_current_text_plain_target_qtextedit(qtbot):
    edit = _plain_text_edit(qtbot)
    btn = AiAssistButton(edit, "item", "name", "Название")
    edit.setPlainText("Клинок")
    assert btn._get_current_text() == "Клинок"


def test_get_current_text_unknown_target_is_empty(qtbot):
    from PySide6.QtWidgets import QWidget

    target = QWidget()
    qtbot.addWidget(target)
    target.show()
    btn = AiAssistButton(target, "item", "name", "Название")
    assert btn._get_current_text() == ""


def test_current_text_is_sent_as_generation_context(qtbot, text_edit):
    btn_on_text = AiAssistButton(text_edit, "character", "backstory", "Предыстория")
    btn_on_text.update_llm_state("ready", True)
    text_edit.setPlainText("Контекст для генерации")
    emitted: list[tuple] = []
    btn_on_text.generate_requested.connect(lambda *args: emitted.append(args))
    btn_on_text._on_clicked()
    assert emitted[0][3] == "Контекст для генерации"


def test_click_while_generating_is_ignored(qtbot):
    edit = _plain_text_edit(qtbot)
    btn = AiAssistButton(edit, "event", "name", "Название")
    btn.update_llm_state("ready", True)
    btn.set_generating(True)
    emitted: list = []
    btn.generate_requested.connect(lambda *a: emitted.append(a))
    with patch.object(QMessageBox, "information") as mock_msg:
        btn._on_clicked()
    assert emitted == []
    mock_msg.assert_not_called()
    assert btn.is_generating
