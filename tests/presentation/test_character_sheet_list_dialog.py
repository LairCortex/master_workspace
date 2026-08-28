"""Tests for the character-sheet list dialog (task 6.1 of add-character-sheet-a1).

Real in-memory DB + real service; modal helpers (QInputDialog / QMessageBox)
are stubbed. The dialog is non-modal; its async flows are triggered through
the buttons and pumped.
"""
from __future__ import annotations

import asyncio
import time

import pytest
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

from app.application.services.character_sheet_service import (
    CharacterSheetError,
    CharacterSheetService,
    NameConflictError,
)
from app.domain.entities.character_sheet import EMPTY_PAGES_JSON
from app.infrastructure.repositories.character_sheet_repository import (
    CharacterSheetRepository,
)
from app.presentation.views.character_sheet.list_dialog import CharacterSheetListDialog


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
def dialog_input(monkeypatch) -> dict:
    """Stub QInputDialog.getText: state["answer"] = (text, ok)."""
    state: dict = {"answer": ("", False)}

    def fake_get_text(*args, **kwargs):
        return state["answer"]

    monkeypatch.setattr(QInputDialog, "getText", staticmethod(fake_get_text))
    return state


@pytest.fixture
def confirm(monkeypatch) -> dict:
    """Stub QMessageBox.question: return state["answer"]; calls are recorded."""
    state: dict = {"answer": QMessageBox.StandardButton.Yes, "calls": []}

    def fake_question(parent, title, text, *args, **kwargs):
        state["calls"].append((title, text))
        return state["answer"]

    monkeypatch.setattr(QMessageBox, "question", staticmethod(fake_question))
    return state


@pytest.fixture
def boxes(monkeypatch) -> list:
    """Record-and-dismiss QMessageBox.information/warning/critical."""
    recorded: list = []

    def _dismiss(kind, parent, title, text, *args, **kwargs):
        recorded.append((kind, title, text))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: _dismiss("information", *a, **k)))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: _dismiss("warning", *a, **k)))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: _dismiss("critical", *a, **k)))
    return recorded


@pytest.fixture
def dlg(qtbot, service):
    d = CharacterSheetListDialog(service)
    d.resize(420, 520)
    d.show()
    qtbot.wait(10)
    yield d
    d.close()
    d.deleteLater()  # a closed dialog otherwise lingers as a top-level widget
    qtbot.wait(1)


def _first_text(dlg) -> str | None:
    return dlg.list_widget.item(0).text() if dlg.list_widget.count() > 0 else None


async def pump(qtbot, until, timeout: float = 3.0) -> None:
    """Pump the asyncio loop + Qt loop until ``until()`` is true."""
    t0 = time.perf_counter()
    while not until():
        if time.perf_counter() - t0 > timeout:
            raise TimeoutError("pump: condition not met")
        await asyncio.sleep(0)
        qtbot.wait(1)


async def create_via_service(service, name):
    return await service.create(name)


# ── create ─────────────────────────────────────────────────────────────────

async def test_create_adds_row_and_db_record(dlg, service, dialog_input, qtbot):
    opened = []
    dlg.open_requested.connect(opened.append)
    await dlg.refresh()
    assert dlg.list_widget.count() == 0

    dialog_input["answer"] = ("Персонаж", True)
    dlg.create_button.click()
    await pump(qtbot, lambda: dlg.list_widget.count() == 1)

    assert dlg.list_widget.item(0).text() == "Персонаж"
    row = await service._repo.get_by_name("Персонаж")
    assert row is not None
    assert row.pages == EMPTY_PAGES_JSON      # empty single page written at create
    assert row.schema_version == 2            # A-playable: new sheets are v2
    assert opened == [row.id]                 # the app opens the freshly created sheet


async def test_create_empty_name_refused(dlg, service, dialog_input, boxes, qtbot):
    await dlg.refresh()
    dialog_input["answer"] = ("   ", True)
    dlg.create_button.click()
    await pump(qtbot, lambda: any(k == "warning" for k, *_ in boxes))
    assert dlg.list_widget.count() == 0
    assert len(await service.list_sheets()) == 0


