"""Tests for the «Создать из пресета…» dialog (add-character-sheet-c, TDD).

Real in-memory DB + real service; QMessageBox is stubbed. The dialog is
non-modal (a child of the list dialog): two presets in a fixed order,
selecting a preset shows its full license text and substitutes the title into
the name field (unless the user already typed their own name), OK calls
``create_from_preset`` and closes only on success, cancel creates nothing.
"""
from __future__ import annotations

import asyncio
import time

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from app.application.services.character_sheet_service import CharacterSheetService
from app.infrastructure.repositories.character_sheet_repository import (
    CharacterSheetRepository,
)
from app.presentation.views.character_sheet.preset_dialog import (
    CharacterSheetPresetDialog,
)
from app.presentation.views.character_sheet.presets.catalog import (
    FATE_LICENSE_TEXT,
    MORK_BORG_LICENSE_TEXT,
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
    d = CharacterSheetPresetDialog(service)
    d.resize(540, 500)
    d.show()
    qtbot.wait(10)
    yield d
    d.close()
    d.deleteLater()
    qtbot.wait(1)


async def pump(qtbot, until, timeout: float = 3.0) -> None:
    """Pump the asyncio loop + Qt loop until ``until()`` is true."""
    t0 = time.perf_counter()
    while not until():
        if time.perf_counter() - t0 > timeout:
            raise TimeoutError("pump: condition not met")
        await asyncio.sleep(0)
        qtbot.wait(1)


# ── 4.1: two items, license swap, name substitution, cancel ─────────────────


async def test_exactly_two_presets_in_order(dlg):
    assert dlg.preset_list.count() == 2
    assert [dlg.preset_list.item(i).text() for i in range(2)] == [
        "Fate Core",
        "Mörk Borg",
    ]


async def test_initial_selection_shows_fate_license_and_name(dlg):
    assert dlg.preset_list.currentRow() == 0
    assert dlg.license_view.toPlainText() == FATE_LICENSE_TEXT
    assert dlg.name_edit.text() == "Fate Core"


async def test_switching_selection_changes_license_and_name(dlg, qtbot):
    dlg.preset_list.setCurrentRow(1)
    qtbot.wait(1)
    assert dlg.license_view.toPlainText() == MORK_BORG_LICENSE_TEXT
    assert dlg.name_edit.text() == "Mörk Borg"

    # switching back: Fate text back, no Mörk Borg text left
    dlg.preset_list.setCurrentRow(0)
    qtbot.wait(1)
    assert dlg.license_view.toPlainText() == FATE_LICENSE_TEXT
    assert "Third Party License" not in dlg.license_view.toPlainText()
    assert dlg.name_edit.text() == "Fate Core"


async def test_user_typed_name_is_not_overwritten_on_switch(dlg, qtbot):
    dlg.name_edit.setText("Свой герой")
    dlg.preset_list.setCurrentRow(1)
    qtbot.wait(1)
    assert dlg.name_edit.text() == "Свой герой"

    # an empty field is filled with the new title
    dlg.name_edit.clear()
    dlg.preset_list.setCurrentRow(0)
    qtbot.wait(1)
    assert dlg.name_edit.text() == "Fate Core"


async def test_padded_preset_title_is_still_substituted_on_switch(dlg, qtbot):
    """Review #9: a preset title with surrounding whitespace is still the
    preset's own title (not a user-typed name), so switching presets must
    replace it with the new clean title instead of leaving the padding."""
    # starts on Fate Core (row 0); pad its title, then switch to Mörk Borg.
    dlg.name_edit.setText("Fate Core ")
    dlg.preset_list.setCurrentRow(1)
    qtbot.wait(1)
    assert dlg.name_edit.text() == "Mörk Borg"

    # leading whitespace is recognized the same way.
    dlg.name_edit.setText("  Mörk Borg")
    dlg.preset_list.setCurrentRow(0)
    qtbot.wait(1)
    assert dlg.name_edit.text() == "Fate Core"


async def test_cancel_does_not_create(dlg, service, qtbot):
    dlg.cancel_button.click()
    await asyncio.sleep(0.05)
    qtbot.wait(10)
    assert dlg.isVisible() is False
    assert len(await service.list_sheets()) == 0


async def test_ok_creates_template_and_emits_created(dlg, service, qtbot):
    created: list[int] = []
    dlg.created.connect(created.append)
    dlg.name_edit.setText("Fate Core")
    dlg.ok_button.click()
    await pump(qtbot, lambda: created)

    assert len(created) == 1
    row = await service._repo.get_by_name("Fate Core")
    assert row is not None
    assert created[0] == row.id
    assert dlg.isVisible() is False


async def test_ok_name_conflict_keeps_dialog_open(dlg, service, boxes, qtbot):
    await service.create("Fate Core")
    dlg.ok_button.click()
    await pump(qtbot, lambda: any("уже существует" in text for _, _, text in boxes))

    assert dlg.isVisible()            # the dialog stays open for a retry
    assert dlg.name_edit.text() == "Fate Core"
    rows = await service.list_sheets()
    assert [r.name for r in rows] == ["Fate Core"]

    # retry with a free name succeeds
    dlg.name_edit.setText("Мой Fate")
    created: list[int] = []
    dlg.created.connect(created.append)
    dlg.ok_button.click()
    await pump(qtbot, lambda: created)
    assert len(created) == 1
    assert [r.name for r in await service.list_sheets()] == ["Fate Core", "Мой Fate"]


async def test_ok_blank_name_shows_warning_and_creates_nothing(dlg, service, boxes, qtbot):
    dlg.name_edit.setText("   ")
    dlg.ok_button.click()
    await pump(qtbot, lambda: any("пустым" in text for _, _, text in boxes))

    assert dlg.isVisible()
    assert len(await service.list_sheets()) == 0
