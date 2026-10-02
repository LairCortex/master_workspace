"""«Обзор мира» as a sheet (NRI-0022 group 2; sheet format since NRI-0024 task 2.4).

Spec world-snapshot «Обзор мира открывается листом из строки меню»: the panel
that used to sit in a non-modal window of its own now rides the application's
sheet contract. The wrapper is a ``SheetFrame`` — header «Обзор мира + Закрыть»
(one windowTitle-threaded caption, SheetFrame's own chrome pinned in
``test_sheet_frame``) over the untouched QML island, shown by the connector's
one ``open_sheet`` path (WindowModal, the stack, the single ``finished``
release). Because a child widget never sees a closeEvent when its dialog
closes, the sheet releases the island itself on every route out (done covers
«Закрыть»/Esc/close()). The sheet never remembers a placement: the old role's
frame may still sit in ui.json — the flow no longer reads the geometry memory,
the sheet opens at its default 520×760 and stores nothing on the way out
(spec «Лист не помнит рамку»). The height tracks the parent window (growth to
the default, shrink to the usability floor — spec modal-sheets «Окно растёт —
лист догоняет до предела»), and a row activation opens the entity card OVER
the sheet: the sheet is the card's Qt parent, so the stack dims it one share
and the card's close peels the share back, the sheet staying open and live
(spec «Активация строки открывает карточку поверх листа»).
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QSize, Qt, QUrl, Signal
from PySide6.QtWidgets import QLabel, QWidget

from app.domain.theme import DEFAULT_THEME
from app.infrastructure.ui_prefs.config import UiPrefs, UiPrefsManager
from app.presentation.views.sheet_frame import SheetFrame
from app.presentation.views.world_snapshot_widget import (
    WorldSnapshotWidget,
    WorldSnapshotWindow,
)
from app.presentation.wiring import (
    ApplicationWiring,
    SHEET_SCRIM_ALPHA_PER_SHEET,
)

#: The ui.json key the retired window era left behind (NRI-0024 task 6.1
#: removed the role for good — no app code reads it anymore). Kept here as a
#: legacy-fixture literal: the ignore-pins below are exactly about this key.
LEGACY_SNAPSHOT_ROLE = "world_snapshot"

#: The default main window (NRI-0018 Д5) — the height the sheet default 760
#: is the growth rule's value at.
MAIN_DEFAULT_SIZE = (1280, 800)


def _main_window(qtbot, size: tuple[int, int] = MAIN_DEFAULT_SIZE) -> QWidget:
    """Stand-in for the real main window: the growth rule reads the host's
    height, so the stub stands at a chosen window size."""
    main = QWidget()
    qtbot.addWidget(main)
    main.resize(*size)
    main.show()
    return main


def _drain():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


def _header_title(sheet: WorldSnapshotWindow) -> str:
    return sheet.findChild(QLabel, "sheetFrameTitle").text()


# ── the sheet home: header, default size, modality, island release ──────────


def test_wrapper_is_the_sheet_home_at_the_default_size(qtbot):
    main = _main_window(qtbot)  # stand-in parent: the modality rule is the sheet's
    # The host alone goes to qtbot — the sheet hangs C++-owned under it
    # (the convention of test_sheet_stack_contract).
    sheet = WorldSnapshotWindow(parent=main)

    assert sheet.windowTitle() == "Обзор мира"
    # Header names the sheet with the same value as windowTitle (spec
    # modal-sheets «текст, соответствующий windowTitle»).
    assert _header_title(sheet) == "Обзор мира"
    assert isinstance(sheet.snapshot, WorldSnapshotWidget)
    # The island is the panel untouched — same VM, same bridge objects.
    assert sheet.snapshot.quick is not None

    # The sheet default (design Д6): 520×760.
    assert sheet.size() == QSize(520, 760)

    sheet.open()  # the show half of ApplicationWiring.open_sheet
    # Sheet class (spec modal-sheets): WindowModal over the main layer.
    assert sheet.windowModality() == Qt.WindowModality.WindowModal
    assert sheet.isVisible()


def test_height_tracks_the_parent_window_up_to_the_default(qtbot):
    """Spec modal-sheets «Окно растёт — лист догоняет до предела»: at the
    default 800-tall window the rule lands exactly on the default height; a
    smaller window shrinks the sheet (the island's own ListView scrolls the
    rest), a bigger one grows it back to the 760 cap, never below the
    usability floor; a CLOSED sheet stops chasing resizes with its filter."""
    main = _main_window(qtbot)
    sheet = WorldSnapshotWindow(parent=main)
    sheet.open()
    assert sheet.size() == QSize(520, 760)  # default window → default size

    main.resize(1280, 600)  # window shrinks — the sheet fits itself to it
    assert sheet.height() == 560
    main.resize(1280, 300)  # …but never under the MIN_SIZE usability floor
    assert sheet.height() == WorldSnapshotWindow.MIN_SIZE.height()
    main.resize(1280, 900)  # window grows — the sheet catches up to its cap
    assert sheet.size() == QSize(520, 760)

    sheet.done(0)  # the growth filter leaves with the closed sheet (done())
    main.resize(1280, 500)
    assert sheet.height() == 760  # a closed layer never resizes again


def test_closing_the_sheet_releases_the_panel_island(qtbot):
    sheet = WorldSnapshotWindow()  # parent-less home: no growth tracking there
    qtbot.addWidget(sheet)
    sheet.show()
    quick = sheet.snapshot.quick
    assert quick.rootObject() is not None

    sheet.close()  # closeEvent → done(Rejected) — a production exit path

    # The child island left the scene one loop turn after the sheet closed
    # — the contract IslandDialogMixin pins for its own islands.
    _drain()
    qtbot.wait(1)
    assert quick.source() == QUrl()


# ── the connector's snapshot section: entry, stack, teardown ────────────────


class _SnapshotMenuWindow(QWidget):
    """MainWindow stand-in for the connector's snapshot section: carries
    the one signal the section wires its entry to."""

    world_snapshot_requested = Signal()

    def on_sheet_stack_changed(self, active: bool) -> None:
        pass  # the gate itself is pinned in TestSheetStackMenuGate


class _EntityService:
    async def get_entity(self, entity_id: int):
        return SimpleNamespace(id=entity_id, name="Кто-то")


class _CardStandIn(SheetFrame):
    """The factory's return shape for the card-opening route: a real dialog
    (finished/open/scrim duck) plus the one signal the handler connects."""

    create_related_requested = Signal(str, object)


def _snapshot_wiring(tmp_path, qtbot, *, saved_placement=None):
    """The connector around the real «Обзор мира…» menu path. The factory of
    the sheet format reads NO ``_geometries`` off the application at all —
    the attribute is absent from the stub on purpose, so any renewed contact
    with the geometry memory fails here, not silently. ``saved_placement``
    pre-seeds the OLD window role's frame in the prefs file."""
    prefs = UiPrefsManager(tmp_path / "ui.json")
    if saved_placement is not None:
        prefs.save(
            UiPrefs(
                theme=DEFAULT_THEME,
                windows={LEGACY_SNAPSHOT_ROLE: list(saved_placement)},
            )
        )
    app = SimpleNamespace(
        _image_store=None,
        _theme=None,
        _wire_mentions_for_dialog=lambda dialog, handler: None,
        _wire_ai_buttons=lambda dialog: None,
        _get_entity_service=lambda entity_type: _EntityService(),
    )
    menu_window = _SnapshotMenuWindow()
    qtbot.addWidget(menu_window)
    menu_window.resize(*MAIN_DEFAULT_SIZE)
    menu_window.show()
    wiring = ApplicationWiring(
        app, menu_window, None, None, None, None, None,
        SimpleNamespace(lock=asyncio.Lock()),
    )
    wiring._connect_snapshot()
    return wiring, menu_window


