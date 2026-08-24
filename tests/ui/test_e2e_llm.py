"""E2E scenario 6: LLM wizard — save connection, check it, AI-generate a field.

All LLM traffic goes through the injected emulated transport (canned 200);
the connection config file stays inside the test's tmp path.
"""
from __future__ import annotations

import asyncio
import json
import time

import httpx
import pytest_asyncio
from PySide6.QtWidgets import QDialog

from app.infrastructure.http import AppHttpClient
from app.infrastructure.llm.config import LlmConfig
from app.main import Application
from app.presentation.viewmodels.llm_viewmodel import _default_field_prompts
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
    wizard = _open_wizard(window)
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



def _open_wizard(win) -> LlmSetupDialog:
    """Trigger the LLM setup menu and return the wizard created by THIS trigger.

    ``accept()`` does not destroy a dialog, so already-accepted wizards stay
    in the parent's child list; diff the child sets and drop the leftovers.
    """
    before = {id(d) for d in win.findChildren(LlmSetupDialog)}
    win.llm_setup_action.trigger()
    fresh = []
    for dlg in win.findChildren(LlmSetupDialog):
        if id(dlg) in before:
            dlg.close()
        else:
            fresh.append(dlg)
    assert len(fresh) == 1
    return fresh[0]


async def test_llm_settings_reload_and_save_edge_paths(
    app, llm_client, tmp_llm_config, wait_for, message_boxes, monkeypatch
):
    application, window = app
    db_path = application._db_path

    # Save #1: the per-game prompt rows are created
    window.llm_setup_action.trigger()
    await wait_for(lambda: bool(window.findChildren(LlmSetupDialog)))
    wizard = window.findChildren(LlmSetupDialog)[0]
    wizard.saved.emit(
        LlmConfig(base_url=ENDPOINT, model=MODEL), WORLD_PROMPT, {"character": {}}
    )
    await wait_for(lambda: wizard.result() == QDialog.DialogCode.Accepted)

    # Restart on the same DB: the loader finds the stored rows
    await application.shutdown()
    window2 = await application.start(str(db_path))
    try:
        assert application._llm_vm.world_prompt == WORLD_PROMPT
        # The setter merges with defaults: the round-tripped value is the defaults
        assert application._llm_vm.field_prompts == _default_field_prompts()

        # Save #2: the rows exist now → update-in-place path
        wizard2 = _open_wizard(window2)
        wizard2.saved.emit(
            LlmConfig(base_url=ENDPOINT, model=MODEL), WORLD_PROMPT + "+2", {"character": {}}
        )
        await wait_for(lambda: wizard2.result() == QDialog.DialogCode.Accepted)
        assert application._llm_vm.world_prompt == WORLD_PROMPT + "+2"

        # Session gone mid-save: per-game prompts are dropped, save still succeeds
        wizard3 = _open_wizard(window2)
        real_session = application._session
        application._session = None
        wizard3.saved.emit(LlmConfig(base_url=ENDPOINT, model=MODEL), "W3", {})
        await wait_for(lambda: wizard3.result() == QDialog.DialogCode.Accepted)

        # Save failure: warning box, dialog stays open (no accept)
        application._session = real_session

        async def broken_save(*args, **kwargs):
            raise RuntimeError("save failed")

        monkeypatch.setattr(application, "_save_llm_settings", broken_save)
        wizard4 = _open_wizard(window2)
        wizard4.saved.emit(LlmConfig(base_url=ENDPOINT, model=MODEL), "W4", {})
        await wait_for(lambda: any(
            kind == "warning" and "Настройка LLM" in title
            for kind, title, _text in message_boxes
        ))
        assert wizard4.result() != QDialog.DialogCode.Accepted
    finally:
        window.close()  # already closed by start(); safe no-op
        await application.shutdown()


# ── visible errors (D6) and batch orchestration ────────────────────────────


