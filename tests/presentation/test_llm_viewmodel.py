"""Tests for LlmViewModel — status transitions, persistence, signals."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from PySide6.QtCore import QCoreApplication

from app.application.services.llm_service import LlmService
from app.infrastructure.llm.local_provider import LocalGgufProvider
from app.infrastructure.llm.model_manager import ModelManager
from app.presentation.viewmodels.llm_viewmodel import LlmViewModel


@pytest.fixture
def mock_manager(tmp_path):
    mgr = MagicMock(spec=ModelManager)
    mgr.get_model_path.return_value = None
    return mgr


@pytest.fixture
def mock_provider():
    p = MagicMock(spec=LocalGgufProvider)
    p.is_ready.return_value = False
    return p


@pytest.fixture
def mock_service(mock_provider):
    svc = MagicMock(spec=LlmService)
    svc.provider = mock_provider
    svc.queue_size = 0
    return svc


@pytest.fixture
def vm(mock_service, mock_manager):
    return LlmViewModel(mock_service, mock_manager)


def test_initial_status_not_installed(vm):
    assert vm.status == LlmViewModel.STATUS_NOT_INSTALLED


def test_initial_status_ready_if_model_exists(mock_service, tmp_path):
    mgr = MagicMock(spec=ModelManager)
    mgr.get_model_path.return_value = tmp_path / "model.gguf"
    vm = LlmViewModel(mock_service, mgr)
    assert vm.status == LlmViewModel.STATUS_READY


def test_set_status_emits_signal(vm, qtbot):
    with qtbot.waitSignal(vm.model_status_changed, timeout=1000) as blocker:
        vm.set_status(LlmViewModel.STATUS_DOWNLOADING)
    assert blocker.args == [LlmViewModel.STATUS_DOWNLOADING]
    assert vm.status == LlmViewModel.STATUS_DOWNLOADING


def test_status_transitions(vm, qtbot):
    statuses = []
    vm.model_status_changed.connect(statuses.append)

    vm.set_status(LlmViewModel.STATUS_DOWNLOADING)
    vm.set_status(LlmViewModel.STATUS_LOADING)
    vm.set_status(LlmViewModel.STATUS_READY)

    assert statuses == [
        LlmViewModel.STATUS_DOWNLOADING,
        LlmViewModel.STATUS_LOADING,
        LlmViewModel.STATUS_READY,
    ]


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


def test_is_generation_available(vm):
    assert not vm.is_generation_available()
    vm.set_status(LlmViewModel.STATUS_READY)
    assert not vm.is_generation_available()
    vm.world_prompt = "World"
    assert vm.is_generation_available()


def test_delete_model(vm, mock_manager):
    vm.set_status(LlmViewModel.STATUS_READY)
    vm.delete_model()
    mock_manager.delete_model.assert_called_once()
    assert vm.status == LlmViewModel.STATUS_NOT_INSTALLED


@pytest.mark.asyncio
async def test_download_installs_packages_first(vm, mock_manager, qtbot):
    mock_manager.are_llm_packages_installed.return_value = False
    mock_manager.install_llm_packages = AsyncMock()
    mock_manager.download_model = AsyncMock()
    mock_manager.save_config = MagicMock()

    messages = []
    vm.download_status_message.connect(messages.append)

    await vm.download_model()

    mock_manager.install_llm_packages.assert_awaited_once()
    mock_manager.download_model.assert_awaited_once()
    assert any("пакет" in m.lower() for m in messages)
    assert vm.status == LlmViewModel.STATUS_READY


@pytest.mark.asyncio
async def test_download_skips_packages_if_installed(vm, mock_manager, qtbot):
    mock_manager.are_llm_packages_installed.return_value = True
    mock_manager.install_llm_packages = AsyncMock()
    mock_manager.download_model = AsyncMock()
    mock_manager.save_config = MagicMock()

    messages = []
    vm.download_status_message.connect(messages.append)

    await vm.download_model()

    mock_manager.install_llm_packages.assert_not_awaited()
    assert any("модел" in m.lower() for m in messages)
