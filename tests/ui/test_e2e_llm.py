"""E2E scenario 6: LLM wizard — save connection, check it, AI-generate a field.

All LLM traffic goes through the injected emulated transport (canned 200);
the connection config file stays inside the test's tmp path.
"""
from __future__ import annotations

import json

from PySide6.QtWidgets import QDialog

from app.presentation.views.event_dialog import EventDialog
from app.presentation.views.llm_setup_dialog import LlmSetupDialog

from tests.ui.conftest import CANNED_LLM_CONTENT

WORLD_PROMPT = "Тёмное фэнтези: империя на руинах древней войны."
ENDPOINT = "http://mock-llm/v1"
MODEL = "test-model"

_ACTIVE_STYLE_MARKER = "rgba(91,155,213"   # AiAssistButton._ACTIVE_STYLE
_DISABLED_STYLE_MARKER = "rgba(128,128,128"  # AiAssistButton._DISABLED_STYLE


async def test_llm_wizard_check_connection_and_field_generation(app, llm_client, tmp_llm_config, wait_for):
    application, window = app
    llm_vm = application._llm_vm
    assert llm_vm.status == llm_vm.STATUS_NOT_CONFIGURED

    # ── Open the event dialog first: AI button is inactive until the LLM is configured
    window.timeline_widget.add_button.click()
    await wait_for(lambda: bool(window.findChildren(EventDialog)))
    dialog = window.findChildren(EventDialog)[0]
    name_btn = next(b for b in dialog.get_ai_buttons() if b.field_name == "name")
    assert _DISABLED_STYLE_MARKER in name_btn.styleSheet()

    # Click while unconfigured → info box (auto-accepted), no request, field untouched
    name_btn.click()
    await wait_for(lambda: len(llm_client.requests) == 0)
    assert dialog.name_input.text() == ""

    # ── Wizard: menu → configure connection → check connection (canned 200)
    window.llm_setup_action.trigger()
    await wait_for(lambda: bool(window.findChildren(LlmSetupDialog)))
    wizard = window.findChildren(LlmSetupDialog)[0]
    wizard._endpoint_edit.setText(ENDPOINT)
    wizard._model_edit.setText(MODEL)
    assert wizard._check_btn.isEnabled()
    wizard._check_btn.click()
    await wait_for(lambda: wizard._check_label.text() == "Соединение установлено")
    check_payload = json.loads(llm_client.requests[0].content)
    assert check_payload["max_tokens"] == 1

    # ── World prompt + save (dialog accepts only after the async save is done)
    wizard._next_btn.click()  # → world prompt page
    wizard._world_prompt_edit.setPlainText(WORLD_PROMPT)
    while not wizard._save_btn.isVisible():
        wizard._next_btn.click()
    wizard._save_btn.click()

    await wait_for(lambda: llm_vm.status == llm_vm.STATUS_READY)
    # The dialog accepts only after the async save (config + per-game prompts) finishes
    await wait_for(lambda: wizard.result() == QDialog.DialogCode.Accepted)
    # Connection config is saved to the (tmp) global config file
    assert tmp_llm_config.exists()
    config_raw = json.loads(tmp_llm_config.read_text(encoding="utf-8"))
    assert config_raw["base_url"] == ENDPOINT and config_raw["model"] == MODEL
    assert llm_vm.has_world_prompt

    # ── AI generation of a field through the (now active) assist button
    assert _ACTIVE_STYLE_MARKER in name_btn.styleSheet()
    name_btn.click()
    await wait_for(lambda: dialog.name_input.text() == CANNED_LLM_CONTENT)
    # The generation request carried the world prompt in the system message
    generation_payload = json.loads(llm_client.requests[-1].content)
    assert generation_payload["model"] == MODEL
    assert WORLD_PROMPT in generation_payload["messages"][0]["content"]
    # All requests went through the single emulated client
    assert len(llm_client.requests) == 2
