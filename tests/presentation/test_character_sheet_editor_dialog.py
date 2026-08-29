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
from PySide6.QtGui import QKeySequence
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


# ── A-editor: Правка menu + snap / z-order ─────────────────────────────────

async def test_edit_menu_standard_shortcuts(dlg):
    titles = [a.text() for a in dlg.edit_menu.actions() if not a.isSeparator()]
    assert titles == [
        "Отменить", "Повторить", "Копировать", "Вставить", "Дублировать",
    ]
    assert dlg.undo_action.shortcut() == QKeySequence(QKeySequence.StandardKey.Undo)
    assert dlg.redo_action.shortcut() == QKeySequence(QKeySequence.StandardKey.Redo)
    assert dlg.copy_action.shortcut() == QKeySequence(QKeySequence.StandardKey.Copy)
    assert dlg.paste_action.shortcut() == QKeySequence(QKeySequence.StandardKey.Paste)
    assert dlg.duplicate_action.shortcut() == QKeySequence("Ctrl+D")


async def test_copy_enables_paste_action(dlg):
    assert dlg.paste_action.isEnabled() is False
    vm = dlg.view_model
    fid = vm.place(FieldType.TEXT, 10.0, 10.0)
    vm.select(fid)
    dlg.copy_action.trigger()
    assert dlg.paste_action.isEnabled() is True


async def test_panel_content_is_one_undo_step(dlg, qtbot):
    vm = dlg.view_model
    fid = vm.place(FieldType.TEXT, 10.0, 10.0)
    await vm.save()
    panel = dlg.properties_panel
    vm.select(fid)
    panel.content_edit.setPlainText("а")
    panel.content_edit.setPlainText("аб")
    panel.content_edit.setPlainText("абв")
    panel.content_edit.clearFocus()
    qtbot.wait(10)
    vm.undo()
    assert vm.template.get_field(fid).content == ""


async def test_snap_toggle_and_z_order_buttons(dlg):
    vm = dlg.view_model
    assert dlg.snap_check is not None
    assert dlg.snap_check.isChecked() is False
    assert vm.snap_enabled is False

    dlg.snap_check.setChecked(True)
    assert vm.snap_enabled is True

    a = vm.place(FieldType.LABEL, 10.0, 10.0)
    b = vm.place(FieldType.TEXT, 20.0, 20.0)
    vm.select(a)
    dlg.bring_front_button.click()
    assert [f.id for f in vm.template.page.fields] == [b, a]
    dlg.send_back_button.click()
    assert [f.id for f in vm.template.page.fields] == [a, b]


# ── PDF export (add-character-sheet-p) ──────────────────────────────────

async def test_export_pdf_button_next_to_save(dlg):
    assert dlg.export_pdf_button.text() == "Экспорт в PDF…"
    bottom = dlg.layout().itemAt(dlg.layout().count() - 1).layout()
    widgets = [
        bottom.itemAt(i).widget()
        for i in range(bottom.count())
        if bottom.itemAt(i).widget() is not None
    ]
    assert widgets.index(dlg.export_pdf_button) == widgets.index(dlg.save_button) - 1


async def test_export_pdf_cancel_does_not_write(dlg, monkeypatch):
    calls: list = []
    monkeypatch.setattr(
        "app.presentation.views.character_sheet.editor_dialog.QFileDialog.getSaveFileName",
        staticmethod(lambda *a, **k: ("", "")),
    )
    monkeypatch.setattr(
        "app.presentation.views.character_sheet.editor_dialog.write_sheet_pdf",
        lambda *a, **k: calls.append(1),
    )
    dlg.export_pdf_button.click()
    await asyncio.sleep(0.05)
    assert calls == []


async def test_export_pdf_suggested_name(dlg, monkeypatch):
    captured: dict = {}

    def fake_save(parent, caption, directory="", filter=""):
        captured["directory"] = directory
        captured["filter"] = filter
        return "", ""

    monkeypatch.setattr(
        "app.presentation.views.character_sheet.editor_dialog.QFileDialog.getSaveFileName",
        staticmethod(fake_save),
    )
    dlg.export_pdf_button.click()
    await asyncio.sleep(0.05)
    assert captured["directory"].endswith("Лист героя.pdf")
    assert "pdf" in captured["filter"].lower()


