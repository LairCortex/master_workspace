"""«Настройка LLM…» opens as a sheet (NRI-0024 task 2.3, spec llm-configuration).

The wizard left the non-modal window family with this slice: the composition
root shows a fresh ``LlmSetupDialog`` — the island seated in a ``SheetFrame`` —
through the connector's one ``open_sheet`` path, so (spec «Настройка
открывается листом»):

* the header names the sheet with the entry text «Настройка LLM…», the one
  value it also carries as windowTitle, and the sheet opens at the design Д6
  default 640×560 (placement is never remembered);
* the sheet is an attached native sheet (Qt.Sheet, NonModal at Qt level —
  PR-012) over the main window while open: the main layer stays unavailable
  until the close (its offscreen face is the window's content gate, not Qt
  modality; the menu-gate half of the same rule lives in the window-side gate
  tests);
* the header «Закрыть» and Escape leave the sheet through the same cancel
  outcome, and the stack releases on either route;
* the running-save guard survives the container move (spec «на время
  асинхронного сохранения закрытие листа блокируется»): while the save is in
  flight the header button, Esc and the native close all stay inert, and the
  accept at ``finish_saving`` releases the stack;
* the wizard half is untouched: the island footer still carries «N из M» and
  its own «Закрыть» (task wording «без изменений»).

The connector is unit-built the way ``test_doc_viewer_sheet.py`` builds it;
only the host window is handed to ``qtbot`` — the sheets hang under it and
Qt closes a window's child windows with it.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QLabel, QPushButton, QWidget

from app.infrastructure.llm.config import LlmConfig
from app.presentation.views.llm_setup_dialog import LlmSetupDialog
from app.presentation.wiring import ApplicationWiring
from tests.presentation.qml_helpers import click_item, find_item


def _make_wiring(window) -> ApplicationWiring:
    app = SimpleNamespace(_image_store=None, _theme=None)
    return ApplicationWiring(
        app, window, None, None, None, None, None,
        SimpleNamespace(lock=asyncio.Lock()),
    )


@pytest.fixture
def stack(qtbot):
    """A host window, the connector owning the sheet stack, the announcements."""
    window = QWidget()
    qtbot.addWidget(window)
    window.show()
    wiring = _make_wiring(window)
    states: list[bool] = []
    wiring.sheet_stack_changed.connect(states.append)
    return window, wiring, states


def _open_sheet(qtbot, stack) -> LlmSetupDialog:
    window, wiring, _states = stack
    # A complete connection: the save path validates and arms the guard.
    dlg = LlmSetupDialog(config=LlmConfig("http://x/v1", "m", ""), parent=window)
    qtbot.addWidget(dlg)
    wiring.open_sheet(dlg)
    return dlg


def _header_title(sheet: LlmSetupDialog) -> str:
    return sheet.findChild(QLabel, "sheetFrameTitle").text()


def _close_button(sheet: LlmSetupDialog) -> QPushButton:
    return sheet.findChild(QPushButton, "sheetFrameCloseButton")


def test_header_names_the_setup_and_the_sheet_defaults_to_640x560(qtbot, stack):
    """Spec «Настройка открывается листом» + design Д6: the header names the
    sheet with exactly the windowTitle (the entry text), the sheet opens at
    its default 640×560 as an attached sheet (Qt.Sheet, NonModal at Qt level —
    PR-012 keeps the native menu exceptions live), and the stack rises with
    it."""
    _window, _wiring, states = stack
    dlg = _open_sheet(qtbot, stack)

    assert dlg.windowTitle() == "Настройка LLM…"
    assert _header_title(dlg) == "Настройка LLM…"
    assert dlg.size() == QSize(640, 560)
    assert dlg.windowFlags() & Qt.WindowType.Sheet
    assert dlg.windowModality() == Qt.WindowModality.NonModal
    assert dlg.isVisible()
    assert states == [True]

    dlg.reject()


def test_close_button_and_escape_share_the_cancel_outcome(qtbot, stack):
    """SheetFrame's rule on the setup sheet: «Закрыть» performs exactly the
    Esc action — equal observable outcomes (closed, Rejected), one stack
    release per route, so the work layer comes back the same way on both
    (spec «главный слой … недоступен до закрытия» — the announcement is the
    gate's whole input)."""
    _window, _wiring, states = stack

    by_button = _open_sheet(qtbot, stack)
    _close_button(by_button).click()
    assert not by_button.isVisible()
    assert by_button.result() == by_button.DialogCode.Rejected
    assert states == [True, False]

    by_escape = _open_sheet(qtbot, stack)
    from PySide6.QtTest import QTest

    QTest.keyClick(by_escape, Qt.Key.Key_Escape)
    assert not by_escape.isVisible()
    assert by_escape.result() == by_button.result()
    assert states == [True, False, True, False]


def test_header_close_is_blocked_while_the_save_runs(qtbot, stack):
    """Spec «на время асинхронного сохранения закрытие листа SHALL
    блокироваться» in sheet form: the frame's «Закрыть» rides the dialog's
    guarded reject, so during the save the press changes nothing — the sheet
    stays open and on the stack — and only the accepted finish lets it leave."""
    _window, _wiring, states = stack
    dlg = _open_sheet(qtbot, stack)
    finished: list[int] = []
    dlg.finished.connect(finished.append)

    dlg._on_save()  # complete connection: the guard arms, saved is emitted
    assert dlg.vm.saving is True

    _close_button(dlg).click()
    assert dlg.isVisible()
    assert not dlg.result()
    assert states == [True]
    assert finished == []

    dlg.finish_saving(True)
    assert not dlg.isVisible()
    assert dlg.result() == dlg.DialogCode.Accepted
    assert finished == [int(dlg.DialogCode.Accepted)]
    assert states == [True, False]


def test_escape_and_native_close_stay_blocked_while_saving(qtbot, stack):
    """The other two routes the sheet adds around the old gate: Escape hits
    the same guarded reject, the native close hits the guarded closeEvent —
    a save in flight cannot be outrun by any sheet exit."""
    from PySide6.QtTest import QTest

    _window, _wiring, states = stack
    dlg = _open_sheet(qtbot, stack)
    dlg._on_save()

    QTest.keyClick(dlg, Qt.Key.Key_Escape)
    dlg.close()
    assert dlg.isVisible()
    assert not dlg.result()
    assert states == [True]

    dlg.finish_saving(True)
    assert states == [True, False]


def test_island_footer_counter_and_close_survive_the_container(qtbot, stack):
    """Task wording «счётчик N из M … без изменений»: under the frame the
    island footer still carries «N из M» and its own «Закрыть», the counter
    follows the page, and a footer press leaves through the guarded reject —
    closing the sheet releases the stack (spec «Счётчик страниц виден
    всегда», scenario «Закрыть не трогает сохранённое» stays a plain reject)."""
    _window, _wiring, states = stack
    dlg = _open_sheet(qtbot, stack)

    counter = find_item(dlg.quick, "pageCounterLabel")
    assert counter.property("visible") is True
    assert counter.property("text") == f"1 из {dlg.page_count}"
    dlg.vm.goNext()
    assert counter.property("text") == f"2 из {dlg.page_count}"

    close = find_item(dlg.quick, "setupCloseButton")
    assert close.property("text") == "Закрыть"
    click_item(dlg.quick, close)

    assert not dlg.isVisible()
    assert dlg.result() == dlg.DialogCode.Rejected
    assert states == [True, False]
