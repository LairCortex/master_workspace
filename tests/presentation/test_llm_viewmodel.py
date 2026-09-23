"""Tests for LlmViewModel — connection config, status, prompts, generation proxy."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.application.services.llm_service import LlmService
from app.application.services.llm_status import LlmStatus
from app.infrastructure.http import AppHttpClient
from app.infrastructure.llm.config import LlmConfig, LlmConfigManager
from app.infrastructure.llm.errors import LlmError
from app.infrastructure.llm.remote_provider import RemoteLlmProvider
from app.presentation.viewmodels.llm_viewmodel import GenerationTarget, LlmViewModel


@pytest.fixture
def config_manager(tmp_path):
    return LlmConfigManager(tmp_path / "llm_config.json")


@pytest.fixture
async def http():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    holder = AppHttpClient(client=httpx.AsyncClient(transport=transport))
    yield holder
    await holder.close()


@pytest.fixture
def mock_service():
    svc = MagicMock(spec=LlmService)
    svc.generate_for_field = AsyncMock(return_value="AI text")
    return svc


@pytest.fixture
def make_provider(http):
    """The provider factory the composition root would inject (nri-0011, D2)."""

    def _make(config: LlmConfig) -> RemoteLlmProvider:
        return RemoteLlmProvider(config, http)

    return _make


@pytest.fixture
def vm(mock_service, config_manager, make_provider):
    return LlmViewModel(mock_service, config_manager, make_provider)


def target(field_id="event.name", entity_type="event", field_name="name",
           field_label="Название", current_text="", owner=None) -> GenerationTarget:
    """One generation request as the controller hands it to the ViewModel."""
    return GenerationTarget(
        field_id=field_id, entity_type=entity_type, field_name=field_name,
        field_label=field_label, current_text=current_text, owner=owner,
    )


# --- status ---------------------------------------------------------------


def test_initial_status_not_configured_when_no_file(vm, mock_service):
    assert vm.status == LlmStatus.NOT_CONFIGURED
    assert isinstance(mock_service.provider, RemoteLlmProvider)
    assert mock_service.provider.is_configured() is False


def test_initial_status_ready_when_config_present(mock_service, config_manager, make_provider):
    config_manager.save(LlmConfig("https://api.example.com/v1", "model-x", "key"))
    vm = LlmViewModel(mock_service, config_manager, make_provider)
    assert vm.status == LlmStatus.READY
    assert mock_service.provider.is_configured() is True
    assert mock_service.provider.config.base_url == "https://api.example.com/v1"


def test_initial_status_not_configured_when_config_incomplete(config_manager, make_provider):
    svc = MagicMock(spec=LlmService)
    config_manager.save(LlmConfig("", ""))
    vm = LlmViewModel(svc, config_manager, make_provider)
    assert vm.status == LlmStatus.NOT_CONFIGURED


def test_set_status_emits_signal(vm, qtbot):
    with qtbot.waitSignal(vm.model_status_changed, timeout=1000) as blocker:
        vm.set_status(LlmStatus.READY)
    assert blocker.args == [LlmStatus.READY]
    assert vm.status == LlmStatus.READY


def test_set_status_same_value_no_signal(vm):
    received = []
    vm.model_status_changed.connect(received.append)
    vm.set_status(LlmStatus.NOT_CONFIGURED)
    assert received == []


# --- apply_config ----------------------------------------------------------


def test_apply_config_updates_provider_and_status(vm, mock_service, qtbot):
    with qtbot.waitSignal(vm.model_status_changed, timeout=1000) as blocker:
        vm.apply_config(LlmConfig("http://localhost:11434/v1", "llama3"))
    assert blocker.args == [LlmStatus.READY]
    assert vm.status == LlmStatus.READY
    new_provider = mock_service.provider
    assert isinstance(new_provider, RemoteLlmProvider)
    assert new_provider.config == LlmConfig("http://localhost:11434/v1", "llama3", "")


def test_apply_config_empty_returns_to_not_configured(vm, mock_service):
    vm.apply_config(LlmConfig("http://any.url", "m"))
    old_provider = mock_service.provider
    vm.apply_config(LlmConfig("", ""))
    assert vm.status == LlmStatus.NOT_CONFIGURED
    assert mock_service.provider is not old_provider
    assert vm.config.base_url == ""


def test_apply_config_does_not_touch_network(mock_service, config_manager, make_provider):
    vm = LlmViewModel(mock_service, config_manager, make_provider)
    vm.apply_config(LlmConfig("https://unreachable.example/v1", "m"))
    assert vm.status == LlmStatus.READY


# --- check_connection (moved off the dialog, nri-0011 design D2) --------------


async def test_check_connection_success_returns_none_for_the_checked_config(
    mock_service, config_manager
):
    built: list[LlmConfig] = []

    def probe_provider(config: LlmConfig):
        built.append(config)

        async def _ok() -> str:
            return "ok"

        return SimpleNamespace(check_connection=_ok)

    vm = LlmViewModel(mock_service, config_manager, probe_provider)
    # The init fired the factory with the stored config; the check must fire
    # it again with exactly the config under test (one-shot provider).
    built.clear()
    checked = LlmConfig("http://probe/v1", "m")

    assert await vm.check_connection(checked) is None
    assert built == [checked]


async def test_check_connection_maps_llm_error_to_displayable_text(
    mock_service, config_manager
):
    def failing_provider(config: LlmConfig):
        async def _fail() -> str:
            raise LlmError("Неверный ключ API.")

        return SimpleNamespace(check_connection=_fail)

    vm = LlmViewModel(mock_service, config_manager, failing_provider)

    assert await vm.check_connection(LlmConfig("http://x", "m")) == "Неверный ключ API."


async def test_check_connection_is_one_shot_and_keeps_service_provider(
    mock_service, config_manager, make_provider
):
    """The probe never swaps the active provider or flips the stored status."""
    vm = LlmViewModel(mock_service, config_manager, make_provider)
    vm.apply_config(LlmConfig("http://other/v1", "keep"))
    active = mock_service.provider

    # The fixture transport answers 200 with an empty JSON — the provider
    # surfaces it as a displayable LlmError, which check_connection returns.
    text = await vm.check_connection(LlmConfig("http://probe/v1", "m"))

    assert text
    assert mock_service.provider is active
    assert vm.status == LlmStatus.READY


# --- availability ----------------------------------------------------------


def test_is_generation_available(vm):
    assert not vm.is_generation_available()

    vm.apply_config(LlmConfig("http://x", "m"))
    assert vm.is_generation_available() is False  # no world prompt yet

    vm.world_prompt = "Мир"
    assert vm.is_generation_available() is True


def test_is_generation_available_false_when_not_configured(vm):
    vm.world_prompt = "Мир"
    assert not vm.is_generation_available()


# --- prompts (per-game) -----------------------------------------------------


def test_world_prompt_persistence(vm):
    vm.world_prompt = "Dark fantasy world"
    json_str = vm.world_prompt_to_json()
    assert "Dark fantasy world" in json_str

    vm.world_prompt = ""
    vm.world_prompt_from_json(json_str)
    assert vm.world_prompt == "Dark fantasy world"


def test_field_prompts_saved_to_settings(vm):
    vm.field_prompts = {
        "event": {"name": "Короткое название", "characteristics": "", "backstory": ""},
        "character": {"name": "Имя", "characteristics": "", "backstory": "", "personality": "", "tasks": ""},
    }
    json_str = vm.field_prompts_to_json()
    assert "Короткое название" in json_str

    vm.field_prompts = {}
    vm.field_prompts_from_json(json_str)
    assert vm.get_field_prompt("event", "name") == "Короткое название"
    assert vm.get_field_prompt("character", "name") == "Имя"


def test_get_field_prompt_returns_configured(vm):
    vm.field_prompts = {
        "organization": {"name": "OrgName", "characteristics": "", "backstory": "", "tasks": ""},
    }
    assert vm.get_field_prompt("organization", "name") == "OrgName"


def test_get_field_prompt_returns_empty_for_unconfigured(vm):
    assert vm.get_field_prompt("item", "name") == ""
    assert vm.get_field_prompt("nonexistent", "field") == ""


def test_has_world_prompt(vm):
    assert not vm.has_world_prompt
    vm.world_prompt = "   "
    assert not vm.has_world_prompt
    vm.world_prompt = "Some world"
    assert vm.has_world_prompt


# --- generation proxy --------------------------------------------------------


@pytest.mark.asyncio
async def test_request_generation_emits_finished(vm, mock_service, qtbot):
    vm.apply_config(LlmConfig("http://x", "m"))
    vm.world_prompt = "Мир"

    with qtbot.waitSignal(vm.generation_finished, timeout=1000) as blocker:
        await vm.request_generation(target(current_text="текст"))

    assert blocker.args == [None, "event.name", "AI text"]
    mock_service.generate_for_field.assert_awaited_once()
    kwargs = mock_service.generate_for_field.await_args.kwargs
    assert kwargs["world_prompt"] == "Мир"


@pytest.mark.asyncio
async def test_request_generation_emits_error(vm, mock_service, qtbot):
    vm.apply_config(LlmConfig("http://x", "m"))
    mock_service.generate_for_field = AsyncMock(side_effect=RuntimeError("LLM не настроен"))

    with qtbot.waitSignal(vm.generation_error, timeout=1000) as blocker:
        await vm.request_generation(target(field_id="item.name", entity_type="item"))

    assert blocker.args == [None, "item.name", "LLM не настроен"]


async def test_request_generation_passes_owner_to_service(vm, mock_service):
    """The dialog-owner is forwarded to the service for scoped cancellation."""
    vm.apply_config(LlmConfig("http://x", "m"))
    owner = object()

    await vm.request_generation(target(owner=owner))

    kwargs = mock_service.generate_for_field.await_args.kwargs
    assert kwargs["owner"] is owner
