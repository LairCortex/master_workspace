"""Tests for EntityGenerateButton — state matrix: idle / not ready / cancelling / single in flight."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QMessageBox

from app.presentation.views.ai_assist_button import EntityGenerateButton


@pytest.fixture
def button(qtbot):
    b = EntityGenerateButton()
    qtbot.addWidget(b)
    b.show()
    return b


def _signals(button):
    requested: list[int] = []
    cancelled: list[int] = []
    button.batch_requested.connect(lambda: requested.append(1))
    button.batch_cancel_requested.connect(lambda: cancelled.append(1))
    return requested, cancelled


# ── idle, ready ───────────────────────────────────────────────────────────


def test_idle_ready_active_style_and_tooltip(button):
    button.update_llm_state("ready", True)
    assert button.text() == "\u2728"
    assert button.toolTip() == "Сгенерировать сущность (все поля)"
    assert "91,155,213" in button.styleSheet()
    assert button.isEnabled()
    assert not button.is_cancelling


def test_idle_ready_click_emits_batch_requested(button):
    button.update_llm_state("ready", True)
    requested, cancelled = _signals(button)
    button.click()
    assert requested == [1]
    assert cancelled == []


# ── idle, not ready ───────────────────────────────────────────────────────


def test_not_configured_uses_disabled_style_but_stays_clickable(button):
    button.update_llm_state("not_configured", False)
    assert "128,128,128" in button.styleSheet()
    assert button.isEnabled()
    assert button.text() == "\u2728"


def test_ready_without_world_prompt_uses_disabled_style(button):
    button.update_llm_state("ready", False)
    assert "128,128,128" in button.styleSheet()
    assert button.isEnabled()


def test_click_when_not_configured_shows_same_hint_as_field_buttons(button):
    button.update_llm_state("not_configured", True)
    requested, cancelled = _signals(button)
    with patch.object(QMessageBox, "information") as mock_msg:
        button.click()
    assert requested == []
    assert cancelled == []
    mock_msg.assert_called_once()
    assert "не настроен" in mock_msg.call_args[0][2]
    assert "Настройка LLM" in mock_msg.call_args[0][2]


def test_click_when_no_world_prompt_shows_world_hint(button):
    button.update_llm_state("ready", False)
    requested, cancelled = _signals(button)
    with patch.object(QMessageBox, "information") as mock_msg:
        button.click()
    assert requested == []
    assert cancelled == []
    mock_msg.assert_called_once()
    assert "промт мира" in mock_msg.call_args[0][2]


# ── cancelling (wave in flight) ───────────────────────────────────────────


def test_wave_running_shows_cancel_state(button):
    button.update_llm_state("ready", True)
    button.set_wave_running(True)
    assert button.is_cancelling
    assert button.text() == "\u23F9"
    assert button.toolTip() == "Отменить генерацию"
    assert button.isEnabled()


def test_wave_running_click_emits_cancel_not_request(button):
    button.update_llm_state("ready", True)
    button.set_wave_running(True)
    requested, cancelled = _signals(button)
    button.click()
    assert requested == []
    assert cancelled == [1]


def test_wave_ended_returns_to_idle(button):
    button.update_llm_state("ready", True)
    button.set_wave_running(True)
    button.set_wave_running(False)
    assert not button.is_cancelling
    assert button.text() == "\u2728"
    assert button.toolTip() == "Сгенерировать сущность (все поля)"
    assert button.isEnabled()


# ── single field generation in flight ─────────────────────────────────────


def test_single_in_flight_is_truly_disabled(button):
    button.update_llm_state("ready", True)
    button.set_single_in_flight(True)
    assert not button.isEnabled()


def test_single_in_flight_emits_no_signals(button):
    button.update_llm_state("ready", True)
    button.set_single_in_flight(True)
    requested, cancelled = _signals(button)
    button.click()
    button._on_clicked()
    assert requested == []
    assert cancelled == []


def test_single_in_flight_ended_reenables_button(button):
    button.update_llm_state("ready", True)
    button.set_single_in_flight(True)
    button.set_single_in_flight(False)
    assert button.isEnabled()
    assert button.text() == "\u2728"
