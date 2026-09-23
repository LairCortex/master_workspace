"""Tests for the character-sheet list dialog (task 6.1 of add-character-sheet-a1).

Real in-memory DB + real service; modal helpers (QInputDialog / QMessageBox)
are stubbed. The dialog is non-modal; its async flows are triggered through
the buttons and pumped.

Q3a (change port-sheet-list-preset-dialogs-qml-q3a, task 4.1): the widgets
content is gone — the checks keep their meanings 1:1 but address the
QQuickWidget island through ``walk_items``/``objectName`` (``qml_helpers``):
buttons are clicked through synthetic input on the island, list rows read
from the materialized ``templateRow``/``instanceRow`` delegates, tab switches
and selections go through the VM slots the QML itself drives, and button
availability is asserted through the enabled/visible properties bound to the
VM flags (the retired ``_sync_*`` imperative syncs have no caller anymore).
"""
from __future__ import annotations

import asyncio
import json
import time

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

from app.application.services.character_sheet_instance_service import (
    CharacterSheetInstanceService,
)
from app.application.services.character_sheet_service import (
    CharacterSheetService,
)
from app.domain.entities.character_sheet import EMPTY_PAGES_JSON
from app.infrastructure.repositories.character_sheet_instance_repository import (
    CharacterSheetInstanceRepository,
)
from app.infrastructure.repositories.character_sheet_repository import (
    CharacterSheetRepository,
)
from app.presentation.viewmodels.sheet_list_view_model import TAB_INSTANCES
from app.presentation.views.character_sheet.list_dialog import CharacterSheetListDialog
from app.domain.character_sheets.preset_catalog import PresetCatalog
from tests.presentation.qml_helpers import (
    click_item,
    find_item,
    island_row_texts,
    walk_items,
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


# ── island addressing (the retired QListWidget/QPushButton seams) ────────────


def _click(dlg, object_name: str) -> None:
    """Synthetic click on an island button (the retired QPushButton.click()).

    A disabled QML button swallows the click, exactly like the retired
    ``QPushButton.click()`` was a no-op on a disabled widgets button.
    """
    click_item(dlg.quick, find_item(dlg.quick, object_name))


def _button(dlg, object_name: str):
    return find_item(dlg.quick, object_name)


def _first_text(dlg) -> str | None:
    texts = island_row_texts(dlg.quick, "templateRow", "templateRowText")
    return texts[0] if texts else None


def _template_texts(dlg) -> list[str]:
    return island_row_texts(dlg.quick, "templateRow", "templateRowText")


def _instance_texts(dlg) -> list[str]:
    return island_row_texts(dlg.quick, "instanceRow", "instanceRowText")


def _select_template(dlg, index: int) -> None:
    """Set the templates-tab selection (the retired setCurrentRow scan): the
    VM slot is the very call the QML delegate tap drives, so the flag/selection
    recompute is the production one."""
    dlg.vm.selectTemplate(index)


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
    assert _template_texts(dlg) == []

    dialog_input["answer"] = ("Персонаж", True)
    _click(dlg, "createButton")
    await pump(qtbot, lambda: len(_template_texts(dlg)) == 1)

    assert _template_texts(dlg) == ["Персонаж"]
    row = await service._repo.get_by_name("Персонаж")
    assert row is not None
    assert row.pages == EMPTY_PAGES_JSON      # empty single page written at create
    assert row.schema_version == 2            # A-playable: new sheets are v2
    assert opened == [row.id]                 # the app opens the freshly created sheet


async def test_create_empty_name_refused(dlg, service, dialog_input, boxes, qtbot):
    await dlg.refresh()
    dialog_input["answer"] = ("   ", True)
    _click(dlg, "createButton")
    await pump(qtbot, lambda: any(k == "warning" for k, *_ in boxes))
    assert _template_texts(dlg) == []
    assert len(await service.list_sheets()) == 0


async def test_create_name_conflict_rejected(dlg, service, dialog_input, boxes, qtbot):
    await create_via_service(service, "Занято")
    await dlg.refresh()

    dialog_input["answer"] = ("Занято", True)
    _click(dlg, "createButton")
    await pump(qtbot, lambda: any("Занято" in text for _, _, text in boxes))

    assert _template_texts(dlg) == ["Занято"]  # no duplicate row
    names = _template_texts(dlg)
    assert names == ["Занято"]
    rows = await service.list_sheets()
    assert [r.name for r in rows] == ["Занято"]            # nothing new in the DB


async def test_create_input_cancelled(dlg, service, dialog_input, qtbot):
    dialog_input["answer"] = ("Не создавалось", False)
    _click(dlg, "createButton")
    await asyncio.sleep(0.05)
    qtbot.wait(10)
    assert len(await service.list_sheets()) == 0


# ── rename ─────────────────────────────────────────────────────────────────

async def test_rename_updates_db_immediately(dlg, service, dialog_input, qtbot):
    row = await create_via_service(service, "Старое имя")
    await dlg.refresh()
    _select_template(dlg, 0)

    pages_before = (await service._repo.get_by_id(row.id)).pages
    dialog_input["answer"] = ("Новое имя", True)
    _click(dlg, "renameButton")
    await pump(qtbot, lambda: _first_text(dlg) == "Новое имя")

    row2 = await service._repo.get_by_id(row.id)
    assert row2.name == "Новое имя"
    assert row2.pages == pages_before       # rename never touches the layout


async def test_rename_conflict_keeps_old_name(dlg, service, dialog_input, boxes, qtbot):
    await create_via_service(service, "А")
    await create_via_service(service, "В")
    await dlg.refresh()
    _select_template(dlg, 0)   # "А"

    dialog_input["answer"] = ("В", True)
    _click(dlg, "renameButton")
    await pump(qtbot, lambda: any("В" in text for _, _, text in boxes))

    rows = await service.list_sheets()
    assert sorted(r.name for r in rows) == ["А", "В"]     # nothing renamed
    await dlg.refresh()  # the retired blockSignals-clear-then-reload re-read
    names = _template_texts(dlg)
    assert "В" in names and "А" in names


# ── delete ─────────────────────────────────────────────────────────────────

async def test_delete_with_confirmation(dlg, service, dialog_input, confirm, qtbot):
    row = await create_via_service(service, "Удалить меня")
    await dlg.refresh()
    _select_template(dlg, 0)

    _click(dlg, "deleteButton")
    await pump(qtbot, lambda: _template_texts(dlg) == [])

    assert (await service._repo.get_by_id(row.id)) is None
    assert confirm["calls"], "a confirmation dialog was shown"


async def test_delete_refused_keeps_sheet(dlg, service, dialog_input, confirm, qtbot):
    row = await create_via_service(service, "Осталось")
    await dlg.refresh()
    _select_template(dlg, 0)

    confirm["answer"] = QMessageBox.StandardButton.No
    _click(dlg, "deleteButton")
    await asyncio.sleep(0.05)
    qtbot.wait(10)

    assert len(_template_texts(dlg)) == 1
    assert (await service._repo.get_by_id(row.id)) is not None


async def test_delete_of_open_sheet_is_unavailable(dlg, service, dialog_input, qtbot):
    opened = await create_via_service(service, "Открыт")
    await create_via_service(service, "Другой")
    await dlg.refresh()
    dlg.set_open_sheet_id(opened.id)

    _select_template(dlg, _template_texts(dlg).index("Открыт"))
    # The VM recomputes the flags synchronously; QML re-evaluates the enabled
    # binding on the same notify — the retired _sync_delete_enabled imperative.
    assert _button(dlg, "deleteButton").property("enabled") is False

    _select_template(dlg, _template_texts(dlg).index("Другой"))
    assert _button(dlg, "deleteButton").property("enabled") is True

    # and the async flow itself refuses the open id even if forced
    dlg.set_open_sheet_id(opened.id)
    _select_template(dlg, _template_texts(dlg).index("Открыт"))
    await dlg.delete_sheet()
    assert (await service._repo.get_by_id(opened.id)) is not None


# ── open ───────────────────────────────────────────────────────────────────

async def test_open_emits_requested(dlg, service, qtbot):
    row = await create_via_service(service, "Открыть")
    opened = []
    dlg.open_requested.connect(opened.append)
    await dlg.refresh()
    _select_template(dlg, 0)

    _click(dlg, "openButton")
    await pump(qtbot, lambda: opened)
    assert opened == [row.id]


async def test_enter_clicks_the_open_marker(dlg, service, qtbot):
    """Design D5 wrapper contract: Enter clicks the island's ``defaultButton``
    marker (the migrated dialog answered Enter through «Открыть»)."""
    row = await create_via_service(service, "Enter")
    opened = []
    dlg.open_requested.connect(opened.append)
    await dlg.refresh()
    _select_template(dlg, 0)

    QTest.keyClick(dlg, Qt.Key_Return)
    await pump(qtbot, lambda: opened)
    assert opened == [row.id]

    # A non-Enter key is not the marker's: it falls through to QDialog
    # handling and emits nothing here.
    opened.clear()
    QTest.keyClick(dlg, Qt.Key_Tab)
    await asyncio.sleep(0.05)
    qtbot.wait(10)
    assert opened == []


# ── edge guards ────────────────────────────────────────────────────────────

async def test_open_without_selection_does_nothing(dlg, qtbot):
    opened = []
    dlg.open_requested.connect(opened.append)
    await dlg.refresh()
    _click(dlg, "openButton")  # disabled without a selection: swallows the click
    await asyncio.sleep(0.05)
    qtbot.wait(10)
    assert opened == []


async def test_rename_without_selection_does_nothing(dlg, service, dialog_input, boxes, qtbot):
    await create_via_service(service, "Целое")
    await dlg.refresh()
    dialog_input["answer"] = ("Взлом", True)
    _click(dlg, "renameButton")
    await asyncio.sleep(0.05)
    qtbot.wait(10)
    rows = await service.list_sheets()
    assert [r.name for r in rows] == ["Целое"]
    assert boxes == []


async def test_rename_cancelled_and_empty_name(dlg, service, dialog_input, boxes, qtbot):
    await create_via_service(service, "Как есть")
    await dlg.refresh()
    _select_template(dlg, 0)

    dialog_input["answer"] = ("Другое", False)   # cancelled in the input dialog
    _click(dlg, "renameButton")
    await asyncio.sleep(0.05)
    qtbot.wait(10)

    _select_template(dlg, 0)
    dialog_input["answer"] = ("  ", True)        # empty name
    _click(dlg, "renameButton")
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
    _select_template(dlg, 0)
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
    _select_template(dlg, 0)
    confirm["answer"] = QMessageBox.StandardButton.Yes
    _click(dlg, "deleteButton")
    await pump(qtbot, lambda: any(k == "warning" for k, *_ in boxes))

    assert (await service._repo.get_by_id(row.id)) is not None
    assert len(_template_texts(dlg)) == 1


# ── tabs / instances (add-character-sheet-b) ────────────────────────────────


@pytest.fixture
def inst_services(async_session):
    sheet_repo = CharacterSheetRepository(async_session)
    inst_repo = CharacterSheetInstanceRepository(async_session)
    sheet_svc = CharacterSheetService(sheet_repo, instance_repo=inst_repo)
    inst_svc = CharacterSheetInstanceService(inst_repo, sheet_svc)
    return sheet_svc, inst_svc


@pytest.fixture
def inst_dlg(qtbot, inst_services):
    sheet_svc, inst_svc = inst_services
    d = CharacterSheetListDialog(sheet_svc, instance_service=inst_svc)
    d.resize(420, 520)
    d.show()
    qtbot.wait(10)
    yield d, sheet_svc, inst_svc
    d.close()
    d.deleteLater()
    qtbot.wait(1)


@pytest.fixture
def dialog_item(monkeypatch) -> dict:
    state: dict = {"answer": ("", False)}

    def fake_get_item(*args, **kwargs):
        return state["answer"]

    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(fake_get_item))
    return state


