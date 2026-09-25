"""Tests for the «Создать из пресета…» dialog (add-character-sheet-c, TDD).

Real in-memory DB + real service; QMessageBox is stubbed. The dialog is
non-modal (a child of the list dialog): two presets in a fixed order,
selecting a preset shows its full license text and substitutes the title into
the name field (unless the user already typed their own name), OK calls
``create_from_preset`` and closes only on success, cancel creates nothing.

Q3a (change port-sheet-list-preset-dialogs-qml-q3a, task 4.2): the widgets
content is gone — the checks keep their meanings 1:1 but address the
QQuickWidget island through ``walk_items``/``objectName`` (``qml_helpers``).
The retired seams map as follows:

* ``preset_list.setCurrentRow(i)``  → ``vm.selectPreset(i)`` — the very sync
  slot the QML delegate tap drives, so the D5 rule runs through the production
  path; one test switches via an island row click to prove the QML→VM seam;
* ``name_edit`` / ``license_view``  → the island's ``nameField`` /
  ``licenseView`` items (``text`` property), reading what the user sees;
  "typed" text is set on the field itself (its ``onTextChanged`` pushes it
  into the VM — the production typing route);
* ``ok_button`` / ``cancel_button`` → synthetic clicks on the island buttons.
"""
from __future__ import annotations