async def test_create_name_conflict_rejected(dlg, service, dialog_input, boxes, qtbot):
    await create_via_service(service, "Занято")
    await dlg.refresh()

    dialog_input["answer"] = ("Занято", True)
    dlg.create_button.click()
    await pump(qtbot, lambda: any("Занято" in text for _, _, text in boxes))

    assert dlg.list_widget.count() == 1                    # no duplicate row
    names = [dlg.list_widget.item(i).text() for i in range(dlg.list_widget.count())]
    assert names == ["Занято"]
    rows = await service.list_sheets()
    assert [r.name for r in rows] == ["Занято"]            # nothing new in the DB


async def test_create_input_cancelled(dlg, service, dialog_input, qtbot):
    dialog_input["answer"] = ("Не создавалось", False)
    dlg.create_button.click()
    await asyncio.sleep(0.05)
    qtbot.wait(10)
    assert len(await service.list_sheets()) == 0


# ── rename ─────────────────────────────────────────────────────────────────

async def test_rename_updates_db_immediately(dlg, service, dialog_input, qtbot):
    row = await create_via_service(service, "Старое имя")
    await dlg.refresh()
    dlg.list_widget.setCurrentRow(0)

    pages_before = (await service._repo.get_by_id(row.id)).pages
    dialog_input["answer"] = ("Новое имя", True)
    dlg.rename_button.click()
    await pump(qtbot, lambda: _first_text(dlg) == "Новое имя")

    row2 = await service._repo.get_by_id(row.id)
    assert row2.name == "Новое имя"
    assert row2.pages == pages_before       # rename never touches the layout


async def test_rename_conflict_keeps_old_name(dlg, service, dialog_input, boxes, qtbot):
    await create_via_service(service, "А")
    await create_via_service(service, "В")
    await dlg.refresh()
    dlg.list_widget.setCurrentRow(0)   # "А"

    dialog_input["answer"] = ("В", True)
    dlg.rename_button.click()
    await pump(qtbot, lambda: any("В" in text for _, _, text in boxes))

    rows = await service.list_sheets()
    assert sorted(r.name for r in rows) == ["А", "В"]     # nothing renamed
    dlg.list_widget.blockSignals(True)
    dlg.list_widget.clear()
    dlg.list_widget.blockSignals(False)
    await dlg.refresh()
    names = [dlg.list_widget.item(i).text() for i in range(dlg.list_widget.count())]
    assert "В" in names and "А" in names


# ── delete ─────────────────────────────────────────────────────────────────

async def test_delete_with_confirmation(dlg, service, dialog_input, confirm, qtbot):
    row = await create_via_service(service, "Удалить меня")
    await dlg.refresh()
    dlg.list_widget.setCurrentRow(0)

    dlg.delete_button.click()
    await pump(qtbot, lambda: dlg.list_widget.count() == 0)

    assert (await service._repo.get_by_id(row.id)) is None
    assert confirm["calls"], "a confirmation dialog was shown"


async def test_delete_refused_keeps_sheet(dlg, service, dialog_input, confirm, qtbot):
    row = await create_via_service(service, "Осталось")
    await dlg.refresh()
    dlg.list_widget.setCurrentRow(0)

    confirm["answer"] = QMessageBox.StandardButton.No
    dlg.delete_button.click()
    await asyncio.sleep(0.05)
    qtbot.wait(10)

    assert dlg.list_widget.count() == 1
    assert (await service._repo.get_by_id(row.id)) is not None