async def test_tabs_templates_and_instances(inst_dlg):
    d, *_ = inst_dlg
    assert find_item(d.quick, "tabTemplates").property("text") == "Шаблоны"
    assert find_item(d.quick, "tabInstances").property("text") == "Листы"


async def test_create_instance_adds_row_and_insert(inst_dlg, dialog_item, dialog_input, qtbot):
    d, sheet_svc, inst_svc = inst_dlg
    opened = []
    d.open_instance_requested.connect(opened.append)
    await sheet_svc.create("Шаблон")
    await d.refresh()
    d.vm.setCurrentTab(TAB_INSTANCES)
    dialog_item["answer"] = ("Шаблон", True)
    dialog_input["answer"] = ("Лист 1", True)
    _click(d, "createButton")
    await pump(qtbot, lambda: len(_instance_texts(d)) == 1)
    assert _instance_texts(d) == ["Лист 1 — Шаблон"]
    row = await inst_svc._repo.get_by_name("Лист 1")
    assert row is not None
    assert opened == [row.id]


async def test_create_instance_name_conflict(inst_dlg, dialog_item, dialog_input, boxes, qtbot):
    d, sheet_svc, inst_svc = inst_dlg
    t = await sheet_svc.create("Шаблон")
    await inst_svc.create("Занято", t.id)
    await d.refresh()
    d.vm.setCurrentTab(TAB_INSTANCES)
    dialog_item["answer"] = ("Шаблон", True)
    dialog_input["answer"] = ("Занято", True)
    _click(d, "createButton")
    await pump(qtbot, lambda: any("Занято" in text for _, _, text in boxes))
    assert len(_instance_texts(d)) == 1