@pytest_asyncio.fixture
async def app_401(qapp, tmp_games_dir, tmp_llm_config, tmp_path):
    """Application where every LLM request gets a non-retryable 401."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401, json={"error": {"message": "Invalid API key", "type": "auth"}}
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    http = AppHttpClient(client=client)
    http.requests = []

    db_path = tmp_path / "game_401.db"
    application = Application(qapp, http=http)
    window = await application.start(str(db_path))
    yield application, window
    window.close()
    await application.shutdown()
    await client.aclose()


async def test_single_generation_error_shows_warning_with_field_name(
    app_401, wait_for, message_boxes
):
    """A failed single generation is no longer silent: the user gets a
    warning naming the field and the reason; the field text is untouched
    and the AI button becomes active again."""
    application, window = app_401
    llm_vm = application._llm_vm

    window.timeline_widget.add_button.click()
    await wait_for(lambda: bool(window.findChildren(EventDialog)))
    dialog = window.findChildren(EventDialog)[0]
    name_btn = next(b for b in dialog.get_ai_buttons() if b.field_name == "name")

    llm_vm.world_prompt = WORLD_PROMPT
    llm_vm.apply_config(LlmConfig(base_url=ENDPOINT, model=MODEL))
    await wait_for(lambda: llm_vm.status == llm_vm.STATUS_READY)
    assert _ACTIVE_STYLE_MARKER in name_btn.styleSheet()

    name_btn.click()
    await wait_for(lambda: any(kind == "warning" for kind, _t, _x in message_boxes))
    warning = next(item for item in message_boxes if item[0] == "warning")
    _kind, _title, text = warning

    assert "Название" in text
    assert "Неверный ключ API" in text
    assert dialog.name_input.text() == ""
    assert not name_btn.is_generating
    assert name_btn.isEnabled()


@pytest_asyncio.fixture
async def slow_llm_client():
    """MockTransport LLM: per-field delays/failures configured via ``http.state``.

    ``state`` keys: ``delay`` (default seconds), ``field_delays`` (label→s),
    ``fail`` (label → (status, message)), ``requests``, ``started_times``,
    ``finished_times``.
    """
    state: dict = {
        "delay": 0.05,
        "field_delays": {},
        "fail": {},
        "fail_first_n": {},  # label → how many attempts get a 503 before success
        "attempts": {},      # label → attempts seen so far
        "requests": [],
        "started_times": [],
        "finished_times": [],
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        import re as _re

        payload = json.loads(request.content)
        user_prompt = payload["messages"][1]["content"]
        m = _re.search(r"поле «(.+?)»", user_prompt)
        label = m.group(1) if m else "?"
        state["requests"].append(request)
        state["started_times"].append(time.monotonic())
        state["attempts"][label] = state["attempts"].get(label, 0) + 1
        first_n = state["fail_first_n"].get(label, 0)
        if state["attempts"][label] <= first_n:
            return httpx.Response(503, json={"error": {"message": "unavailable", "type": "test"}})
        await asyncio.sleep(state["field_delays"].get(label, state["delay"]))
        state["finished_times"].append(time.monotonic())
        failure = state["fail"].get(label)
        if failure is not None:
            status, message = failure
            return httpx.Response(status, json={"error": {"message": message, "type": "test"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": f"AI: {label}"}}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    http = AppHttpClient(client=client)
    http.state = state
    yield http
    await client.aclose()


@pytest_asyncio.fixture
async def app_slow_llm(qapp, tmp_games_dir, tmp_llm_config, tmp_path, slow_llm_client):
    db_path = tmp_path / "game_slow.db"
    application = Application(qapp, http=slow_llm_client)
    window = await application.start(str(db_path))
    yield application, window
    window.close()
    await application.shutdown()


def _make_ready_card(application, window, entity_type: str = "character"):
    """Character/event card opened the same way the wiring opens it."""
    from app.presentation.views.entity_card_dialog import EntityCardDialog

    dialog = EntityCardDialog(None, entity_type=entity_type, parent=window)
    application._wire_ai_buttons(dialog)
    application._llm_vm.world_prompt = WORLD_PROMPT
    application._llm_vm.apply_config(LlmConfig(base_url=ENDPOINT, model=MODEL))
    dialog.open()
    return dialog


async def test_batch_start_locks_all_fields_and_runs_requests_in_parallel(
    app_slow_llm, slow_llm_client, wait_for, message_boxes
):
    """Bundle start: every target field is in the generating state, Save is
    blocked, the entity button flips to cancel, all requests go out in
    parallel and each result lands in its field as soon as it arrives."""
    application, window = app_slow_llm
    state = slow_llm_client.state
    state["field_delays"] = {
        "Название": 0.05,
        "Характеристики": 0.15,
        "Предыстория": 0.15,
        "Личность": 0.15,
        "Задачи": 0.15,
    }
    dialog = _make_ready_card(application, window)

    # A field with existing text: its text is mixed into the prompt
    dialog.backstory_input.setPlainText("Ранний текст пользователя")
    entity_btn = dialog.get_entity_button()
    assert entity_btn.isEnabled()

    entity_btn.click()

    # all five fields are in the generating state
    assert len(dialog.get_ai_buttons()) == 5
    for btn in dialog.get_ai_buttons():
        assert btn.is_generating
        assert not btn.isEnabled()
    assert dialog.name_input.isReadOnly()
    assert dialog.characteristics_input.isReadOnly()
    assert dialog.backstory_input.isReadOnly()
    assert dialog.personality_input.isReadOnly()
    assert dialog.tasks_input.isReadOnly()
    assert not dialog.save_button.isEnabled()
    assert entity_btn.is_cancelling

    # all five requests were launched, and at least one has already answered…
    await wait_for(
        lambda: len(state["started_times"]) == 5 and len(state["finished_times"]) >= 1
    )
    # …in parallel: the second one started before the first one finished
    assert state["started_times"][1] < state["finished_times"][0]

    # the pre-filled text went into the prompt of its field
    await wait_for(lambda: dialog.name_input.text() == "AI: Название")
    backstory_req = next(
        r for r in state["requests"] if "«Предыстория»" in r.content.decode("utf-8")
    )
    assert "Ранний текст пользователя" in backstory_req.content.decode("utf-8")

    # early result unblocks ONLY its field; the rest keep generating
    assert not dialog.name_input.isReadOnly()
    name_btn = next(b for b in dialog.get_ai_buttons() if b.field_name == "name")
    assert not name_btn.is_generating
    assert dialog.characteristics_input.isReadOnly()
    assert dialog.personality_input.isReadOnly()

    # the wave finishes: every field filled with its own result and editable
    await wait_for(lambda: all(not b.is_generating for b in dialog.get_ai_buttons()))
    assert dialog.name_input.text() == "AI: Название"
    assert dialog.characteristics_input.toPlainText() == "AI: Характеристики"
    assert dialog.backstory_input.toPlainText() == "AI: Предыстория"
    assert dialog.personality_input.toPlainText() == "AI: Личность"
    assert dialog.tasks_input.toPlainText() == "AI: Задачи"
    for btn in dialog.get_ai_buttons():
        assert btn.isEnabled()
        assert not btn.is_generating
    assert dialog.name_input.isReadOnly() is False
    assert dialog.save_button.isEnabled()
    assert not entity_btn.is_cancelling
    # a fully successful wave shows no error dialog
    assert not any(kind in ("warning", "critical") for kind, _t, _x in message_boxes)


async def _start_batch_and_settle(dialog, wait_for):
    dialog.get_entity_button().click()
    await wait_for(lambda: all(not b.is_generating for b in dialog.get_ai_buttons()))


async def test_batch_all_failed_one_reason_one_aggregated_dialog(
    app_slow_llm, slow_llm_client, wait_for, message_boxes
):
    application, window = app_slow_llm
    slow_llm_client.state["fail"] = {
        "Характеристики": (401, "Invalid API key"),
        "Предыстория": (401, "Invalid API key"),
    }
    dialog = _make_ready_card(application, window)
    await _start_batch_and_settle(dialog, wait_for)

    warnings = [text for kind, _t, text in message_boxes if kind == "warning"]
    assert len(warnings) == 1
    text = warnings[0]
    assert "«Характеристики»" in text
    assert "«Предыстория»" in text
    # one shared reason — stated once for the whole list
    assert text.count("Неверный ключ API или недостаточно прав") == 1
    # the successful fields stay filled and their buttons are active again
    assert dialog.name_input.text() == "AI: Название"
    assert dialog.personality_input.toPlainText() == "AI: Личность"
    assert dialog.tasks_input.toPlainText() == "AI: Задачи"
    for btn in dialog.get_ai_buttons():
        assert btn.isEnabled()
    assert dialog.save_button.isEnabled()


async def test_batch_different_failed_reasons_listed_per_field(
    app_slow_llm, slow_llm_client, wait_for, message_boxes
):
    application, window = app_slow_llm
    slow_llm_client.state["fail"] = {
        "Характеристики": (401, "Invalid API key"),
        "Задачи": (404, "model missing"),
    }
    dialog = _make_ready_card(application, window)
    await _start_batch_and_settle(dialog, wait_for)

    warnings = [text for kind, _t, text in message_boxes if kind == "warning"]
    assert len(warnings) == 1
    text = warnings[0]
    # different reasons — each failed field gets its own line
    assert "«Характеристики»: Неверный ключ API или недостаточно прав" in text
    assert "«Задачи»: Модель или endpoint не найдены" in text


async def test_batch_partial_failure_keeps_successes_and_reports_one_field(
    app_slow_llm, slow_llm_client, wait_for, message_boxes
):
    application, window = app_slow_llm
    slow_llm_client.state["fail"] = {"Личность": (401, "Invalid API key")}
    dialog = _make_ready_card(application, window)
    await _start_batch_and_settle(dialog, wait_for)

    warnings = [text for kind, _t, text in message_boxes if kind == "warning"]
    assert len(warnings) == 1
    assert "«Личность»" in warnings[0]
    assert "«Характеристики»" not in warnings[0]
    assert dialog.characteristics_input.toPlainText() == "AI: Характеристики"
    assert dialog.name_input.text() == "AI: Название"
    # the failed field is editable again with its previous (empty) content
    assert dialog.personality_input.toPlainText() == ""


# ── close protection & phase-dependent confirmation (spec: Закрытие диалога) ──


ALL_FIELD_LABELS = ("Название", "Характеристики", "Предыстория", "Личность", "Задачи")


async def _start_wave_wait_in_flight(dialog, wait_for, service):
    dialog.get_entity_button().click()
    await wait_for(lambda: service.any_active(dialog) and service.any_in_flight(dialog))


async def test_close_while_in_flight_no_keeps_dialog_and_generation(
    app_slow_llm, slow_llm_client, wait_for, message_boxes
):
    """X/«Отмена» with a request already sent to LLM → confirmation; «Нет»
    keeps the dialog open and the generation runs to completion."""
    application, window = app_slow_llm
    state = slow_llm_client.state
    state["delay"] = 0.4
    service = application._llm_service
    dialog = _make_ready_card(application, window)
    await _start_wave_wait_in_flight(dialog, wait_for, service)

    # «Отмена» (same path as X) → guard → question; the stub answers No by default
    dialog.cancel_button.click()
    questions = [item for item in message_boxes if item[0] == "question"]
    assert len(questions) == 1
    _kind, _title, text = questions[0]
    assert "5" in text  # five fields in flight
    assert dialog.isVisible()

    # generation continues and completes without an error dialog
    await wait_for(lambda: all(not b.is_generating for b in dialog.get_ai_buttons()))
    assert dialog.name_input.text() == "AI: Название"
    assert not any(kind in ("warning", "critical") for kind, _t, _x in message_boxes)


async def test_close_while_in_flight_yes_cancels_and_closes(
    app_slow_llm, slow_llm_client, wait_for, message_boxes, monkeypatch
):
    """Confirming the warning cancels every request of the dialog and closes it;
    cancellation shows no error dialog."""
    from PySide6.QtWidgets import QMessageBox

    application, window = app_slow_llm
    state = slow_llm_client.state
    state["delay"] = 0.4
    service = application._llm_service
    dialog = _make_ready_card(application, window)

    def _question_yes(parent, title, *args, **kwargs):
        message_boxes.append(("question", title, args[0] if args else kwargs.get("text", "")))
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", staticmethod(_question_yes))

    await _start_wave_wait_in_flight(dialog, wait_for, service)
    requests_before_close = len(state["requests"])
    assert requests_before_close == 5

    dialog.close()  # X path
    assert not dialog.isVisible()
    assert dialog.result() == QDialog.DialogCode.Rejected

    await wait_for(lambda: not service.any_active(dialog))
    await _flush(wait_for)
    # cancelled in flight: no further attempts, no error dialog
    assert len(state["requests"]) == 5
    assert len(state["finished_times"]) == 0
    assert not any(kind in ("warning", "critical") for kind, _t, _x in message_boxes)


async def test_close_while_only_waiting_closes_silently(
    app_slow_llm, slow_llm_client, wait_for, message_boxes
):
    """X when the requests are only between retry attempts (not sent to LLM)
    → no confirmation, the dialog closes and the requests are cancelled."""
    application, window = app_slow_llm
    state = slow_llm_client.state
    state["fail_first_n"] = {label: 1 for label in ALL_FIELD_LABELS}  # 503, then 200
    service = application._llm_service
    dialog = _make_ready_card(application, window)

    dialog.get_entity_button().click()
    # wait until every request has hit the 503 and sits in the retry backoff:
    # active, but nothing is in flight any more
    await wait_for(lambda: service.any_active(dialog) and not service.any_in_flight(dialog))

    dialog.close()  # X path

    # no confirmation and no error dialog; the dialog is closed
    assert not any(kind == "question" for kind, _t, _x in message_boxes)
    assert not any(kind in ("warning", "critical") for kind, _t, _x in message_boxes)
    assert not dialog.isVisible()

    await wait_for(lambda: not service.any_active(dialog))
    await _flush(wait_for)
    # each request was cancelled in the backoff: the never-happened retry never came
    assert all(n == 1 for n in state["attempts"].values())


async def test_batch_button_cancel_keeps_arrived_results_and_shows_no_error(
    app_slow_llm, slow_llm_client, wait_for, message_boxes
):
    """Cancel via the entity button while a wave runs: already-landed results
    stay in the fields, the rest become editable, no error dialog appears."""
    application, window = app_slow_llm
    state = slow_llm_client.state
    state["field_delays"] = {
        "Название": 0.05,
        "Характеристики": 0.5,
        "Предыстория": 0.5,
        "Личность": 0.5,
        "Задачи": 0.5,
    }
    service = application._llm_service
    dialog = _make_ready_card(application, window)
    entity_btn = dialog.get_entity_button()
    entity_btn.click()

    await wait_for(lambda: dialog.name_input.text() == "AI: Название")

    entity_btn.click()  # → batch_cancel_requested

    assert not entity_btn.is_cancelling
    for btn in dialog.get_ai_buttons():
        assert not btn.is_generating
        assert btn.isEnabled()
    assert dialog.save_button.isEnabled()

    # the arrived result is preserved; the unfinished fields are editable with
    # their previous (empty) content
    assert dialog.name_input.text() == "AI: Название"
    assert dialog.characteristics_input.toPlainText() == ""
    assert dialog.personality_input.toPlainText() == ""

    await wait_for(lambda: not service.any_active(dialog))
    await _flush(wait_for)
    assert len(state["requests"]) == 5
    assert not any(kind in ("warning", "critical", "question") for kind, _t, _x in message_boxes)


async def test_cancel_button_without_generation_closes_via_guard(
    app, wait_for, message_boxes
):
    """«Отмена» without any generation goes through the wiring guard, which
    simply rejects (D5): the dialog closes and no message box is shown."""
    application, window = app
    dialog = _make_ready_card(application, window)

    dialog.cancel_button.click()
    assert not dialog.isVisible()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert not message_boxes


class _GateProvider:
    """Provider whose generate suspends on a gate until the test releases it."""

    def __init__(self):
        self.gate = asyncio.Event()
        self.calls = 0

    async def generate(self, system_prompt, user_prompt, max_tokens=512, on_phase=None):
        # The result is the entry-time call number: with a released gate the
        # answer is stable per request (done-N for the N-th started request).
        call_no = self.calls + 1
        self.calls += 1
        await self.gate.wait()
        return f"done-{call_no}"

    async def close(self) -> None:
        pass


async def _flush(wait_for) -> None:
    """Turn the loop once: deliveries queued by the previous step run through.

    Signals emitted from app tasks reach the wiring handlers via the Qt
    event queue in this rig, so state set by them lags the service registry
    by one pump.
    """
    done = False
    try:
        await wait_for(lambda: done, timeout_s=0.05)
    except TimeoutError:
        pass


async def _start_single_and_wait_in_flight(application, dialog, wait_for):
    name_btn = next(b for b in dialog.get_ai_buttons() if b.field_name == "name")
    name_btn.generate_requested.emit("character", "name", "Название", "")
    await wait_for(lambda: application._llm_service.any_active(dialog))
    return name_btn


async def test_close_during_single_generation_declined_continues(
    app, wait_for, message_boxes
):
    """Close/«Отмена» during a single in-flight generation: «Нет» keeps the
    dialog open and the generation continues to completion."""
    application, window = app
    provider = _GateProvider()
    dialog = _make_ready_card(application, window)
    application._llm_service.provider = provider

    name_btn = await _start_single_and_wait_in_flight(application, dialog, wait_for)

    dialog.cancel_button.click()  # stub answers No (defaultButton)
    assert any(item[0] == "question" for item in message_boxes)
    assert dialog.isVisible()

    provider.gate.set()
    await wait_for(lambda: not name_btn.is_generating)
    assert dialog.name_input.text() == "done-1"
    assert not any(kind in ("warning", "critical") for kind, _t, _x in message_boxes)


async def test_close_during_single_confirmed_cancels_and_late_signals_are_dropped(
    app, wait_for, message_boxes, monkeypatch
):
    """Confirmed close during a single generation: cancel + close, no error
    dialog; a result or an error that lands after the cancel (race window)
    must not be applied nor reported."""
    from PySide6.QtWidgets import QMessageBox

    application, window = app
    provider = _GateProvider()
    dialog = _make_ready_card(application, window)
    application._llm_service.provider = provider

    def _question_yes(parent, title, *args, **kwargs):
        message_boxes.append(("question", title, args[0] if args else kwargs.get("text", "")))
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", staticmethod(_question_yes))

    name_btn = await _start_single_and_wait_in_flight(application, dialog, wait_for)
    assert name_btn.is_generating

    dialog.close()  # X path → confirm → cancel_all + reject
    assert not dialog.isVisible()
    assert dialog.result() == QDialog.DialogCode.Rejected
    await wait_for(lambda: not name_btn.is_generating)
    await wait_for(lambda: not application._llm_service.any_active(dialog))

    # Late signals from the cancelled request (response crossed the cancel
    # line): dropped — no text, no error dialog.
    application._llm_vm.generation_finished.emit(dialog, "character.name", "late text")
    application._llm_vm.generation_error.emit(dialog, "character.name", "late error")
    # A same-field_id signal from another dialog of the same entity type is
    # foreign (nested card) — dropped by the owner filter as well.
    application._llm_vm.generation_finished.emit(object(), "character.name", "foreign text")
    await _flush(wait_for)
    assert dialog.name_input.text() == ""
    assert not any(kind in ("warning", "critical") for kind, _t, _x in message_boxes)


async def test_concurrent_single_start_while_one_is_running_is_ignored(
    app, wait_for, message_boxes
):
    """At most one wave per dialog: a field-button start while another field
    generation is in flight is ignored (no second request)."""
    application, window = app
    provider = _GateProvider()
    dialog = _make_ready_card(application, window)
    application._llm_service.provider = provider

    name_btn = await _start_single_and_wait_in_flight(application, dialog, wait_for)
    chars_btn = next(b for b in dialog.get_ai_buttons() if b.field_name == "characteristics")

    chars_btn.generate_requested.emit("character", "characteristics", "Характеристики", "")
    assert provider.calls == 1
    assert not chars_btn.is_generating

    provider.gate.set()
    await wait_for(lambda: not name_btn.is_generating)
    assert dialog.name_input.text() == "done-1"


async def test_nested_card_results_do_not_cross_between_dialogs(
    app, wait_for, message_boxes
):
    """Nested card of the SAME entity type (spec: «Вложенная карточка»):
    both dialogs run a full wave in parallel and share every field id —
    each result must land only in its own dialog's fields (the service
    registry is owner-scoped, and the delivery signals must be too)."""
    from app.presentation.views.entity_card_dialog import EntityCardDialog

    application, window = app
    provider = _GateProvider()
    parent = _make_ready_card(application, window)
    application._llm_service.provider = provider

    # Parent wave: the first five requests (done-1..done-5)
    parent.get_entity_button().click()
    await wait_for(lambda: application._llm_service.count_in_flight(parent) == 5)

    child = EntityCardDialog(None, entity_type="character", parent=parent)
    application._wire_ai_buttons(child)
    child.open()
    # Child wave: the next five requests (done-6..done-10)
    child.get_entity_button().click()
    await wait_for(lambda: application._llm_service.count_in_flight(child) == 5)
    assert provider.calls == 10

    provider.gate.set()
    await wait_for(
        lambda: not application._llm_service.any_active(parent)
        and not application._llm_service.any_active(child)
    )
    await _flush(wait_for)

    # "character.name" exists in BOTH dialogs: only this dialog's own
    # result may fill its field.
    assert parent.name_input.text() == "done-1"
    assert child.name_input.text() == "done-6"
    for d in (parent, child):
        assert d.save_button.isEnabled()
        assert not any(b.is_generating for b in d.get_ai_buttons())
    assert not any(kind in ("warning", "critical") for kind, _t, _x in message_boxes)


async def test_nested_card_cancel_only_stops_nested_generation(
    app, wait_for, message_boxes
):
    """Nested card (spec: «Вложенная карточка»): a generation cancelled in a
    nested card interrupts only the nested card's requests — the parent
    dialog's in-flight generation keeps running and completes normally,
    and the nested cancel shows no error dialog."""
    from app.presentation.views.entity_card_dialog import EntityCardDialog

    application, window = app
    provider = _GateProvider()
    parent = _make_ready_card(application, window)
    application._llm_service.provider = provider

    # Parent card: one single generation, gated (stays in flight)
    parent_btn = next(b for b in parent.get_ai_buttons() if b.field_name == "name")
    parent_btn.generate_requested.emit("character", "name", "Название", "")
    await wait_for(lambda: application._llm_service.any_active(parent))
    assert provider.calls == 1
    assert parent_btn.is_generating

    # Nested card — the same construction the wiring uses to open it
    # from the parent dialog's related section.
    child = EntityCardDialog(None, entity_type="character", parent=parent)
    application._wire_ai_buttons(child)
    child.open()

    # Nested card: a full wave, gated (all five requests stay in flight)
    child_entity = child.get_entity_button()
    child_entity.click()
    await wait_for(lambda: application._llm_service.count_in_flight(child) == 5)
    assert provider.calls == 6
    assert not parent.save_button.isEnabled()

    # Cancel the nested wave via its entity button
    child_entity.click()
    assert not child_entity.is_cancelling
    for btn in child.get_ai_buttons():
        assert not btn.is_generating
        assert btn.isEnabled()
    assert child.save_button.isEnabled()
    await wait_for(lambda: not application._llm_service.any_active(child))
    # Cancellation is not an error: no message box of any kind
    assert not message_boxes

    # The parent generation survived the nested cancel, still in flight
    assert parent.isVisible()
    assert parent_btn.is_generating
    assert application._llm_service.any_in_flight(parent)

    # Release the gate: only the parent's request can land now (the
    # provider answers with the entry-time call number: done-1).
    provider.gate.set()
    await wait_for(lambda: not parent_btn.is_generating)
    assert provider.calls == 6
    assert parent.name_input.text() == "done-1"
    assert parent.save_button.isEnabled()
    assert not any(kind in ("warning", "critical") for kind, _t, _x in message_boxes)
