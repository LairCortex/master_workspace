"""Tests for LlmViewModel — connection config, status, prompts, generation proxy."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.application.services.llm_service import LlmService
from app.infrastructure.http import AppHttpClient
from app.infrastructure.llm.config import LlmConfig, LlmConfigManager
from app.infrastructure.llm.remote_provider import RemoteLlmProvider
from app.presentation.viewmodels.llm_viewmodel import LlmViewModel


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
def vm(mock_service, config_manager, http):
    return LlmViewModel(mock_service, config_manager, http)


# --- status ---------------------------------------------------------------


def test_initial_status_not_configured_when_no_file(vm, mock_service):
    assert vm.status == LlmViewModel.STATUS_NOT_CONFIGURED
    assert isinstance(mock_service.provider, RemoteLlmProvider)
    assert mock_service.provider.is_configured() is False


def test_initial_status_ready_when_config_present(mock_service, config_manager, http):
    config_manager.save(LlmConfig("https://api.example.com/v1", "model-x", "key"))
    vm = LlmViewModel(mock_service, config_manager, http)
    assert vm.status == LlmViewModel.STATUS_READY
    assert mock_service.provider.is_configured() is True
    assert mock_service.provider.config.base_url == "https://api.example.com/v1"


def test_initial_status_not_configured_when_config_incomplete(config_manager, http):
    svc = MagicMock(spec=LlmService)
    config_manager.save(LlmConfig("", ""))
    vm = LlmViewModel(svc, config_manager, http)
    assert vm.status == LlmViewModel.STATUS_NOT_CONFIGURED


def test_set_status_emits_signal(vm, qtbot):
    with qtbot.waitSignal(vm.model_status_changed, timeout=1000) as blocker:
        vm.set_status(LlmViewModel.STATUS_READY)
    assert blocker.args == [LlmViewModel.STATUS_READY]
    assert vm.status == LlmViewModel.STATUS_READY


def test_set_status_same_value_no_signal(vm):
    received = []
    vm.model_status_changed.connect(received.append)
    vm.set_status(LlmViewModel.STATUS_NOT_CONFIGURED)
    assert received == []


# --- apply_config ----------------------------------------------------------


def test_apply_config_updates_provider_and_status(vm, mock_service, qtbot):
    with qtbot.waitSignal(vm.model_status_changed, timeout=1000) as blocker:
        vm.apply_config(LlmConfig("http://localhost:11434/v1", "llama3"))
    assert blocker.args == [LlmViewModel.STATUS_READY]
    assert vm.status == LlmViewModel.STATUS_READY
    new_provider = mock_service.provider
    assert isinstance(new_provider, RemoteLlmProvider)
    assert new_provider.config == LlmConfig("http://localhost:11434/v1", "llama3", "")


def test_apply_config_empty_returns_to_not_configured(vm, mock_service):
    vm.apply_config(LlmConfig("http://any.url", "m"))
    old_provider = mock_service.provider
    vm.apply_config(LlmConfig("", ""))
    assert vm.status == LlmViewModel.STATUS_NOT_CONFIGURED
    assert mock_service.provider is not old_provider
    assert vm.config.base_url == ""


def test_apply_config_does_not_touch_network(mock_service, config_manager, http):
    vm = LlmViewModel(mock_service, config_manager, http)
    vm.apply_config(LlmConfig("https://unreachable.example/v1", "m"))
    assert vm.status == LlmViewModel.STATUS_READY


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
        await vm.request_generation("event.name", "event", "name", "Название", "текст")

    assert blocker.args == [None, "event.name", "AI text"]
    mock_service.generate_for_field.assert_awaited_once()
    kwargs = mock_service.generate_for_field.await_args.kwargs
    assert kwargs["world_prompt"] == "Мир"


@pytest.mark.asyncio
async def test_request_generation_emits_error(vm, mock_service, qtbot):
    vm.apply_config(LlmConfig("http://x", "m"))
    mock_service.generate_for_field = AsyncMock(side_effect=RuntimeError("LLM не настроен"))

    with qtbot.waitSignal(vm.generation_error, timeout=1000) as blocker:
        await vm.request_generation("item.name", "item", "name", "Название", "")

    assert blocker.args == [None, "item.name", "LLM не настроен"]


async def test_request_generation_passes_owner_to_service(vm, mock_service):
    """The dialog-owner is forwarded to the service for scoped cancellation."""
    vm.apply_config(LlmConfig("http://x", "m"))
    owner = object()

    await vm.request_generation("event.name", "event", "name", "Название", "", owner=owner)

    kwargs = mock_service.generate_for_field.await_args.kwargs
    assert kwargs["owner"] is owner
