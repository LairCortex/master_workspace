"""Docs entries open sheets (NRI-0024 task 2.2, spec document-viewer).

«Документация» and «Changelog» left the non-modal window format with this
slice: the connector shows a fresh ``DocViewerDialog`` — a SheetFrame wearing
the document's name in its header — through the one ``open_sheet`` path, so
(spec «Документ открывается листом»):

* each header names its document and the two sheets are distinguishable by
  the header alone (spec «Два документа различимы»);
* the sheet is WindowModal over the main window while open — reading blocks
  the work layer, closing resumes it (the sheet is shown with ``open()``,
  the modality check is the offscreen face of that);
* the header «Закрыть» and Escape leave the sheet through the same cancel
  outcome, and the stack releases on either route;
* the document stays fully readable: the island's ScrollView reaches the
  very last line (NRI-0014 AB1 survives the container move);
* a repeated entry on the closed stack builds a FRESH sheet — never a
  duplicate, never a revived one (the abolished registry's job, Д2).

The connector is unit-built the way ``test_sheet_stack_contract.py`` builds
it; the docs tree is the patched tmp dir (the bundle resolver's own dev/
frozen halves are pinned in ``tests/test_coverage_gaps.py``). Only the host
window is handed to ``qtbot`` — the sheets hang under it and Qt closes a
window's child windows with it.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QPushButton, QWidget

from app.presentation.views.doc_viewer_dialog import DocViewerDialog
from app.presentation.wiring import ApplicationWiring
from tests.presentation.qml_helpers import find_item


class _GateWindow(QWidget):
    """Window stand-in carrying the two real «О приложении» entries the
    connector's docs section connects (the shape MainWindow answers with)."""

    def __init__(self) -> None:
        super().__init__()
        self.readme_action = QAction("Документация", self)
        self.changelog_action = QAction("Changelog", self)
        self.states: list[bool] = []

    def on_sheet_stack_changed(self, active: bool) -> None:
        self.states.append(active)


def _make_wiring(window) -> ApplicationWiring:
    app = SimpleNamespace(_image_store=None, _theme=None)
    return ApplicationWiring(
        app, window, None, None, None, None, None,
        SimpleNamespace(lock=asyncio.Lock()),
    )


