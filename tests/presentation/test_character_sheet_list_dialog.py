"""Widget tests for the character sheet list dialog (task 7.1).

The dialog's DB work is scheduled with ``ensure_future`` (app-wide qasync
pattern), so every test is an async function running on the test loop.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QMessageBox,
)

from app.application.services.character_sheet_service import (
    CharacterSheetImportError,
    CharacterSheetNameConflict,
    CharacterSheetService,
)
from app.domain.entities.character_sheet import SheetPage, SheetTemplate
from app.domain.enums.sheet_orientation import SheetOrientation
from app.presentation.views.character_sheet.list_dialog import CharacterSheetListDialog


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


async def spin(times: int = 10) -> None:
    for _ in range(times):
        await asyncio.sleep(0)


def make_row(name: str, sheet_id: int):
    return SimpleNamespace(id=sheet_id, name=name, orientation="landscape", pages="[]")


def make_service(rows=()):
    service = AsyncMock(spec=CharacterSheetService)
    service.get_all = AsyncMock(return_value=list(rows))
    return service


async def open_dialog(service) -> CharacterSheetListDialog:
    dialog = CharacterSheetListDialog(service)
    await spin()  # initial refresh completed
    return dialog


def select_row(dialog, index: int) -> None:
    dialog._list.setCurrentRow(index)


# ── list refresh / open ─────────────────────────────────────────────────────


class TestRefreshOpen:
    async def test_refresh_lists_templates(self, qapp):
        service = make_service([make_row("Лист A", 1), make_row("Лист B", 2)])
        dialog = await open_dialog(service)
        assert dialog._list.count() == 2
        assert dialog._list.item(0).text() == "Лист A"
        assert dialog._list.item(0).data(Qt.ItemDataRole.UserRole) == 1
        assert dialog._list.item(1).data(Qt.ItemDataRole.UserRole) == 2

    async def test_open_selected_emits_id(self, qapp):
        service = make_service([make_row("Лист A", 7)])
        dialog = await open_dialog(service)
        opened: list[int] = []
        dialog.open_requested.connect(opened.append)
        select_row(dialog, 0)
        dialog._open_btn.click()
        assert opened == [7]

    async def test_open_selected_without_selection_is_noop(self, qapp):
        dialog = await open_dialog(make_service())
        opened: list[int] = []
        dialog.open_requested.connect(opened.append)
        dialog._open_btn.click()
        assert opened == []

    async def test_double_click_opens(self, qapp):
        service = make_service([make_row("Лист A", 3)])
        dialog = await open_dialog(service)
        opened: list[int] = []
        dialog.open_requested.connect(opened.append)
        select_row(dialog, 0)  # a real double-click selects the item first
        dialog._list.itemDoubleClicked.emit(dialog._list.item(0))
        assert opened == [3]


# ── create ──────────────────────────────────────────────────────────────────


class TestCreate:
    async def test_create_cancelled_input(self, qapp, monkeypatch):
        monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("", False)))
        service = make_service()
        dialog = await open_dialog(service)
        dialog._create_btn.click()
        await spin()
        service.create.assert_not_awaited()
        assert dialog._list.count() == 0

    async def test_create_empty_name(self, qapp, monkeypatch):
        monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("   ", True)))
        service = make_service()
        dialog = await open_dialog(service)
        dialog._create_btn.click()
        await spin()
        service.create.assert_not_awaited()

    async def test_create_success_selects_the_new_row(self, qapp, monkeypatch):
        monkeypatch.setattr(
            QInputDialog, "getText", staticmethod(lambda *a, **k: ("Новый лист", True)),
        )
        created_row = make_row("Новый лист", 42)
        service = make_service()
        service.create = AsyncMock(return_value=created_row)
        service.get_all = AsyncMock(return_value=[created_row])  # reload after create
        dialog = await open_dialog(service)
        dialog._create_btn.click()
        await spin()
        service.create.assert_awaited_once()
        template = service.create.await_args.args[0]
        assert template.name == "Новый лист"
        assert template.orientation is SheetOrientation.LANDSCAPE
        assert len(template.pages) == 1
        assert dialog._list.count() == 1
        assert dialog._list.currentRow() == 0  # the new row is selected

    async def test_create_name_conflict_shows_warning(self, qapp, monkeypatch):
        monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Есть", True)))
        service = make_service()
        service.create = AsyncMock(side_effect=CharacterSheetNameConflict("Есть"))
        boxes: list[tuple] = []
        monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: boxes.append(a)))
        dialog = await open_dialog(service)
        dialog._create_btn.click()
        await spin()
        assert any("Есть" in text for box in boxes for text in box if isinstance(text, str))
        assert dialog._list.count() == 0


# ── delete ──────────────────────────────────────────────────────────────────


class TestDelete:
    async def test_delete_without_selection_is_noop(self, qapp):
        service = make_service()
        dialog = await open_dialog(service)
        dialog._delete_btn.click()
        await spin()
        service.delete.assert_not_awaited()

    async def test_delete_declined_keeps_the_row(self, qapp, monkeypatch):
        monkeypatch.setattr(
            QMessageBox, "question",
            staticmethod(lambda *a, **k: QMessageBox.StandardButton.No),
        )
        service = make_service([make_row("Лист A", 1)])
        dialog = await open_dialog(service)
        select_row(dialog, 0)
        dialog._delete_btn.click()
        await spin()
        service.delete.assert_not_awaited()
        assert dialog._list.count() == 1

    async def test_delete_confirmed_refreshes_the_list(self, qapp, monkeypatch):
        monkeypatch.setattr(
            QMessageBox, "question",
            staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
        )
        first_load = [make_row("Лист A", 1)]
        service = make_service(first_load)
        service.get_all = AsyncMock(side_effect=[[r for r in first_load], []])
        service.delete = AsyncMock(return_value=True)
        dialog = await open_dialog(service)
        select_row(dialog, 0)
        dialog._delete_btn.click()
        await spin()
        service.delete.assert_awaited_once_with(1)
        assert dialog._list.count() == 0


# ── JSON export ─────────────────────────────────────────────────────────────

_TEMPLATE = SheetTemplate(
    name="Лист 1",
    orientation=SheetOrientation.LANDSCAPE,
    pages=[SheetPage(name="Стр 1")],
)


async def _dialog_with_selected_sheet(qapp, monkeypatch) -> tuple[CharacterSheetListDialog, AsyncMock]:
    service = make_service([make_row("Лист 1", 1)])
    service.load = AsyncMock(return_value=_TEMPLATE)
    dialog = await open_dialog(service)
    select_row(dialog, 0)
    return dialog, service


class TestExport:
    async def test_export_without_selection_is_noop(self, qapp):
        service = make_service()
        dialog = await open_dialog(service)
        dialog._export_btn.click()
        await spin()
        service.load.assert_not_awaited()

    async def test_export_loaded_sheet_gone_is_noop(self, qapp, monkeypatch):
        dialog = await open_dialog(make_service([make_row("Лист 1", 1)]))
        dialog._service.load = AsyncMock(return_value=None)
        select_row(dialog, 0)
        save_calls: list = []
        monkeypatch.setattr(
            QFileDialog, "getSaveFileName",
            staticmethod(lambda *a, **k: save_calls.append(1)),
        )
        dialog._export_btn.click()
        await spin()
        assert not save_calls  # the row vanished → no file dialog is shown

    async def test_export_cancelled_dialog(self, qapp, monkeypatch):
        dialog, _service = await _dialog_with_selected_sheet(qapp, monkeypatch)
        monkeypatch.setattr(
            QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", "")),
        )
        infos: list[tuple] = []
        monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: infos.append(a)))
        dialog._export_btn.click()
        await spin()
        assert not infos  # cancelled picker → no success box

    async def test_export_writes_project_json(self, qapp, monkeypatch, tmp_path):
        dest = tmp_path / "sheet.json"
        dialog, _service = await _dialog_with_selected_sheet(qapp, monkeypatch)
        monkeypatch.setattr(
            QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(dest), "")),
        )
        monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
        dialog._export_btn.click()
        await spin()
        assert dest.exists()
        payload = json.loads(dest.read_text(encoding="utf-8"))
        assert payload["format"] == "nri-charsheet"
        assert payload["version"] == 1
        assert payload["sheets"][0]["name"] == "Лист 1"

    async def test_export_write_failure_shows_critical(self, qapp, monkeypatch):
        dialog, _service = await _dialog_with_selected_sheet(qapp, monkeypatch)
        monkeypatch.setattr(
            QFileDialog, "getSaveFileName",
            staticmethod(lambda *a, **k: ("/no/such/dir/sheet.json", "")),
        )
        criticals: list[tuple] = []
        monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: criticals.append(a)))
        dialog._export_btn.click()
        await spin()
        assert criticals


# ── JSON import ─────────────────────────────────────────────────────────────


class TestImport:
    async def test_import_cancelled_dialog(self, qapp, monkeypatch):
        monkeypatch.setattr(
            QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", "")),
        )
        service = make_service()
        dialog = await open_dialog(service)
        dialog._import_btn.click()
        await spin()
        service.import_project.assert_not_awaited()

    async def test_import_unreadable_file_shows_critical(self, qapp, monkeypatch, tmp_path):
        missing = tmp_path / "missing.json"
        monkeypatch.setattr(
            QFileDialog, "getOpenFileName",
            staticmethod(lambda *a, **k: (str(missing), "")),
        )
        service = make_service()
        dialog = await open_dialog(service)
        criticals: list[tuple] = []
        monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: criticals.append(a)))
        dialog._import_btn.click()
        await spin()
        assert criticals
        service.import_project.assert_not_awaited()

    async def test_import_invalid_project_shows_reason(self, qapp, monkeypatch, tmp_path):
        src = tmp_path / "bad.json"
        src.write_text("не json", encoding="utf-8")
        monkeypatch.setattr(
            QFileDialog, "getOpenFileName",
            staticmethod(lambda *a, **k: (str(src), "")),
        )
        service = make_service()
        service.import_project = AsyncMock(
            side_effect=CharacterSheetImportError("файл не является корректным JSON"),
        )
        dialog = await open_dialog(service)
        warnings: list[tuple] = []
        monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warnings.append(a)))
        dialog._import_btn.click()
        await spin()
        assert any("корректным JSON" in str(part) for box in warnings for part in box)

    async def test_import_success_shows_count_and_refreshes(self, qapp, monkeypatch, tmp_path):
        src = tmp_path / "project.json"
        src.write_text(CharacterSheetService.export_project([_TEMPLATE]), encoding="utf-8")
        monkeypatch.setattr(
            QFileDialog, "getOpenFileName",
            staticmethod(lambda *a, **k: (str(src), "")),
        )
        imported_row = make_row("Лист 1", 11)
        service = make_service()
        service.import_project = AsyncMock(return_value=[imported_row])
        service.get_all = AsyncMock(side_effect=[[], [imported_row]])
        dialog = await open_dialog(service)
        infos: list[tuple] = []
        monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: infos.append(a)))
        dialog._import_btn.click()
        await spin()
        service.import_project.assert_awaited_once()
        assert dialog._list.count() == 1
        assert dialog._list.item(0).text() == "Лист 1"
        assert any("Импортировано" in str(part) for box in infos for part in box)
