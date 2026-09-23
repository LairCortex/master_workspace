"""Sync VM of the LLM setup island (R3 pack 2) — no service, no http, no QML."""
from __future__ import annotations

from app.domain import entity_registry
from app.presentation.viewmodels.llm_setup_view_model import (
    PAGE_WARNINGS,
    LlmSetupViewModel,
)

# The LLM field set lives in the domain entity registry since wave 3 (A4);
# this local view keeps the assertions in this file unchanged.
FIELD_CONFIG = {
    desc.key: list(desc.llm_fields)
    for desc in map(entity_registry.descriptor, entity_registry.LLM_TYPES)
}


def _vm(**kwargs) -> LlmSetupViewModel:
    return LlmSetupViewModel(
        endpoint="https://api.openai.com/v1",
        model="gpt-4o-mini",
        api_key="sk-123",
        world_prompt="Test world",
        field_prompts={"event": {"name": "Evt name"}},
        **kwargs,
    )


def test_initial_values_from_constructor():
    vm = _vm()
    assert vm.currentPage == 0
    assert vm.endpoint == "https://api.openai.com/v1"
    assert vm.model == "gpt-4o-mini"
    assert vm.apiKey == "sk-123"
    assert vm.worldPrompt == "Test world"
    assert vm.saving is False
    assert vm.checkText == ""
    assert vm.checkStatus == ""


def test_empty_vm_defaults():
    vm = LlmSetupViewModel()
    assert vm.endpoint == "" and vm.model == "" and vm.apiKey == ""
    assert vm.worldPrompt == ""
    assert vm.checkEnabled is False


def test_field_pages_follow_field_config_order():
    vm = _vm()
    pages = vm.fieldPages
    assert [p["entityType"] for p in pages] == [
        "event", "organization", "character", "item", "location",
    ]
    for page in pages:
        names = [f["name"] for f in page["fields"]]
        assert names == list(FIELD_CONFIG[page["entityType"]])
        for field in page["fields"]:
            assert field["label"] and isinstance(field["placeholder"], str)
    assert pages[0]["title"].endswith("События")
    # seeded value survives into the model, the rest start empty
    assert pages[0]["fields"][0]["value"] == "Evt name"
    assert pages[0]["fields"][1]["value"] == ""


def test_page_count_is_connection_world_entities_warnings():
    vm = _vm()
    assert vm.pageCount == len(FIELD_CONFIG) + 3
    assert vm.pageCount == PAGE_WARNINGS + 1


def test_navigation_clamped_at_both_ends():
    vm = _vm()
    vm.goBack()
    assert vm.currentPage == 0
    assert vm.backEnabled is False
    assert vm.nextVisible is True
    assert vm.saveVisible is False

    vm.goNext()
    assert vm.currentPage == 1
    assert vm.backEnabled is True
    vm.goBack()
    assert vm.currentPage == 0

    for _ in range(20):
        vm.goNext()
    assert vm.currentPage == PAGE_WARNINGS
    assert vm.nextVisible is False
    assert vm.saveVisible is True


def test_navigation_frozen_while_saving():
    vm = _vm()
    vm.goNext()
    vm.set_saving(True)
    vm.goNext()
    vm.goBack()
    assert vm.currentPage == 1
    assert vm.backEnabled is False
    assert vm.saveEnabled is False
    vm.set_saving(False)
    assert vm.backEnabled is True
    assert vm.saveEnabled is True


def test_check_enabled_requires_endpoint_and_model():
    vm = _vm()
    assert vm.checkEnabled is True
    vm.endpoint = "   "
    assert vm.checkEnabled is False
    vm.endpoint = "http://localhost:11434/v1"
    assert vm.checkEnabled is True
    vm.model = ""
    assert vm.checkEnabled is False


def test_check_request_emitted_only_when_enabled():
    vm = _vm()
    requests: list[int] = []
    vm.checkRequested.connect(lambda: requests.append(1))
    vm.model = ""
    vm.requestCheck()
    assert requests == []
    vm.model = "llama3"
    vm.requestCheck()
    assert requests == [1]


def test_check_running_then_result():
    vm = _vm()
    vm.set_check_running("Проверка соединения…")
    assert vm.checkText == "Проверка соединения…"
    assert vm.checkStatus == ""
    assert vm.checkEnabled is False  # blocked while the facade checks
    vm.requestCheck()  # a second click during the check is a no-op

    vm.set_check_result("Соединение установлено", "ok")
    assert vm.checkText == "Соединение установлено"
    assert vm.checkStatus == "ok"
    assert vm.checkEnabled is True

    vm.set_check_result("Ошибка: нет", "error")
    assert vm.checkStatus == "error"


def test_save_request_blocked_while_saving():
    vm = _vm()
    requests: list[int] = []
    vm.saveRequested.connect(lambda: requests.append(1))
    vm.requestSave()
    vm.set_saving(True)
    vm.requestSave()
    assert requests == [1]
    assert vm.saving is True


def test_setters_are_idempotent_and_notify():
    vm = _vm()
    changes: list[str] = []
    vm.connectionChanged.connect(lambda: changes.append("conn"))
    vm.worldChanged.connect(lambda: changes.append("world"))

    vm.endpoint = vm.endpoint
    vm.model = vm.model
    vm.apiKey = vm.apiKey
    vm.worldPrompt = vm.worldPrompt
    assert changes == []

    vm.endpoint = "e"
    vm.model = "m"
    vm.apiKey = "k"
    vm.worldPrompt = "w"
    assert changes == ["conn", "conn", "conn", "world"]


def test_field_values_round_trip_to_nested_dict():
    vm = _vm()
    vm.setFieldValue(0, 1, "  характеристики  ")
    vm.setFieldValue(2, 0, "Имя")
    vm.setFieldValue(99, 0, "ignored")  # out of range is a no-op
    vm.setFieldValue(0, 99, "ignored")

    prompts = vm.field_prompts_dict()
    assert set(prompts) == set(FIELD_CONFIG)
    assert prompts["event"]["name"] == "Evt name"
    assert prompts["event"]["characteristics"] == "характеристики"
    assert prompts["character"]["name"] == "Имя"
    assert list(prompts["character"]) == list(FIELD_CONFIG["character"])