async def test_delete_of_open_sheet_is_unavailable(dlg, service, dialog_input, qtbot):
    opened = await create_via_service(service, "Открыт")
    other = await create_via_service(service, "Другой")
    await dlg.refresh()
    dlg.set_open_sheet_id(opened.id)

    dlg.list_widget.blockSignals(True)
    for i in range(dlg.list_widget.count()):
        if dlg.list_widget.item(i).text() == "Открыт":
            dlg.list_widget.setCurrentRow(i)
    dlg.list_widget.blockSignals(False)
    dlg._sync_delete_enabled()
    assert not dlg.delete_button.isEnabled()

    dlg.list_widget.blockSignals(True)
    for i in range(dlg.list_widget.count()):
        if dlg.list_widget.item(i).text() == "Другой":
            dlg.list_widget.setCurrentRow(i)
    dlg.list_widget.blockSignals(False)
    dlg._sync_delete_enabled()
    assert dlg.delete_button.isEnabled()

    # and the async flow itself refuses the open id even if forced
    dlg.set_open_sheet_id(opened.id)
    dlg.list_widget.blockSignals(True)
    for i in range(dlg.list_widget.count()):
        if dlg.list_widget.item(i).text() == "Открыт":
            dlg.list_widget.setCurrentRow(i)
    dlg.list_widget.blockSignals(False)
    await dlg.delete_sheet()
    assert (await service._repo.get_by_id(opened.id)) is not None


# ── open ───────────────────────────────────────────────────────────────────

async def test_open_emits_requested(dlg, service, qtbot):
    row = await create_via_service(service, "Открыть")
    opened = []
    dlg.open_requested.connect(opened.append)
    await dlg.refresh()
    dlg.list_widget.setCurrentRow(0)

    dlg.open_button.click()
    await pump(qtbot, lambda: opened)
    assert opened == [row.id]


# ── edge guards ────────────────────────────────────────────────────────────

async def test_open_without_selection_does_nothing(dlg, qtbot):
    opened = []
    dlg.open_requested.connect(opened.append)
    await dlg.refresh()
    dlg.open_button.click()
    await asyncio.sleep(0.05)
    qtbot.wait(10)
    assert opened == []


async def test_rename_without_selection_does_nothing(dlg, service, dialog_input, boxes, qtbot):
    await create_via_service(service, "Целое")
    await dlg.refresh()
    dialog_input["answer"] = ("Взлом", True)
    dlg.rename_button.click()
    await asyncio.sleep(0.05)
    qtbot.wait(10)
    rows = await service.list_sheets()
    assert [r.name for r in rows] == ["Целое"]
    assert boxes == []


async def test_rename_cancelled_and_empty_name(dlg, service, dialog_input, boxes, qtbot):
    await create_via_service(service, "Как есть")
    await dlg.refresh()
    dlg.list_widget.setCurrentRow(0)

    dialog_input["answer"] = ("Другое", False)   # cancelled in the input dialog
    dlg.rename_button.click()
    await asyncio.sleep(0.05)
    qtbot.wait(10)

    dlg.list_widget.blockSignals(True)
    dlg.list_widget.setCurrentRow(0)
    dlg.list_widget.blockSignals(False)
    dialog_input["answer"] = ("  ", True)        # empty name
    dlg.rename_button.click()
    await asyncio.sleep(0.05)
    qtbot.wait(10)

    rows = await service.list_sheets()
    assert [r.name for r in rows] == ["Как есть"]


async def test_unexpected_error_shown_critical(dlg, service, dialog_input, boxes, qtbot):
    await create_via_service(service, "Сломанный")

    async def broken(*args, **kwargs):
        raise RuntimeError("boom")

    dlg._service.rename = broken
    await dlg.refresh()
    dlg.list_widget.setCurrentRow(0)
    dialog_input["answer"] = ("Новое", True)
    await dlg.rename_sheet()
    assert ("critical", "Ошибка", "boom") in boxes


async def test_delete_service_error_keeps_row(dlg, service, boxes, confirm, qtbot):
    row = await create_via_service(service, "Осталось после ошибки")

    async def broken(*args, **kwargs):
        from app.application.services.character_sheet_service import SheetNotFoundError

        raise SheetNotFoundError(row.id)

    dlg._service.delete = broken
    await dlg.refresh()
    dlg.list_widget.setCurrentRow(0)
    confirm["answer"] = QMessageBox.StandardButton.Yes
    dlg.delete_button.click()
    await pump(qtbot, lambda: any(k == "warning" for k, *_ in boxes))

    assert (await service._repo.get_by_id(row.id)) is not None
    assert dlg.list_widget.count() == 1
