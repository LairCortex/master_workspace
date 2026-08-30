"""Tests for LlmSetupDialog — connection page, check, wizard navigation, save."""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import httpx
import pytest
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
)

from app.infrastructure.http import AppHttpClient
from app.infrastructure.llm.config import LlmConfig
from app.presentation.views.llm_setup_dialog import LlmSetupDialog

_DEFAULT_PROMPTS = {
    "event": {"name": "Evt name", "characteristics": "", "backstory": ""},
    "character": {"name": "Char name", "characteristics": "", "backstory": "", "personality": "", "tasks": ""},
}


def _ok_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": "ок"}}]})


def _error_response(status: int, message: str):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": message}})
    return handler


@pytest.fixture
async def make_dialog(qtbot):
    created: list[tuple[LlmSetupDialog, AppHttpClient]] = []

    def _make(handler=None, config: LlmConfig | None = None):
        if handler is None:
            handler = _ok_response
        transport = httpx.MockTransport(handler)
        holder = AppHttpClient(client=httpx.AsyncClient(transport=transport))
        dlg = LlmSetupDialog(
            config=config or LlmConfig("https://api.openai.com/v1", "gpt-4o-mini", "sk-123"),
            world_prompt="Test world",
            field_prompts=_DEFAULT_PROMPTS,
            http=holder,
        )
        qtbot.addWidget(dlg)
        created.append((dlg, holder))
        return dlg

    yield _make

    for _, holder in created:
        await holder.close()


@pytest.fixture
def dialog(make_dialog):
    return make_dialog()


# --- connection page ----------------------------------------------------------


def test_connection_page_first_with_prefilled_values(dialog):
    assert dialog._stack.currentIndex() == 0
    assert dialog._endpoint_edit.text() == "https://api.openai.com/v1"
    assert dialog._model_edit.text() == "gpt-4o-mini"
    assert dialog._key_edit.text() == "sk-123"


def test_key_field_is_masked(dialog):
    assert dialog._key_edit.echoMode() == QLineEdit.EchoMode.Password


def test_no_download_ui(dialog):
    assert dialog.findChildren(QProgressBar) == []
    assert dialog.findChildren(QPushButton, "Скачать модель") == []
    assert dialog.findChildren(QPushButton, "Удалить модель") == []


def test_endpoint_hint_mentions_format(dialog):
    full = " ".join(lbl.text() for lbl in dialog._connection_page.findChildren(QLabel) if lbl.text())
    assert "/v1" in full


# --- check connection -----------------------------------------------------------


def test_check_button_disabled_when_endpoint_empty(dialog):
    dialog._endpoint_edit.setText("")
    assert not dialog._check_btn.isEnabled()
    dialog._endpoint_edit.setText("https://api.openai.com/v1")
    assert dialog._check_btn.isEnabled()


def test_check_button_disabled_when_model_empty(dialog):
    dialog._model_edit.setText("")
    assert not dialog._check_btn.isEnabled()
    dialog._model_edit.setText("gpt-4o-mini")
    assert dialog._check_btn.isEnabled()


@pytest.mark.asyncio
async def test_check_success_shows_established(dialog):
    await dialog._on_check()
    assert "установлено" in dialog._check_label.text().lower()
    assert dialog._check_label.property("uiRole") == "status-ok"
    assert dialog._check_btn.isEnabled()


@pytest.mark.asyncio
async def test_check_401_shows_invalid_key(make_dialog):
    dlg = make_dialog(handler=_error_response(401, "Invalid API key"))
    await dlg._on_check()
    assert "неверный ключ" in dlg._check_label.text().lower()
    assert dlg._check_label.property("uiRole") == "status-error"
    assert dlg._check_btn.isEnabled()


@pytest.mark.asyncio
async def test_check_button_blocked_during_check(make_dialog):
    states: list[bool] = []
    btns: dict = {}

    def capturing(request: httpx.Request) -> httpx.Response:
        states.append(btns["btn"].isEnabled())
        return _ok_response(request)

    dlg = make_dialog(handler=capturing)
    btns["btn"] = dlg._check_btn
    await dlg._on_check()
    assert states == [False]
    assert dlg._check_btn.isEnabled()



@pytest.mark.asyncio
async def test_check_button_click_runs_check(dialog):
    """Qt signal -> async slot must be bridged into the event loop."""
    dialog._check_btn.click()
    for _ in range(200):
        await asyncio.sleep(0)
        if dialog._check_label.text():
            break
    assert "установлено" in dialog._check_label.text().lower()


# --- save -------------------------------------------------------------------------



