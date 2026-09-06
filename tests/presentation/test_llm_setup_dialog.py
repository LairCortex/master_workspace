"""LlmSetupDialog — the QML-island facade: connection, check, wizard, save.

The dialog is a QDialog frame around one QQuickWidget island (R3 pack 2), so
the tests address state through the island's view model and the facade's
public API; the async HTTP check and the save lifecycle stay on the facade.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from PySide6.QtQml import QQmlEngine
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QStackedWidget,
    QTextEdit,
)

from app.infrastructure.http import AppHttpClient
from app.infrastructure.llm.config import LlmConfig
from app.presentation.qml.engine import qml_engine
from app.presentation.views import llm_setup_dialog as dialog_module
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


# --- island wiring ------------------------------------------------------------


def test_island_runs_on_the_shared_engine_with_isolated_context(dialog, qapp):
    assert QQmlEngine.contextForObject(dialog.quick.rootObject()).engine() is qml_engine()
    assert len(qapp.findChildren(QQmlEngine)) == 1
    context = dialog._context
    assert context.contextProperty("llmSetupVm") is dialog.vm
    assert context.contextProperty("islandPalette") is not None
    assert dialog.quick.rootContext().contextProperty("llmSetupVm") is None
    # Services never reach QML (spec qml-shell «Контекст LLM изолирован»).
    for forbidden in ("http", "llmService", "provider", "vm"):
        assert context.contextProperty(forbidden) is None


def test_widgets_layout_is_gone(dialog):
    assert dialog.findChildren(QStackedWidget) == []
    assert dialog.findChildren(QLineEdit) == []
    assert dialog.findChildren(QTextEdit) == []
    assert dialog.findChildren(QProgressBar) == []
    assert not dialog.findChildren(QFormLayout)
    source = Path(dialog_module.__file__).read_text(encoding="utf-8")
    for gone in ("QFormLayout", "QStackedWidget", "QLineEdit", "QTextEdit", "_FieldPromptsPage"):
        assert gone not in source, gone


# --- connection page ----------------------------------------------------------


def test_connection_page_first_with_prefilled_values(dialog):
    assert dialog.vm.currentPage == 0
    assert dialog.vm.endpoint == "https://api.openai.com/v1"
    assert dialog.vm.model == "gpt-4o-mini"
    assert dialog.vm.apiKey == "sk-123"
    assert dialog.get_connection() == LlmConfig("https://api.openai.com/v1", "gpt-4o-mini", "sk-123")


def test_missing_config_falls_back_to_empty_connection(make_dialog):
    dlg = make_dialog(config=LlmConfig())
    assert dlg.get_connection() == LlmConfig("", "", "")


# --- check connection -----------------------------------------------------------


def test_check_disabled_when_endpoint_empty(dialog):
    dialog.vm.endpoint = ""
    assert dialog.vm.checkEnabled is False
    dialog.vm.endpoint = "https://api.openai.com/v1"
    assert dialog.vm.checkEnabled is True


def test_check_disabled_when_model_empty(dialog):
    dialog.vm.model = ""
    assert dialog.vm.checkEnabled is False
    dialog.vm.model = "gpt-4o-mini"
    assert dialog.vm.checkEnabled is True


async def test_check_success_shows_established(dialog):
    await dialog._on_check()
    assert "установлено" in dialog.vm.checkText.lower()
    assert dialog.vm.checkStatus == "ok"
    assert dialog.vm.checkEnabled is True


async def test_check_401_shows_invalid_key(make_dialog):
    dlg = make_dialog(handler=_error_response(401, "Invalid API key"))
    await dlg._on_check()
    assert "неверный ключ" in dlg.vm.checkText.lower()
    assert dlg.vm.checkStatus == "error"
    assert dlg.vm.checkEnabled is True


async def test_check_incomplete_connection_makes_no_request(make_dialog):
    requests: list[httpx.Request] = []

    def counting(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _ok_response(request)

    dlg = make_dialog(handler=counting)
    dlg.vm.model = ""
    await dlg._on_check()
    assert requests == []
    assert dlg.vm.checkText == ""


async def test_check_blocked_while_running(make_dialog):
    states: list[bool] = []
    holder: dict = {}

    def capturing(request: httpx.Request) -> httpx.Response:
        states.append(holder["vm"].checkEnabled)
        return _ok_response(request)

    dlg = make_dialog(handler=capturing)
    holder["vm"] = dlg.vm
    await dlg._on_check()
    assert states == [False]
    assert dlg.vm.checkEnabled is True


async def test_check_request_from_island_runs_the_facade_check(dialog):
    """QML emits a sync request; the coroutine is scheduled by the facade."""
    dialog.vm.requestCheck()
    for _ in range(200):
        await asyncio.sleep(0)
        if dialog.vm.checkText and dialog.vm.checkStatus:
            break
    assert "установлено" in dialog.vm.checkText.lower()


# --- save -------------------------------------------------------------------------


def test_save_blocked_when_endpoint_empty(dialog):
    dialog.vm.endpoint = ""
    emitted = []
    dialog.saved.connect(lambda *args: emitted.append(args))
    with patch.object(QMessageBox, "warning") as mock_warning:
        dialog._on_save()
    mock_warning.assert_called_once()
    assert emitted == []
    assert not dialog.result()


def test_save_blocked_when_model_empty(dialog):
    dialog.vm.model = ""
    with patch.object(QMessageBox, "warning") as mock_warning:
        dialog._on_save()
    mock_warning.assert_called_once()
    assert not dialog.result()


def test_save_emits_config_and_prompts(dialog, qtbot):
    dialog.vm.endpoint = "http://localhost:11434/v1"
    dialog.vm.model = "llama3"
    dialog.vm.apiKey = ""

    with qtbot.waitSignal(dialog.saved, timeout=1000) as blocker:
        dialog.vm.requestSave()

    config, world_prompt, field_prompts = blocker.args
    assert config == LlmConfig("http://localhost:11434/v1", "llama3", "")
    assert world_prompt == "Test world"
    assert field_prompts["event"]["name"] == "Evt name"


def test_dialog_not_accepted_until_save_finished(dialog):
    dialog._on_save()
    assert dialog.vm.saving is True
    assert dialog.vm.saveEnabled is False
    assert not dialog.result()
    dialog.finish_saving(True)
    assert dialog.vm.saving is False
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_save_reentry_ignored_while_saving(dialog):
    counts = []
    dialog.saved.connect(lambda *a: counts.append(1))
    dialog._on_save()
    dialog._on_save()
    dialog.vm.requestSave()
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


def test_close_allowed_when_not_saving(dialog):
    dialog.close()
    assert not dialog.isVisible()


def test_finish_saving_failure_shows_warning_and_keeps_open(dialog):
    dialog._on_save()
    with patch.object(QMessageBox, "warning") as mock_warning:
        dialog.finish_saving(False)
    mock_warning.assert_called_once()
    assert not dialog.result()
    assert dialog.vm.saving is False
    # save can be retried after a failed attempt
    dialog._on_save()
    dialog.finish_saving(True)


# --- wizard -------------------------------------------------------------------------


def test_wizard_has_8_pages(dialog):
    assert dialog.page_count == 8


def test_navigation_back_forward(dialog):
    assert dialog.vm.currentPage == 0
    assert dialog.vm.backEnabled is False

    dialog.vm.goNext()
    assert dialog.vm.currentPage == 1
    assert dialog.vm.backEnabled is True

    dialog.vm.goBack()
    assert dialog.vm.currentPage == 0

    for _ in range(10):
        dialog.vm.goNext()
    assert dialog.vm.currentPage == 7


def test_save_shown_only_on_last_page(dialog):
    assert dialog.vm.saveVisible is False
    assert dialog.vm.nextVisible is True
    for _ in range(7):
        dialog.vm.goNext()
    assert dialog.vm.saveVisible is True
    assert dialog.vm.nextVisible is False


def test_world_prompt_saved_on_close(dialog):
    dialog.vm.worldPrompt = "New world prompt"
    emitted = []
    dialog.saved.connect(lambda c, wp, fp: emitted.append(wp))
    dialog._on_save()
    assert emitted == ["New world prompt"]


def test_field_prompts_pages(dialog):
    prompts = dialog.get_field_prompts()
    assert len(prompts["event"]) == 3
    assert len(prompts["character"]) == 5
    assert len(prompts["item"]) == 3


def test_field_prompts_prefilled_on_reopen(dialog):
    assert dialog.get_field_prompts()["event"]["name"] == "Evt name"


def test_get_world_prompt(dialog):
    dialog.vm.worldPrompt = "  My world  "
    assert dialog.get_world_prompt() == "My world"


def test_get_field_prompts(dialog):
    result = dialog.get_field_prompts()
    for etype in ("event", "character", "item", "location", "organization"):
        assert etype in result


def test_done_releases_the_island(dialog, qtbot):
    dialog.done(0)
    qtbot.waitUntil(lambda: dialog.quick.source().isEmpty(), timeout=2000)