async def test_rename_instance_immediately(inst_dlg, dialog_input, qtbot):
    d, sheet_svc, inst_svc = inst_dlg
    t = await sheet_svc.create("Шаблон")
    await inst_svc.create("До", t.id)
    await d.refresh()
    d.vm.setCurrentTab(TAB_INSTANCES)
    d.vm.selectInstance(0)
    dialog_input["answer"] = ("После", True)
    _click(d, "renameButton")
    await pump(qtbot, lambda: _instance_texts(d) == ["После — Шаблон"])
    assert (await inst_svc._repo.get_by_name("После")) is not None


async def test_delete_instance_with_confirm(inst_dlg, confirm, qtbot):
    d, sheet_svc, inst_svc = inst_dlg
    t = await sheet_svc.create("Шаблон")
    row = await inst_svc.create("Удалить", t.id)
    await d.refresh()
    d.vm.setCurrentTab(TAB_INSTANCES)
    d.vm.selectInstance(0)
    _click(d, "deleteButton")
    await pump(qtbot, lambda: _instance_texts(d) == [])
    assert await inst_svc._repo.get_by_id(row.id) is None
    assert confirm["calls"]


async def test_delete_open_instance_unavailable(inst_dlg, qtbot):
    d, sheet_svc, inst_svc = inst_dlg
    t = await sheet_svc.create("Шаблон")
    opened = await inst_svc.create("Открыт", t.id)
    await d.refresh()
    d.vm.setCurrentTab(TAB_INSTANCES)
    d.set_open_instance_id(opened.id)
    d.vm.selectInstance(0)
    assert _button(d, "deleteButton").property("enabled") is False