import asyncio
import time

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QAccessible
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from app.application.services.character_sheet_service import CharacterSheetService
from app.infrastructure.repositories.character_sheet_repository import (
    CharacterSheetRepository,
)
from app.presentation.views.character_sheet.preset_dialog import (
    CharacterSheetPresetDialog,
)
from app.domain.character_sheets.preset_catalog import (
    FATE_LICENSE_TEXT,
    MORK_BORG_LICENSE_TEXT,
)
from tests.presentation.qml_helpers import (
    click_item,
    find_item,
    island_row_texts,
    island_rows,
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


# ── island addressing (the retired QListWidget/QPlainTextEdit/QLineEdit seams) ─


def _preset_texts(dlg) -> list[str]:
    return island_row_texts(dlg.quick, "presetRow", "presetRowText")


def _license_text(dlg) -> str:
    return find_item(dlg.quick, "licenseView").property("text")


def _name_field(dlg):
    return find_item(dlg.quick, "nameField")


def _name_text(dlg) -> str:
    return _name_field(dlg).property("text")


def _type_name(dlg, text: str) -> None:
    """Type into the island field (the user's route): the field's
    ``onTextChanged`` pushes the text into the VM via ``setNameText`` — the
    same round trip a real key press drives."""
    _name_field(dlg).setProperty("text", text)
    QTest.qWait(0)  # let the field's onTextChanged → setNameText settle first


def _select_row_through_island(dlg, index: int) -> None:
    """Click the delegate row — the QML→VM selection seam."""
    rows = island_rows(dlg.quick, "presetRow")
    assert index < len(rows)
    click_item(dlg.quick, rows[index])


# ── 4.1: two items, license swap, name substitution, cancel ─────────────────


async def test_exactly_two_presets_in_order(dlg):
    assert _preset_texts(dlg) == ["Fate Core", "Mörk Borg"]


async def test_initial_selection_shows_fate_license_and_name(dlg):
    # the retired preset_list.currentRow() == 0 — the VM pre-selects row 0
    assert dlg.vm.selected_index == 0
    assert _license_text(dlg) == FATE_LICENSE_TEXT
    assert _name_text(dlg) == "Fate Core"


async def test_switching_selection_changes_license_and_name(dlg, qtbot):
    # the migrated setCurrentRow: the VM sync slot the delegate tap drives
    dlg.vm.selectPreset(1)
    qtbot.wait(1)
    assert _license_text(dlg) == MORK_BORG_LICENSE_TEXT
    assert _name_text(dlg) == "Mörk Borg"

    # switching back: Fate text back, no Mörk Borg text left
    dlg.vm.selectPreset(0)
    qtbot.wait(1)
    assert _license_text(dlg) == FATE_LICENSE_TEXT
    assert "Third Party License" not in _license_text(dlg)
    assert _name_text(dlg) == "Fate Core"


async def test_switching_by_row_tap_through_the_island(dlg, qtbot):
    """The selection change «через остров»: a delegate click goes through the
    QML ``onSelectedRequested`` → ``selectPreset`` seam and re-drives the
    license + name the very same way (the retired QListWidget row click)."""
    _select_row_through_island(dlg, 1)
    qtbot.wait(1)
    assert dlg.vm.selected_index == 1
    assert _license_text(dlg) == MORK_BORG_LICENSE_TEXT
    assert _name_text(dlg) == "Mörk Borg"


async def test_user_typed_name_is_not_overwritten_on_switch(dlg, qtbot):
    _type_name(dlg, "Свой герой")
    dlg.vm.selectPreset(1)
    qtbot.wait(1)
    assert _name_text(dlg) == "Свой герой"

    # an empty field is filled with the new title
    _type_name(dlg, "")
    dlg.vm.selectPreset(0)
    qtbot.wait(1)
    assert _name_text(dlg) == "Fate Core"


async def test_padded_preset_title_is_still_substituted_on_switch(dlg, qtbot):
    """Review #9: a preset title with surrounding whitespace is still the
    preset's own title (not a user-typed name), so switching presets must
    replace it with the new clean title instead of leaving the padding."""
    # starts on Fate Core (row 0); pad its title, then switch to Mörk Borg.
    _type_name(dlg, "Fate Core ")
    dlg.vm.selectPreset(1)
    qtbot.wait(1)
    assert _name_text(dlg) == "Mörk Borg"

    # leading whitespace is recognized the same way.
    _type_name(dlg, "  Mörk Borg")
    dlg.vm.selectPreset(0)
    qtbot.wait(1)
    assert _name_text(dlg) == "Fate Core"


async def test_cancel_does_not_create(dlg, service, qtbot):
    # Task 4.2 meaning: cancel closes WITHOUT emitting ``created`` at all
    # (the retired cancel_button.click() path — a plain done(), no signal).
    created: list[int] = []
    dlg.created.connect(created.append)
    click_item(dlg.quick, find_item(dlg.quick, "cancelButton"))
    await asyncio.sleep(0.05)
    qtbot.wait(10)
    assert dlg.isVisible() is False
    assert created == []
    assert len(await service.list_sheets()) == 0


async def test_ok_creates_template_and_emits_created(dlg, service, qtbot):
    created: list[int] = []
    dlg.created.connect(created.append)
    _type_name(dlg, "Fate Core")
    click_item(dlg.quick, find_item(dlg.quick, "okButton"))
    await pump(qtbot, lambda: created)

    assert len(created) == 1
    row = await service._repo.get_by_name("Fate Core")
    assert row is not None
    assert created[0] == row.id
    assert dlg.isVisible() is False


async def test_enter_clicks_the_create_marker(dlg, service, qtbot):
    """Design D5 wrapper contract: Enter clicks the island's ``defaultButton``
    marker (the migrated default action was «Создать») — row 0 is selected and
    its title is already substituted, so Enter creates right away."""
    created: list[int] = []
    dlg.created.connect(created.append)

    # A non-Enter key is not the marker's: it falls through to QDialog
    # handling and creates nothing.
    QTest.keyClick(dlg, Qt.Key_Tab)
    await asyncio.sleep(0.01)
    qtbot.wait(5)
    assert created == []
    assert dlg.isVisible()

    QTest.keyClick(dlg, Qt.Key_Enter)
    await pump(qtbot, lambda: created)

    assert len(created) == 1
    row = await service._repo.get_by_name("Fate Core")
    assert created[0] == row.id
    assert dlg.isVisible() is False


async def test_ok_name_conflict_keeps_dialog_open(dlg, service, boxes, qtbot):
    await service.create("Fate Core")
    click_item(dlg.quick, find_item(dlg.quick, "okButton"))
    await pump(qtbot, lambda: any("уже существует" in text for _, _, text in boxes))

    assert dlg.isVisible()            # the dialog stays open for a retry
    assert _name_text(dlg) == "Fate Core"
    rows = await service.list_sheets()
    assert [r.name for r in rows] == ["Fate Core"]

    # retry with a free name succeeds
    _type_name(dlg, "Мой Fate")
    created: list[int] = []
    dlg.created.connect(created.append)
    click_item(dlg.quick, find_item(dlg.quick, "okButton"))
    await pump(qtbot, lambda: created)
    assert len(created) == 1
    assert [r.name for r in await service.list_sheets()] == ["Fate Core", "Мой Fate"]


async def test_ok_blank_name_shows_warning_and_creates_nothing(dlg, service, boxes, qtbot):
    _type_name(dlg, "   ")
    click_item(dlg.quick, find_item(dlg.quick, "okButton"))
    await pump(qtbot, lambda: any("пустым" in text for _, _, text in boxes))

    assert dlg.isVisible()
    assert len(await service.list_sheets()) == 0


# ── accessibility (change nri-0012-qml-accessibility, task 3.4) ──────────────

def test_license_and_name_zones_carry_map_names(dlg):
    license_view = QAccessible.queryAccessibleInterface(
        find_item(dlg.quick, "licenseView"))
    assert license_view is not None
    assert license_view.role() == QAccessible.Role.EditableText
    assert license_view.text(QAccessible.Name) == "Текст лицензии"

    name = QAccessible.queryAccessibleInterface(find_item(dlg.quick, "nameField"))
    assert name is not None
    assert name.role() == QAccessible.Role.EditableText
    assert name.text(QAccessible.Name) == "Имя листа"


# ── activation wiring (change nri-0017-accessibility-completers, task 2.2) ───
#
# Live finding B3: RowItem emits ``activateRequested`` on its accessibility
# press (the double-click mirror), the island listened only to
# ``selectedRequested`` — the tree press of a preset row was a silent no-op.
# The contract pinned here: tree press = accept (the OK path, design F3 —
# select the activated row first, then the facade creates and closes with the
# Accepted result), while the mouse keeps its old split: single click selects
# and highlights, nothing is accepted yet.


def _press_preset_row(dlg, index: int) -> None:
    rows = island_rows(dlg.quick, "presetRow")
    assert index < len(rows)
    iface = QAccessible.queryAccessibleInterface(rows[index])
    assert iface is not None
    actions = iface.actionInterface()
    assert "Press" in actions.actionNames()
    actions.doAction("Press")


async def test_single_click_on_a_row_selects_without_accepting(dlg, service, boxes, qtbot):
    created: list[int] = []
    dlg.created.connect(created.append)

    _select_row_through_island(dlg, 1)
    qtbot.wait(10)

    # Selection/highlight only: the VM moved, nothing was created, the window
    # is still open with no result yet (the pre-B3 mouse behavior preserved).
    assert dlg.vm.selected_index == 1
    assert _license_text(dlg) == MORK_BORG_LICENSE_TEXT
    assert dlg.isVisible() is True
    assert dlg.result() == QDialog.DialogCode.Rejected
    assert created == []


async def test_press_on_a_row_accepts_that_preset(dlg, service, qtbot):
    """Spec «Пресет выбран активацией»: one tree press on an UNSELECTED row
    does what a mouse double-click does — the dialog closes having chosen
    that preset (create emitted, result Accepted)."""
    created: list[int] = []
    dlg.created.connect(created.append)

    _press_preset_row(dlg, 1)
    await pump(qtbot, lambda: created)

    assert len(created) == 1
    row = await service._repo.get_by_name("Mörk Borg")
    assert row is not None
    assert created[0] == row.id
    assert dlg.result() == QDialog.DialogCode.Accepted
    assert dlg.isVisible() is False