@pytest.fixture
def docs_tree(tmp_path, monkeypatch):
    (tmp_path / "README.md").write_text("DOC CONTENT", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text("CH TEXT", encoding="utf-8")
    monkeypatch.setattr(
        "app.presentation.wiring.bundle_resource_path", lambda *parts: tmp_path
    )
    return tmp_path


def _docs_wiring(qtbot, docs_tree):
    window = _GateWindow()
    qtbot.addWidget(window)
    window.show()
    wiring = _make_wiring(window)
    wiring._connect_docs()
    states: list[bool] = []
    wiring.sheet_stack_changed.connect(states.append)
    return window, wiring, states


def _live_docs(window) -> list[DocViewerDialog]:
    return [
        dlg for dlg in window.findChildren(DocViewerDialog) if dlg.isVisible()
    ]


def _header_title(sheet: DocViewerDialog) -> str:
    return sheet.findChild(QLabel, "sheetFrameTitle").text()


def _close_button(sheet: DocViewerDialog) -> QPushButton:
    return sheet.findChild(QPushButton, "sheetFrameCloseButton")


def test_each_header_names_its_document(qtbot, docs_tree):
    """Spec «Два документа различимы»: the header text names exactly the
    document the entry opened (one value with windowTitle), each sheet
    carries its own content, and the stack rises with the reader (the main
    layer's sheet entries then gate — window side, pinned in TestSheetStack
    MenuGate)."""
    window, wiring, states = _docs_wiring(qtbot, docs_tree)

    window.readme_action.trigger()
    readme = _live_docs(window)
    assert len(readme) == 1
    doc = readme[0]
    assert doc.windowTitle() == "Документация"
    assert _header_title(doc) == "Документация"
    assert doc.vm.text == "DOC CONTENT"
    # A sheet, not a window: open() under the parent — WindowModal over the
    # main layer (spec «Чтение блокирует работу до закрытия»).
    assert doc.windowModality() == Qt.WindowModality.WindowModal
    assert states == [True]

    doc.reject()
    window.changelog_action.trigger()
    changelog = _live_docs(window)
    assert len(changelog) == 1
    assert changelog[0] is not doc
    assert _header_title(changelog[0]) == "Changelog"
    assert changelog[0].vm.text == "CH TEXT"
    # «каждый закрывается своей кнопкой»
    _close_button(changelog[0]).click()
    assert not changelog[0].isVisible()
    assert states == [True, False, True, False]


def test_sheet_opens_at_the_document_default_size(qtbot, docs_tree):
    """The docs sheet default 720×620 (design Д6); placement is never
    remembered, so the next opening gets the same default back."""
    window, wiring, states = _docs_wiring(qtbot, docs_tree)
    window.readme_action.trigger()
    doc = _live_docs(window)[0]
    assert doc.size() == QSize(720, 620)
    doc.reject()
    window.readme_action.trigger()
    again = _live_docs(window)[0]
    assert again.size() == QSize(720, 620)
    again.reject()


def test_close_button_and_escape_share_the_cancel_outcome(qtbot, docs_tree):
    """SheetFrame's rule on the docs sheet: «Закрыть» performs exactly the
    Esc action — equal observable outcomes (closed, Rejected) and one stack
    release per route, so reading always ends the same way it began
    (spec «Чтение блокирует работу до закрытия»: after the close the work
    layer is back — the stack announcement is the gate's whole input)."""
    window, wiring, states = _docs_wiring(qtbot, docs_tree)

    window.changelog_action.trigger()
    by_button = _live_docs(window)[0]
    _close_button(by_button).click()
    assert not by_button.isVisible()
    assert by_button.result() == by_button.DialogCode.Rejected
    assert states == [True, False]

    window.changelog_action.trigger()
    by_escape = _live_docs(window)[0]
    QTest.keyClick(by_escape, Qt.Key.Key_Escape)
    assert not by_escape.isVisible()
    assert by_escape.result() == by_button.result()
    assert states == [True, False, True, False]


def test_scroll_reaches_the_end_of_a_long_document(qtbot, docs_tree):
    """Scroll preserved after the container move (AB1): the sheet is smaller
    than the document, and the ScrollView's clamp lands on the very last
    line — the end of the document is reachable, not only its head."""
    (docs_tree / "README.md").write_text(
        "\n".join(f"строка {i} длинного документа" for i in range(600)),
        encoding="utf-8",
    )
    window, wiring, states = _docs_wiring(qtbot, docs_tree)
    window.readme_action.trigger()
    doc = _live_docs(window)[0]
    qtbot.waitExposed(doc)

    scroll = find_item(doc.quick, "docScroll")
    flick = scroll.property("contentItem")
    assert flick is not None
    # Layout-settle turns (the convention of the island scroll tests): the
    # metrics below must already be the sheet's final ones.
    qtbot.waitUntil(lambda: float(flick.height()) > 0.0, timeout=2000)
    for _ in range(4):
        qtbot.wait(5)

    content_h = float(flick.property("contentHeight"))
    viewport_h = float(flick.height())
    assert content_h > viewport_h  # the sheet truly clips the document

    # Drive the view to the document's end — the scroll offset the scrollbar
    # maximum maps to — and require the last text line flush with the
    # viewport bottom: the end of the document is reachable, not only its
    # head.
    flick.setProperty("contentY", content_h - viewport_h)
    qtbot.waitUntil(
        lambda: float(flick.property("contentY")) > 0.0, timeout=2000
    )
    assert float(flick.property("contentY")) == pytest.approx(
        content_h - viewport_h, abs=1.0
    )
    text = find_item(doc.quick, "docText")
    bottom = text.mapToItem(flick, 0.0, float(text.property("height"))).y()
    assert abs(bottom - viewport_h) <= 1.0


def test_repeat_entry_on_closed_stack_opens_fresh_never_a_duplicate(
    qtbot, docs_tree,
):
    """The abolished registry's guarantee as a sheet property (Д2): a
    repeated entry on the CLOSED stack opens a fresh sheet — the closed one
    is never revived — and while a sheet is up only one lives (the entry
    itself is gated then, window side)."""
    window, wiring, states = _docs_wiring(qtbot, docs_tree)

    window.readme_action.trigger()
    first = _live_docs(window)[0]
    assert len(_live_docs(window)) == 1

    first.reject()
    assert _live_docs(window) == []

    window.readme_action.trigger()
    second = _live_docs(window)[0]
    assert second is not first
    assert len(_live_docs(window)) == 1
    second.reject()
    assert states == [True, False, True, False]