async def test_delete_seated_instance_unavailable(inst_dlg, qtbot):
    d, sheet_svc, inst_svc = inst_dlg
    t = await sheet_svc.create("Шаблон")
    row = await inst_svc.create("За столом", t.id)
    await d.refresh()
    d.vm.setCurrentTab(TAB_INSTANCES)
    d.set_seated_ids({row.id})
    d.vm.selectInstance(0)
    assert _button(d, "deleteButton").property("enabled") is False
    await d.delete_instance()
    assert await inst_svc._repo.get_by_id(row.id) is not None
    d.set_seated_ids(None)
    assert _button(d, "deleteButton").property("enabled") is True


async def test_delete_template_with_instances_unavailable(inst_dlg, qtbot):
    d, sheet_svc, inst_svc = inst_dlg
    t = await sheet_svc.create("Шаблон")
    await inst_svc.create("Лист", t.id)
    await d.refresh()
    d.vm.setCurrentTab(0)
    _select_template(d, 0)
    assert _button(d, "deleteButton").property("enabled") is False
    await d.delete_sheet()
    assert await sheet_svc._repo.get_by_id(t.id) is not None


async def test_open_rename_disabled_without_selection(inst_dlg, qtbot):
    d, sheet_svc, _ = inst_dlg
    await sheet_svc.create("Шаблон")
    await d.refresh()
    d.vm.setCurrentTab(0)
    d.vm.selectTemplate(-1)  # the retired clearSelection(): nothing selected
    assert _button(d, "openButton").property("enabled") is False
    assert _button(d, "renameButton").property("enabled") is False
    _select_template(d, 0)
    assert _button(d, "openButton").property("enabled") is True
    assert _button(d, "renameButton").property("enabled") is True
    d.vm.setCurrentTab(1)
    assert _button(d, "openButton").property("enabled") is False
    assert _button(d, "renameButton").property("enabled") is False


