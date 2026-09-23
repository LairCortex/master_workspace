"""ObjectName contract, single-source fields and live retheme of the LLM island."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from PySide6.QtGui import QAccessible
from PySide6.QtQuick import QQuickItem

from app.domain import entity_registry
from app.infrastructure.llm.config import LlmConfig
from app.presentation.views.llm_setup_dialog import ROOT_QML, LlmSetupDialog
from tests.presentation.qml_helpers import find_item, walk_items

# The LLM field set lives in the domain entity registry since wave 3 (A4);
# this local view keeps the assertions in this file unchanged.
FIELD_CONFIG = {
    desc.key: list(desc.llm_fields)
    for desc in map(entity_registry.descriptor, entity_registry.LLM_TYPES)
}


@pytest.fixture
def dialog(qtbot):
    dlg = LlmSetupDialog(
        config=LlmConfig("https://api.openai.com/v1", "gpt-4o-mini", "sk-123"),
        world_prompt="Test world",
        field_prompts={"event": {"name": "Evt name"}},
    )
    qtbot.addWidget(dlg)
    return dlg


def _names(root: QQuickItem) -> set[str]:
    return {root.objectName()} | {i.objectName() for i in walk_items(root)}


def test_root_object_names_cover_every_control(dialog):
    root = dialog.quick.rootObject()
    names = _names(root)
    assert root.objectName() == "llmSetupRoot"
    for expected in (
        "endpointField", "modelField", "keyField", "checkButton", "checkStatusText",
        "worldPromptArea", "warningsPage", "backButton", "nextButton", "saveButton",
    ):
        assert expected in names, expected
    assert root.property("defaultButton").objectName() == "saveButton"


def _iface(widget, object_name: str):
    iface = QAccessible.queryAccessibleInterface(find_item(widget, object_name))
    assert iface is not None, f"no accessibility interface on {object_name!r}"
    return iface


def test_accessibility_names_on_all_four_zones(dialog):
    """nri-0012 task 3.2: endpoint/model/key/world carry the design-map names
    through the interface, and the field-prompt repeater names itself by the
    model label (the same string its TitleText paints)."""
    quick = dialog.quick

    endpoint = _iface(quick, "endpointField")
    assert endpoint.role() == QAccessible.Role.EditableText
    assert endpoint.text(QAccessible.Name) == "Endpoint"

    model = _iface(quick, "modelField")
    assert model.role() == QAccessible.Role.EditableText
    assert model.text(QAccessible.Name) == "Модель"

    key = _iface(quick, "keyField")
    assert key.role() == QAccessible.Role.EditableText
    assert key.text(QAccessible.Name) == "Ключ API"

    # The world page sits on StackLayout page 1: show it before querying.
    dialog.vm.goNext()
    world = _iface(quick, "worldPromptArea")
    assert world.role() == QAccessible.Role.EditableText
    assert world.text(QAccessible.Name) == "Описание мира"


def test_field_prompt_repeater_names_by_model_label(dialog):
    prompt = _iface(dialog.quick, "fieldPrompt_event_name")
    assert prompt.role() == QAccessible.Role.EditableText
    assert prompt.text(QAccessible.Name) == "Название"


def test_field_prompt_inputs_come_from_field_config(dialog):
    names = _names(dialog.quick.rootObject())
    for entity_type, fields in FIELD_CONFIG.items():
        for field_name in fields:
            assert f"fieldPrompt_{entity_type}_{field_name}" in names
    assert find_item(dialog.quick, "fieldPrompt_event_name").property("text") == "Evt name"


def test_qml_does_not_repeat_field_config_names():
    """The single-source rule: no second list of entity/field names in QML."""
    code = Path(ROOT_QML).read_text(encoding="utf-8")
    code = re.sub(r"//[^\n]*", "", code)
    literals = set(re.findall(r'"([^"\n]*)"', code))
    duplicated = literals & (
        set(FIELD_CONFIG) | {name for fields in FIELD_CONFIG.values() for name in fields}
    )
    assert not duplicated, duplicated


def test_key_field_is_masked(dialog):
    key_field = find_item(dialog.quick, "keyField")
    assert key_field.property("echoPassword") is True
    # The value stays readable for the facade, the rendered text does not.
    assert key_field.property("text") == "sk-123"
    assert key_field.property("displayText") != "sk-123"


def test_warnings_page_mentions_key_storage(dialog):
    texts = [
        i.property("text")
        for i in walk_items(find_item(dialog.quick, "warningsPage"))
        if i.property("text")
    ]
    assert any("llm_config.json" in str(text) for text in texts)


def test_connection_hint_mentions_v1(dialog):
    texts = [str(i.property("text") or "") for i in walk_items(dialog.quick.rootObject())]
    assert any("/v1" in text for text in texts)


def test_no_download_controls(dialog):
    labels = {str(i.property("text") or "") for i in walk_items(dialog.quick.rootObject())}
    assert not any("Скачать" in text or "Удалить модель" in text for text in labels)


def test_live_retheme_keeps_page_values_and_masking(qtbot, tmp_path):
    from app.infrastructure.ui_prefs.config import UiPrefsManager
    from app.presentation.theme.compiler import tokens_file_path
    from app.presentation.theme.runtime import ThemeRuntime

    runtime = ThemeRuntime(
        prefs=UiPrefsManager(tmp_path / "ui.json"),
        tokens_path=tokens_file_path(),
    )
    dlg = LlmSetupDialog(config=LlmConfig("http://localhost:11434/v1", "llama3", ""), theme=runtime)
    qtbot.addWidget(dlg)
    dlg.vm.goNext()
    dlg.vm.worldPrompt = "Мир"
    find_item(dlg.quick, "keyField").setProperty("text", "secret")
    root = dlg.quick.rootObject()

    assert runtime.toggle() is True

    assert dlg.quick.rootObject() is root
    assert dlg.vm.currentPage == 1
    assert find_item(dlg.quick, "worldPromptArea").property("text") == "Мир"
    key_field = find_item(dlg.quick, "keyField")
    assert key_field.property("text") == "secret"
    assert key_field.property("displayText") != "secret"
    assert dlg.get_connection().api_key == "secret"
