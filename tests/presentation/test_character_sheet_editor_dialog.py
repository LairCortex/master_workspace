"""Tests for the character-sheet editor window (task 6.3 of add-character-sheet-a1).

One non-modal window per sheet: palette | canvas | properties + explicit
«Сохранить». The VM (own instance per window) is the only layout buffer;
close-with-dirty asks for confirmation; an external rename updates the title
without touching the dirty flag.
"""
from __future__ import annotations

import asyncio
import json
import time

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from app.application.services.character_sheet_service import CharacterSheetService
from app.domain.enums.field_type import FieldType
from app.infrastructure.repositories.character_sheet_repository import (
    CharacterSheetRepository,
)
from app.presentation.views.character_sheet.editor_dialog import (
    CharacterSheetEditorDialog,
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def service(async_session):
    return CharacterSheetService(CharacterSheetRepository(async_session))


@pytest.fixture
async def row(service):
    return await service.create("Лист героя")


@pytest.fixture
def confirm(monkeypatch) -> dict:
    """Stub QMessageBox.question: return state["answer"]; calls recorded."""
    state: dict = {"answer": QMessageBox.StandardButton.Yes, "calls": []}

    def fake_question(parent, title, text, *args, **kwargs):
        state["calls"].append((title, text))
        return state["answer"]

    monkeypatch.setattr(QMessageBox, "question", staticmethod(fake_question))
    return state


@pytest.fixture
async def dlg(qtbot, service, row):
    d = CharacterSheetEditorDialog(service, row.id)
    d.resize(1200, 800)
    await d.load()
    d.show()
    yield d
    # force_close: some tests leave the window open and dirty (no prompt in teardown)
    d.force_close()
    d.deleteLater()  # a closed dialog otherwise lingers as a top-level widget
    qtbot.wait(1)


def _pages_fields(row) -> list:
    pages = json.loads(row.pages)
    return pages[0]["fields"]


# ── title / layout ─────────────────────────────────────────────────────────

async def test_title_is_sheet_name(dlg):
    assert dlg.windowTitle() == "Лист героя"


async def test_editor_has_palette_canvas_panel_and_save(dlg):
    assert dlg.palette is not None
    assert dlg.canvas is not None
    assert dlg.properties_panel is not None
    assert dlg.save_button is not None
    assert dlg.canvas.item_count() == 0        # fresh sheet: empty A4 page


# ── saving ─────────────────────────────────────────────────────────────────

async def test_save_writes_layout_and_clears_dirty(dlg, service):
    vm = dlg.view_model
    fid = vm.place(FieldType.TEXT, 50, 60)
    vm.set_content(fid, "имя персонажа")
    assert vm.dirty is True

    dlg.save_button.click()
    await asyncio.sleep(0.05)
    for _ in range(50):
        if not vm.dirty:
            break
        await asyncio.sleep(0)

    assert vm.dirty is False
    row = await service._repo.get_by_id(vm.sheet_id)
    fields = _pages_fields(row)
    assert len(fields) == 1
    assert fields[0]["id"] == fid
    assert fields[0]["content"] == "имя персонажа"


# ── save failure must be surfaced, never swallowed ─────────────────────────

@pytest.fixture
def save_boxes(monkeypatch) -> list[tuple[str, str]]:
    """Record QMessageBox.warning/critical (save error path)."""
    boxes: list[tuple[str, str]] = []

    def _record(kind: str, parent, title: str, text: str, *args, **kwargs):
        boxes.append((kind, text))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: _record("warning", *a, **k)))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: _record("critical", *a, **k)))
    return boxes


async def _wait_boxes(boxes, qtbot, n: int) -> None:
    for _ in range(100):
        if len(boxes) >= n:
            return
        await asyncio.sleep(0.02)
        qtbot.wait(1)
    raise AssertionError(f"expected {n} message boxes, got {boxes}")


async def test_save_failure_shows_warning_and_keeps_dirty(dlg, service, save_boxes, qtbot, monkeypatch):
    from app.application.services.character_sheet_service import CharacterSheetError

    async def broken(sheet_id, template):
        raise CharacterSheetError("тестовый сбой базы")

    # the dialog's VM shares this service instance
    monkeypatch.setattr(service, "update_pages", broken)

    vm = dlg.view_model
    vm.place(FieldType.LABEL, 10, 10)         # dirty
    dlg.save_button.click()
    await _wait_boxes(save_boxes, qtbot, 1)

    assert save_boxes[0] == ("warning", "тестовый сбой базы")
    assert vm.dirty is True                   # the layout is still unsaved


async def test_save_unexpected_error_shows_critical(dlg, service, save_boxes, qtbot, monkeypatch):
    async def explode(sheet_id, template):
        raise RuntimeError("io fail")

    monkeypatch.setattr(service, "update_pages", explode)

    vm = dlg.view_model
    vm.place(FieldType.LABEL, 10, 10)
    dlg.save_button.click()
    await _wait_boxes(save_boxes, qtbot, 1)

    assert save_boxes[0][0] == "critical"
    assert "Не удалось сохранить" in save_boxes[0][1]
    assert vm.dirty is True


# ── close with unsaved changes ─────────────────────────────────────────────

async def test_close_dirty_no_confirmation_keeps_window(dlg, service, confirm, qtbot):
    vm = dlg.view_model
    row = await service._repo.get_by_id(vm.sheet_id)
    pages_before = row.pages

    fid = vm.place(FieldType.TEXT, 50, 60)   # dirty
    confirm["answer"] = QMessageBox.StandardButton.No
    dlg.close()
    qtbot.wait(10)

    assert dlg.isVisible(), "decline must keep the editor open"
    assert vm.dirty is True
    row = await service._repo.get_by_id(vm.sheet_id)
    assert row.pages == pages_before          # nothing was written


async def test_close_dirty_with_confirmation_closes_without_save(dlg, service, confirm, qtbot):
    vm = dlg.view_model
    row = await service._repo.get_by_id(vm.sheet_id)
    pages_before = row.pages

    vm.place(FieldType.TEXT, 50, 60)         # dirty
    confirm["answer"] = QMessageBox.StandardButton.Yes
    dlg.close()
    qtbot.wait(10)

    assert not dlg.isVisible()
    assert confirm["calls"], "the user was asked for confirmation"
    row = await service._repo.get_by_id(vm.sheet_id)
    assert row.pages == pages_before          # agreement closes WITHOUT saving


async def test_close_not_dirty_closes_silently(dlg, confirm, qtbot):
    assert not confirm["calls"]
    dlg.close()
    qtbot.wait(10)
    assert not dlg.isVisible()
    assert confirm["calls"] == []             # no prompt for a clean layout


# ── external rename ────────────────────────────────────────────────────────

async def test_external_rename_updates_title_not_dirty(dlg):
    vm = dlg.view_model
    assert vm.dirty is False
    vm.place(FieldType.LABEL, 10, 10)        # dirty
    assert vm.dirty is True

    dlg.set_name("Переименован из списка")

    assert dlg.windowTitle() == "Переименован из списка"
    assert vm.template.name == "Переименован из списка"
    assert vm.dirty is True                  # rename is not a layout edit


async def test_set_name_before_load_is_noop(qtbot, service, row):
    d = CharacterSheetEditorDialog(service, row.id)
    d.set_name("Раньше загрузки")            # nothing loaded yet: ignored
    assert d.windowTitle() != "Раньше загрузки"
    d.close()
    d.deleteLater()
    qtbot.wait(1)