# ── create from preset (add-character-sheet-c) ───────────────────────────────


async def test_preset_button_visible_only_on_templates_tab(inst_dlg, qtbot):
    d, *_ = inst_dlg
    d.vm.setCurrentTab(0)
    qtbot.wait(1)
    assert _button(d, "presetButton").property("visible") is True
    d.vm.setCurrentTab(1)
    qtbot.wait(1)
    assert _button(d, "presetButton").property("visible") is False


async def _open_preset_dialog(d, qtbot):
    _click(d, "presetButton")
    await pump(qtbot, lambda: d.preset_dialog is not None and d.preset_dialog.isVisible())
    return d.preset_dialog


async def test_create_from_preset_adds_row_and_opens_design(inst_dlg, qtbot, boxes):
    d, sheet_svc, _ = inst_dlg
    opened: list[int] = []
    d.open_requested.connect(opened.append)
    await d.refresh()
    assert _template_texts(d) == []

    preset = await _open_preset_dialog(d, qtbot)
    preset_rows = island_row_texts(preset.quick, "presetRow", "presetRowText")
    assert len(preset_rows) == 2
    name_field = find_item(preset.quick, "nameField")
    assert name_field.property("text") == "Fate Core"   # title substituted by default

    click_item(preset.quick, find_item(preset.quick, "okButton"))
    await pump(qtbot, lambda: len(_template_texts(d)) == 1 and opened)

    assert _template_texts(d) == ["Fate Core"]
    row = await sheet_svc._repo.get_by_name("Fate Core")
    assert row is not None
    assert opened == [row.id]   # the app opens the new template's Design
    assert json.loads(row.pages) == json.loads(PresetCatalog().load_pages("fate_core"))
    await pump(qtbot, lambda: d.preset_dialog is None)  # closed and dropped


async def test_create_from_preset_name_conflict_rejected(inst_dlg, boxes, qtbot):
    d, sheet_svc, _ = inst_dlg
    opened: list[int] = []
    d.open_requested.connect(opened.append)
    await sheet_svc.create("Mörk Borg")
    await d.refresh()

    preset = await _open_preset_dialog(d, qtbot)
    preset.vm.selectPreset(1)  # Mörk Borg (the retired setCurrentRow)
    qtbot.wait(1)
    assert find_item(preset.quick, "nameField").property("text") == "Mörk Borg"

    click_item(preset.quick, find_item(preset.quick, "okButton"))
    await pump(qtbot, lambda: any("уже существует" in text for _, _, text in boxes))

    assert opened == []
    assert [r.name for r in await sheet_svc.list_sheets()] == ["Mörk Borg"]
    assert preset.isVisible()  # stays open — the user can rename and retry
    click_item(preset.quick, find_item(preset.quick, "cancelButton"))
    # The QML click pumps Qt once (QTest.qWait), which flushes the widgets-era
    # ``_preset_dialog_finished`` deleteLater of the finished dialog: its C++
    # can be gone when we look again. The facade's cleared ``preset_dialog``
    # (set in the very finished handler, synchronously in done()) is the very
    # "closed and dropped" fact the retired ``not isVisible()`` checked.
    await pump(qtbot, lambda: d.preset_dialog is None)


async def test_preset_cancel_keeps_list_unchanged(inst_dlg, qtbot):
    d, sheet_svc, _ = inst_dlg
    opened: list[int] = []
    d.open_requested.connect(opened.append)
    await d.refresh()

    preset = await _open_preset_dialog(d, qtbot)
    click_item(preset.quick, find_item(preset.quick, "cancelButton"))
    # Same seam as the conflict test: closing the island dialog lands the
    # finished handler synchronously; the C++ may flush in the click's pump.
    await pump(qtbot, lambda: d.preset_dialog is None)

    assert _template_texts(d) == []
    assert opened == []
    assert len(await sheet_svc.list_sheets()) == 0


async def test_list_dialog_has_no_pdf_export(dlg):
    texts = [
        i.property("text")
        for i in walk_items(dlg.quick.rootObject())
        if i.objectName().endswith("Button")
    ]
    assert texts  # the guard must not pass vacuously on an unrendered scene
    assert "Экспорт в PDF…" not in texts