def _stub_card_factory(wiring, monkeypatch, cards: list[_CardStandIn]) -> None:
    """Swap the heavy EntityCardDialog factory for a SheetFrame stand-in
    seated on the parent the handler passes — the parent threading is the
    wiring half this file pins; the real card over the real sheet is e2e."""

    async def fake_open_entity_card(
        self, entity_type, *, parent, on_saved, entity=None,
        load_available=True, popup_cleanup=False,
    ):
        card = _CardStandIn(f"Карточка: {entity_type}", parent)
        cards.append(card)
        return card

    async def no_character_sheet(self, dialog, entity_type, entity_id):
        return None

    monkeypatch.setattr(ApplicationWiring, "_open_entity_card", fake_open_entity_card)
    monkeypatch.setattr(
        ApplicationWiring, "_wire_open_character_sheet", no_character_sheet,
    )


def test_entry_opens_a_fresh_sheet_the_connector_tracks_then_forgets(qtbot, tmp_path):
    """Every menu entry opens a FRESH sheet through open_sheet (the entry is
    gated while the stack is up — window side; nothing revives a closed one),
    the connector tracks the live sheet, and a close of the tracked one
    releases the slot through ``finished``; the stale guard keeps a late
    close of an older sheet from forgetting a newer tracked one. Closing
    still releases the island resource the fresh next sheet must redo."""
    wiring, menu_window = _snapshot_wiring(tmp_path, qtbot)
    assert wiring.snapshot_sheet is None

    menu_window.world_snapshot_requested.emit()
    first = wiring.snapshot_sheet
    assert first is not None and first.isVisible()
    # The show contract is the sheet one, not the retired window's show().
    assert first.windowModality() == Qt.WindowModality.WindowModal
    assert first.size() == QSize(520, 760)

    menu_window.world_snapshot_requested.emit()
    second = wiring.snapshot_sheet
    assert second is not None and second is not first  # fresh per entry

    first.close()  # the stale close must not clear the newer tracking
    assert wiring.snapshot_sheet is second
    second.close()
    assert wiring.snapshot_sheet is None

    _drain()
    qtbot.wait(1)
    assert first.snapshot.quick.source() == QUrl()
    assert second.snapshot.quick.source() == QUrl()