async def test_export_pdf_uses_dirty_canvas(dlg, monkeypatch, tmp_path):
    written: list = []

    def fake_save(parent, caption, directory="", filter=""):
        return str(tmp_path / "out.pdf"), "PDF (*.pdf)"

    def fake_write(template, dest, images):
        written.append((template, dest, dict(images)))

    monkeypatch.setattr(
        "app.presentation.views.character_sheet.editor_dialog.QFileDialog.getSaveFileName",
        staticmethod(fake_save),
    )
    monkeypatch.setattr(
        "app.presentation.views.character_sheet.editor_dialog.write_sheet_pdf",
        fake_write,
    )
    fid = dlg.view_model.place(FieldType.LABEL, 10.0, 10.0)
    dlg.view_model.set_content(fid, "Черновик")
    dlg.export_pdf_button.click()
    await asyncio.sleep(0.05)
    assert written
    template, dest, images = written[0]
    assert template.get_field(fid).content == "Черновик"
    assert images == {}


async def test_export_pdf_oserror_shows_box(dlg, monkeypatch, save_boxes, qtbot):
    monkeypatch.setattr(
        "app.presentation.views.character_sheet.editor_dialog.QFileDialog.getSaveFileName",
        staticmethod(lambda *a, **k: ("/tmp/out.pdf", "PDF (*.pdf)")),
    )
    monkeypatch.setattr(
        "app.presentation.views.character_sheet.editor_dialog.write_sheet_pdf",
        lambda *a, **k: (_ for _ in ()).throw(OSError("нет места")),
    )
    dlg.export_pdf_button.click()
    await asyncio.sleep(0.05)
    await _wait_boxes(save_boxes, qtbot, 1)


async def test_export_pdf_collects_image_bytes(qtbot, service, row, monkeypatch, tmp_path):
    orig = tmp_path / "orig.png"
    orig.write_bytes(b"PNGDATA")

    class Store:
        async def original_file_path(self, image_id):
            return orig if image_id == 7 else None

        async def preview_file_path(self, image_id):
            return None

    written: list = []
    monkeypatch.setattr(
        "app.presentation.views.character_sheet.editor_dialog.QFileDialog.getSaveFileName",
        staticmethod(lambda *a, **k: (str(tmp_path / "x.pdf"), "PDF")),
    )
    monkeypatch.setattr(
        "app.presentation.views.character_sheet.editor_dialog.write_sheet_pdf",
        lambda template, dest, images: written.append(dict(images)),
    )
    d = CharacterSheetEditorDialog(service, row.id, image_store=Store())
    await d.load()
    fid = d.view_model.place(FieldType.IMAGE, 10.0, 10.0)
    d.view_model.set_image_id(fid, 7)
    d.export_pdf_button.click()
    await asyncio.sleep(0.05)
    assert written[0][7] == b"PNGDATA"
    d.force_close()
    d.deleteLater()
    qtbot.wait(1)


async def test_export_pdf_preview_and_unreadable(qtbot, service, row, monkeypatch, tmp_path):
    preview = tmp_path / "prev.png"
    preview.write_bytes(b"PREV")
    missing = tmp_path / "gone.png"

    class Store:
        async def original_file_path(self, image_id):
            if image_id == 1:
                return None
            if image_id == 2:
                return missing
            return None

        async def preview_file_path(self, image_id):
            if image_id == 1:
                return preview
            return None

    written: list = []
    monkeypatch.setattr(
        "app.presentation.views.character_sheet.editor_dialog.QFileDialog.getSaveFileName",
        staticmethod(lambda *a, **k: (str(tmp_path / "x.pdf"), "PDF")),
    )
    monkeypatch.setattr(
        "app.presentation.views.character_sheet.editor_dialog.write_sheet_pdf",
        lambda template, dest, images: written.append(dict(images)),
    )
    d = CharacterSheetEditorDialog(service, row.id, image_store=Store())
    await d.load()
    a = d.view_model.place(FieldType.IMAGE, 10.0, 10.0)
    b = d.view_model.place(FieldType.IMAGE, 40.0, 10.0)
    c = d.view_model.place(FieldType.IMAGE, 70.0, 10.0)
    d.view_model.set_image_id(a, 1)
    d.view_model.set_image_id(b, 2)
    d.view_model.set_image_id(c, 3)
    d.export_pdf_button.click()
    await asyncio.sleep(0.05)
    assert written[0] == {1: b"PREV"}
    d.force_close()
    d.deleteLater()
    qtbot.wait(1)


async def test_export_pdf_no_op_without_template(qtbot, service, row, monkeypatch):
    calls: list = []
    monkeypatch.setattr(
        "app.presentation.views.character_sheet.editor_dialog.QFileDialog.getSaveFileName",
        staticmethod(lambda *a, **k: calls.append("picker") or ("/x.pdf", "PDF")),
    )
    d = CharacterSheetEditorDialog(service, row.id)
    d.export_pdf_button.click()
    await asyncio.sleep(0.05)
    assert calls == []
    d.force_close()
    d.deleteLater()
    qtbot.wait(1)