def test_save_blocked_when_endpoint_empty(dialog):
    dialog._endpoint_edit.setText("")
    emitted = []
    dialog.saved.connect(lambda *args: emitted.append(args))
    with patch.object(QMessageBox, "warning") as mock_warning:
        dialog._on_save()
    mock_warning.assert_called_once()
    assert emitted == []
    assert not dialog.result()


def test_save_blocked_when_model_empty(dialog):
    dialog._model_edit.setText("")
    with patch.object(QMessageBox, "warning") as mock_warning:
        dialog._on_save()
    mock_warning.assert_called_once()
    assert not dialog.result()


def test_save_emits_config_and_prompts(dialog, qtbot):
    dialog._endpoint_edit.setText("http://localhost:11434/v1")
    dialog._model_edit.setText("llama3")
    dialog._key_edit.setText("")

    with qtbot.waitSignal(dialog.saved, timeout=1000) as blocker:
        dialog._on_save()

    config, world_prompt, field_prompts = blocker.args
    assert config == LlmConfig("http://localhost:11434/v1", "llama3", "")
    assert world_prompt == "Test world"
    assert field_prompts["event"]["name"] == "Evt name"


def test_dialog_not_accepted_until_save_finished(dialog):
    dialog._on_save()
    # save button is not disabled; dialog stays open until the async save completes
    assert dialog._saving
    assert dialog._save_btn.isEnabled()
    assert not dialog.result()
    dialog.finish_saving(True)
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_save_reentry_ignored_while_saving(dialog):
    counts = []
    dialog.saved.connect(lambda *a: counts.append(1))
    dialog._on_save()
    dialog._on_save()
    assert len(counts) == 1
    dialog.finish_saving(True)


def test_reject_blocked_while_saving(dialog):
    dialog._on_save()
    dialog.reject()
    assert not dialog.result()  # dialog stays open
    dialog.finish_saving(True)


def test_close_and_reject_blocked_while_saving(dialog):
    dialog._on_save()
    dialog.close()
    dialog.reject()
    assert not dialog.result()  # closing the dialog is blocked while saving
    dialog.finish_saving(True)
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_finish_saving_failure_shows_warning_and_keeps_open(dialog):
    dialog._on_save()
    with patch.object(QMessageBox, "warning") as mock_warning:
        dialog.finish_saving(False)
    mock_warning.assert_called_once()
    assert not dialog.result()
    assert not dialog._saving
    # save can be retried after a failed attempt
    dialog._on_save()
    dialog.finish_saving(True)


# --- wizard (unchanged parts) -------------------------------------------------------


def test_wizard_has_8_pages(dialog):
    assert dialog.page_count == 8


def test_navigation_back_forward(dialog):
    assert dialog._stack.currentIndex() == 0
    assert not dialog._back_btn.isEnabled()

    dialog._go_next()
    assert dialog._stack.currentIndex() == 1
    assert dialog._back_btn.isEnabled()

    dialog._go_back()
    assert dialog._stack.currentIndex() == 0

    for _ in range(10):
        dialog._go_next()
    assert dialog._stack.currentIndex() == 7


def test_save_btn_on_last_page(dialog):
    for _ in range(7):
        dialog._go_next()
    assert not dialog._save_btn.isHidden()
    assert dialog._next_btn.isHidden()


def test_world_prompt_saved_on_close(dialog):
    dialog._world_prompt_edit.setPlainText("New world prompt")
    emitted = []
    dialog.saved.connect(lambda c, wp, fp: emitted.append(wp))
    dialog._on_save()
    assert emitted == ["New world prompt"]


def test_field_prompts_pages(dialog):
    assert len(dialog._field_pages["event"].get_prompts()) == 3
    assert len(dialog._field_pages["character"].get_prompts()) == 5
    assert len(dialog._field_pages["item"].get_prompts()) == 3


def test_field_prompts_prefilled_on_reopen(dialog):
    assert dialog._field_pages["event"].get_prompts()["name"] == "Evt name"


def test_get_world_prompt(dialog):
    dialog._world_prompt_edit.setPlainText("My world")
    assert dialog.get_world_prompt() == "My world"


def test_get_field_prompts(dialog):
    result = dialog.get_field_prompts()
    for etype in ("event", "character", "item", "location", "organization"):
        assert etype in result


def test_warnings_mention_key_storage(dialog):
    for _ in range(7):
        dialog._go_next()
    full_text = " ".join(lbl.text() for lbl in dialog._warnings_page.findChildren(QLabel) if lbl.text())
    assert "llm_config.json" in full_text