def test_close_snapshot_sheet_takes_the_tracked_sheet_with_the_game(qtbot, tmp_path):
    """Application.shutdown's teardown of the session-bound sheet (NRI-0022
    task 2.1; the slot renamed with the class in task 2.4): the live sheet
    goes down with the game and is forgotten, and the teardown is idempotent
    without one."""
    wiring, menu_window = _snapshot_wiring(tmp_path, qtbot)
    menu_window.world_snapshot_requested.emit()
    live = wiring.snapshot_sheet
    assert live is not None and live.isVisible()

    wiring.close_snapshot_sheet()
    assert not live.isVisible()
    assert wiring.snapshot_sheet is None
    wiring.close_snapshot_sheet()  # no tracked sheet: a silent no-op


def test_saved_window_placement_is_silently_ignored_by_the_sheet(qtbot, tmp_path):
    """The migration rule of spec world-snapshot (REMOVED requirement's
    Migration): a frame an older run left in ui.json under the old ``world_
    snapshot`` role never reaches the sheet — opening reads no geometry
    memory, so the sheet stands at its default; closing stores nothing, the
    legacy key sits untouched, and a reopen is the default again."""
    wiring, menu_window = _snapshot_wiring(
        tmp_path, qtbot, saved_placement=[99999, 99999, 480, 700],
    )
    menu_window.world_snapshot_requested.emit()
    sheet = wiring.snapshot_sheet
    assert sheet.size() == QSize(520, 760)  # the default, not the saved 480×700

    sheet.move(50, 40)
    sheet.close()
    saved = UiPrefsManager(tmp_path / "ui.json").load().windows
    assert saved.get(LEGACY_SNAPSHOT_ROLE) == [99999, 99999, 480, 700]

    menu_window.world_snapshot_requested.emit()
    again = wiring.snapshot_sheet
    assert again.size() == QSize(520, 760)
    again.close()


# ── row activation: the card opens OVER the sheet (stack + cascade) ─────────


async def test_row_activation_opens_the_card_over_the_sheet(qtbot, tmp_path, monkeypatch):
    """Spec «Активация строки открывает карточку поверх листа»: the panel's
    ``entity_clicked`` routes through the connector's entity-card path with
    the sheet as the card's Qt parent — the parent chain IS the stack, so a
    two-layer stack forms (sheet + card) and the scrim cascade dims the
    covered sheet one share while the top card stays clean. Closing the card
    peels exactly that share back: the sheet is alive and open underneath."""
    wiring, menu_window = _snapshot_wiring(tmp_path, qtbot)
    menu_window.world_snapshot_requested.emit()
    sheet = wiring.snapshot_sheet
    cards: list[_CardStandIn] = []
    _stub_card_factory(wiring, monkeypatch, cards)

    sheet.snapshot.entity_clicked.emit("character", 7)
    # The handler runs through _spawn (ensure_future on this very loop): a
    # few loop turns and the card exists.
    for _ in range(50):
        await asyncio.sleep(0)
        if cards:
            break
    assert len(cards) == 1
    card = cards[0]

    assert card.parent() is sheet  # born over the sheet, not on the main layer
    assert card.isVisible()
    assert sheet.sheet_scrim_alpha == pytest.approx(SHEET_SCRIM_ALPHA_PER_SHEET)
    assert card.sheet_scrim_alpha == pytest.approx(0.0)

    card.reject()  # «после закрытия карточки лист жив»
    assert not card.isVisible()
    assert sheet.isVisible()
    assert wiring.snapshot_sheet is sheet
    assert sheet.sheet_scrim_alpha == pytest.approx(0.0)


async def test_activation_without_a_sheet_parent_keeps_the_main_window(qtbot, tmp_path, monkeypatch):
    """The unchanged half: every route that does NOT come from the snapshot
    row (detail panel, search, mentions) still parents the card to the main
    window — the new parameter defaults away and the old behavior stands."""
    wiring, menu_window = _snapshot_wiring(tmp_path, qtbot)
    cards: list[_CardStandIn] = []
    _stub_card_factory(wiring, monkeypatch, cards)

    await wiring._on_entity_click("character", 7)
    assert cards[0].parent() is menu_window
    cards[0].reject()
