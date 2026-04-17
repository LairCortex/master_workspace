"""Tests for LlmSetupDialog — wizard navigation, download trigger, save."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QStackedWidget

from app.presentation.views.llm_setup_dialog import LlmSetupDialog


@pytest.fixture
def dialog(qtbot):
    dlg = LlmSetupDialog(
        model_downloaded=False,
        world_prompt="Test world",
        field_prompts={
            "event": {"name": "Evt name", "characteristics": "", "backstory": ""},
            "character": {"name": "Char name", "characteristics": "", "backstory": "", "personality": "", "tasks": ""},
        },
    )
    qtbot.addWidget(dlg)
    return dlg


def test_wizard_shows_download_page_first(dialog):
    assert dialog._stack.currentIndex() == 0


def test_wizard_has_8_pages(dialog):
    assert dialog.page_count == 8


def test_navigation_back_forward(dialog):
    assert dialog._stack.currentIndex() == 0
    assert not dialog._back_btn.isEnabled()

    dialog._go_next()
    assert dialog._stack.currentIndex() == 1
    assert dialog._back_btn.isEnabled()

    dialog._go_next()
    assert dialog._stack.currentIndex() == 2

    dialog._go_back()
    assert dialog._stack.currentIndex() == 1

    for _ in range(10):
        dialog._go_next()
    assert dialog._stack.currentIndex() == 7


def test_save_btn_on_last_page(dialog):
    for _ in range(7):
        dialog._go_next()
    assert dialog._stack.currentIndex() == 7
    assert not dialog._save_btn.isHidden()
    assert dialog._next_btn.isHidden()


def test_next_btn_on_non_last_page(dialog):
    assert not dialog._next_btn.isHidden()
    assert dialog._save_btn.isHidden()


def test_download_button_present(dialog):
    assert dialog._download_btn is not None
    assert not dialog._download_btn.isHidden()


def test_model_downloaded_hides_download_btn(qtbot):
    dlg = LlmSetupDialog(model_downloaded=True)
    qtbot.addWidget(dlg)
    assert dlg._download_btn.isHidden()
    assert not dlg._delete_btn.isHidden()


def test_world_prompt_saved_on_close(dialog, qtbot):
    dialog._world_prompt_edit.setPlainText("New world prompt")
    with qtbot.waitSignal(dialog.saved, timeout=1000) as blocker:
        dialog._on_save()
    world_prompt, field_prompts = blocker.args
    assert world_prompt == "New world prompt"


def test_field_prompts_page_events(dialog):
    page = dialog._field_pages["event"]
    prompts = page.get_prompts()
    assert "name" in prompts
    assert "characteristics" in prompts
    assert "backstory" in prompts
    assert len(prompts) == 3


def test_field_prompts_page_characters(dialog):
    page = dialog._field_pages["character"]
    prompts = page.get_prompts()
    assert "name" in prompts
    assert "characteristics" in prompts
    assert "backstory" in prompts
    assert "personality" in prompts
    assert "tasks" in prompts
    assert len(prompts) == 5


def test_field_prompts_page_organizations(dialog):
    page = dialog._field_pages["organization"]
    prompts = page.get_prompts()
    assert "name" in prompts
    assert "characteristics" in prompts
    assert "backstory" in prompts
    assert "tasks" in prompts
    assert len(prompts) == 4


def test_field_prompts_page_items(dialog):
    page = dialog._field_pages["item"]
    prompts = page.get_prompts()
    assert "name" in prompts
    assert "characteristics" in prompts
    assert "backstory" in prompts
    assert len(prompts) == 3


def test_field_prompts_page_locations(dialog):
    page = dialog._field_pages["location"]
    prompts = page.get_prompts()
    assert "name" in prompts
    assert "characteristics" in prompts
    assert "backstory" in prompts
    assert "tasks" in prompts
    assert len(prompts) == 4


def test_field_prompts_prefilled_on_reopen(dialog):
    page = dialog._field_pages["event"]
    prompts = page.get_prompts()
    assert prompts["name"] == "Evt name"


def test_field_prompts_saved_on_close(dialog, qtbot):
    dialog._field_pages["item"]._inputs["name"].setText("Magic item name")
    with qtbot.waitSignal(dialog.saved, timeout=1000) as blocker:
        dialog._on_save()
    _, field_prompts = blocker.args
    assert field_prompts["item"]["name"] == "Magic item name"


def test_warnings_displayed(dialog):
    for _ in range(7):
        dialog._go_next()
    page = dialog._warnings_page
    labels = [
        child.text()
        for child in page.findChildren(type(dialog._model_info))
        if hasattr(child, "text") and child.text()
    ]
    full_text = " ".join(labels)
    assert "оперативной памяти" in full_text or "RAM" in full_text or "10 ГБ" in full_text


def test_get_world_prompt(dialog):
    dialog._world_prompt_edit.setPlainText("My world")
    assert dialog.get_world_prompt() == "My world"


def test_get_field_prompts(dialog):
    result = dialog.get_field_prompts()
    assert "event" in result
    assert "character" in result
    assert "item" in result
    assert "location" in result
    assert "organization" in result
