"""The connector-owned sheet stack (NRI-0024 task 1.1, design Д1/Д2).

``ApplicationWiring.open_sheet`` is the one show path of every sheet: the
stack it owns is announced through ``sheet_stack_changed`` — True the moment
the first sheet covers the main window, False when the last one leaves (the
menu gate's input, Д2) — and the scrim cascade generalizes from the two
island classes to the duck contract, so a widget ``SheetFrame`` dims and is
dimmed exactly like the QML sheets around it (test 1.1's «каскад скрэма на
трёх слоях»).

The connector is unit-built the way ``test_sheet_stack_scrim.py`` builds it:
the open paths touch no session (no save here), the lock only satisfies the
constructor.

Widget registration follows the scrim-test convention: only the top-level
host is handed to ``qtbot`` — the sheets hang C++-owned under it (that is
the parent chain the dim walk reads), and a registered child whose C++ side
dies together with its parent's wrapper surfaces as pytest-qt closing a
deleted widget in teardown. Qt closes a window's child windows with it, so
the host's teardown close already covers every sheet.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QWidget

from app.presentation.views.event_dialog import EventDialog
from app.presentation.views.sheet_frame import SheetFrame
from app.presentation.views.xlsx_import_dialog import XlsxImportDialog
from app.presentation.wiring import ApplicationWiring

# The dim one sheet under a parent costs, pinned literally (the convention of
# test_sheet_stack_scrim: renumbering must be a deliberate choice).
UNIT = 0.25


class _StubEntityService:
    async def get_all(self):
        return []


def _make_wiring(window=None) -> ApplicationWiring:
    """The connector with exactly what the sheet-open paths touch."""
    app = SimpleNamespace(
        _image_store=None,
        _theme=None,
        _wire_mentions_for_dialog=lambda dialog, handler: None,
        _wire_ai_buttons=lambda dialog: None,
        _get_entity_service=lambda entity_type: _StubEntityService(),
    )
    return ApplicationWiring(
        app, window, None, None, None, None, None,
        SimpleNamespace(lock=asyncio.Lock()),
    )


def _spy(wiring: ApplicationWiring) -> list[bool]:
    states: list[bool] = []
    wiring.sheet_stack_changed.connect(states.append)
    return states


def test_open_sheet_announces_the_stack_on_and_off(qtbot):
    """The signal contract: one True for the first sheet, silence while more
    pile up, one False when the stack empties — and the next opening starts
    the announcement again (the gate's whole input, Д2)."""
    host = QWidget()  # stand-in main window: the stack is the connector's
    qtbot.addWidget(host)
    host.show()
    wiring = _make_wiring()
    states = _spy(wiring)

    first = SheetFrame("Лист первый", host)
    wiring.open_sheet(first)
    assert states == [True]
    assert first.isVisible()  # the contract shows the sheet itself (open())

    second = SheetFrame("Лист второй", host)
    wiring.open_sheet(second)
    assert states == [True]  # the stack was already up: no second True

    first.reject()
    assert states == [True]  # one sheet still covers the window
    second.reject()
    assert states == [True, False]  # the last sheet left: the gate reopens

    again = SheetFrame("Лист снова", host)
    wiring.open_sheet(again)
    assert states == [True, False, True]
    again.reject()
    assert states == [True, False, True, False]


def test_reopening_a_surviving_sheet_releases_exactly_once(qtbot, monkeypatch):
    """The reopen contour (NRI-0024 task 5.1, design Д5): the table desk lives
    past its close — the session rides the service. The same sheet returning
    through ``open_sheet`` rejoins the stack and re-announces it, but keeps
    the ONE release channel hooked at its first opening; a second lambda on
    ``finished`` would fire a second ``_release_sheet`` whose ``remove`` raises
    (the exception surfacing through the excepthook recorded below). An entry
    on an already-open sheet only raises the live sheet — never a double
    stack membership."""
    import sys

    host = QWidget()
    qtbot.addWidget(host)
    host.show()
    wiring = _make_wiring()
    states = _spy(wiring)
    errors: list[BaseException] = []
    monkeypatch.setattr(sys, "excepthook", lambda _t, value, _tb: errors.append(value))

    desk = SheetFrame("Стол", host)
    wiring.open_sheet(desk)
    assert states == [True]
    desk.reject()
    assert states == [True, False]

    wiring.open_sheet(desk)  # re-entry raises the SAME desk over the service
    assert states == [True, False, True]
    assert desk.isVisible()
    wiring.open_sheet(desk)  # already up: raised, not stacked twice
    assert states == [True, False, True]
    desk.reject()

    assert states == [True, False, True, False]
    assert errors == []  # one close, one release — no double ``remove``


def test_three_layer_cascade_dims_lower_sheets_harder(qtbot):
    """Task 1.1's «каскад скрэма на трёх слоях» on widget frames: the bottom
    sheet sits two shares down, the middle one share, the top stays clean —
    and each close peels exactly one share back."""
    host = QWidget()
    qtbot.addWidget(host)
    host.show()
    wiring = _make_wiring()
    states = _spy(wiring)

    bottom = SheetFrame("Обзор мира", host)
    middle = SheetFrame("Карточка: Персонаж", bottom)
    top = SheetFrame("Просмотр изображения", middle)
    for frame in (bottom, middle, top):
        wiring.open_sheet(frame)
    assert states == [True]  # nested openings do not re-announce the stack

    assert bottom.sheet_scrim_alpha == pytest.approx(2 * UNIT)
    assert middle.sheet_scrim_alpha == pytest.approx(UNIT)
    assert top.sheet_scrim_alpha == pytest.approx(0.0)
    assert bottom.sheet_scrim_alpha > middle.sheet_scrim_alpha  # «явно темнее»

    top.reject()
    assert middle.sheet_scrim_alpha == pytest.approx(0.0)
    assert bottom.sheet_scrim_alpha == pytest.approx(UNIT)
    assert states == [True]  # the parent sheets are still up

    middle.reject()
    assert bottom.sheet_scrim_alpha == pytest.approx(0.0)
    bottom.reject()
    assert states == [True, False]


def test_widget_sheet_dims_island_ancestors_like_a_child_sheet(qtbot):
    """The generalized walk (task 1.1 «обобщить show-контракт»): the dim no
    longer asks whether the ancestor is an island — a SheetFrame opened over
    an EventDialog darkens the island's sheetScrim layer, and closing lifts
    it back. The connector only knows the scrim duck."""
    host = QWidget()
    qtbot.addWidget(host)
    host.show()
    island = EventDialog(None, parent=host)
    wiring = _make_wiring()

    wiring.open_sheet(island)
    assert island._root.property("sheetScrimAlpha") == pytest.approx(0.0)

    frame = SheetFrame("Просмотр изображения", island)
    wiring.open_sheet(frame)
    assert island._root.property("sheetScrimAlpha") == pytest.approx(UNIT)

    frame.reject()
    assert island._root.property("sheetScrimAlpha") == pytest.approx(0.0)
    island.reject()


class _GateWindow(QWidget):
    """Window stand-in for the gate half of the contract: it records the
    announcements and carries the one real sheet-opening entry the fresh-
    opening test triggers — the shape MainWindow answers with."""

    def __init__(self) -> None:
        super().__init__()
        self.import_xlsx_action = QAction("Импорт из .xlsx…", self)
        self.states: list[bool] = []

    def on_sheet_stack_changed(self, active: bool) -> None:
        self.states.append(active)


def test_connect_sheet_gate_routes_the_stack_on_and_off_to_the_window(qtbot):
    """Task 1.2 (design Д2): ``connect()`` binds the announcement to the
    window's slot, and the gate's whole input is the stack's two edges —
    one True when it rises, one False when it empties; the sheets piling
    up between the edges are the window's silence."""
    window = _GateWindow()
    qtbot.addWidget(window)
    window.show()
    wiring = _make_wiring(window=window)
    wiring._connect_sheet_gate()

    first = SheetFrame("Первый лист", window)
    wiring.open_sheet(first)
    assert window.states == [True]
    second = SheetFrame("Второй лист", first)
    wiring.open_sheet(second)
    assert window.states == [True]  # already up: no re-announcement

    first.reject()
    assert window.states == [True]
    second.reject()
    assert window.states == [True, False]


def test_entry_on_closed_stack_opens_a_fresh_sheet_never_a_duplicate(qtbot):
    """Task 1.3 (``MenuWindowRegistry`` abolished): the real «Импорт из .xlsx…»
    path shows its sheet through the connector's one open path. A repeated
    entry on the closed stack builds a FRESH dialog — the closed one is never
    revived — and at every moment exactly one sheet of it lives: single-
    instance became an emergent property of the gated stack (the entry is
    inactive while a sheet is up, tested on the window side), no window
    bookkeeping left to keep."""
    window = _GateWindow()
    qtbot.addWidget(window)
    window.show()
    wiring = _make_wiring(window=window)
    wiring._connect_xlsx_import()
    states = _spy(wiring)

    def live_imports() -> list:
        return [
            dlg for dlg in window.findChildren(XlsxImportDialog)
            if dlg.isVisible()
        ]

    window.import_xlsx_action.trigger()
    first = live_imports()
    assert len(first) == 1
    assert states == [True]

    first[0].reject()  # every close route passes finished → one release
    assert states == [True, False]
    assert live_imports() == []

    window.import_xlsx_action.trigger()
    reopened = live_imports()
    assert len(reopened) == 1
    assert reopened[0] is not first[0]  # a fresh sheet, never the closed one
    reopened[0].reject()
    assert states == [True, False, True, False]
