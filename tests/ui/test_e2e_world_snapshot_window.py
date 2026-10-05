"""The «Обзор мира…» menu sheet end to end (NRI-0022 group 2; sheet since NRI-0024 task 2.4).

Spec world-snapshot «Обзор мира открывается листом из строки меню» on the
real Application contour: the «Файл» entry opens the snapshot as a SHEET —
header «Обзор мира», WindowModal over the main window, the 520×760 default at
the default window size. The repeated call is unreachable while the sheet is
up (the entry is gated — «Повторный вызов недостижим»), and the sheet never
remembers a placement («Лист не помнит рамку»): a frame left under the old
window role is silently ignored, close→reopen returns the default. The
relocated content keeps its wiring: entity activation from the sheet opens
the editable card OVER the sheet, the scrim cascade dims the covered sheet,
and closing the card leaves the sheet alive (spec «Активация строки открывает
карточку поверх листа»).
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QApplication, QLabel

from app.presentation.views.entity_card_dialog import EntityCardDialog
from app.presentation.views.world_snapshot_widget import WorldSnapshotWindow
from app.presentation.wiring import SHEET_SCRIM_ALPHA_PER_SHEET

from tests.ui import helpers

#: The ui.json key of the retired «Обзор мира» window role (NRI-0024 task
#: 6.1 deleted the role; the ignore-pin below deliberately writes this key).
LEGACY_SNAPSHOT_ROLE = "world_snapshot"


def _live_snapshot_sheets() -> list[WorldSnapshotWindow]:
    return [
        w
        for w in QApplication.topLevelWidgets()
        if isinstance(w, WorldSnapshotWindow) and w.isVisible()
    ]


async def test_menu_action_opens_a_gated_sheet_at_the_default_size(app, wait_for):
    application, window = app
    assert window.world_snapshot_action.isEnabled()

    window.world_snapshot_action.trigger()
    sheet = application._wiring.snapshot_sheet
    assert sheet is not None
    assert sheet.isVisible()
    # Sheet chrome (spec «лист с шапкой»): one windowTitle-threaded caption.
    assert sheet.windowTitle() == "Обзор мира"
    assert sheet.findChild(QLabel, "sheetFrameTitle").text() == "Обзор мира"
    # Sheet class, not the retired window: an attached native sheet (Qt.Sheet,
    # NonModal at Qt level — PR-012) over the main layer (spec modal-sheets
    # «Контент открывается листом»).
    assert sheet.windowFlags() & Qt.WindowType.Sheet
    assert sheet.windowModality() == Qt.WindowModality.NonModal
    # Default size (design Д6) at the default main window height.
    assert sheet.size() == QSize(520, 760)
    # The entry is reachable through the «Файл» submenu — a bare bar-level
    # QAction never survives the macOS cocoa bridge (live audit 2026-09-27,
    # FU-1), so it sits beside «Сменить игру…» / «Экспорт игры…».
    from PySide6.QtWidgets import QMenu

    assert window.world_snapshot_action not in window.menuBar().actions()
    file_menu = next(
        m for m in window.menuBar().findChildren(QMenu) if m.title() == "Файл"
    )
    assert window.world_snapshot_action in file_menu.actions()
    # The wiring surface moved with the panel — same signals, now hosted
    # by the sheet instead of a window of its own.
    assert hasattr(sheet.snapshot, "snapshot_requested")
    assert callable(sheet.snapshot.populate)

    # «Повторный вызов недостижим»: with the stack up the entry is gated
    # (task 1.2's gate), so a second copy of the sheet cannot form.
    assert not window.world_snapshot_action.isEnabled()
    assert _live_snapshot_sheets() == [sheet]

    sheet.close()
    assert application._wiring.snapshot_sheet is None
    assert window.world_snapshot_action.isEnabled()

    # The next entry opens a FRESH sheet — the closed one is never revived.
    window.world_snapshot_action.trigger()
    fresh = application._wiring.snapshot_sheet
    assert fresh is not None and fresh is not sheet
    assert fresh.isVisible()
    fresh.close()
    await helpers.wait_until_settled()


async def test_the_sheet_never_remembers_a_placement(app, wait_for):
    """Spec «Лист не помнит рамку» incl. the migration clause: a frame an
    older window-era run saved under role ``world_snapshot`` is silently
    ignored — the sheet opens at its default; a resized, closed and reopened
    sheet returns the default too, not the stretched size."""
    application, window = app
    application._geometries._roles[LEGACY_SNAPSHOT_ROLE] = [
        99999, 99999, 480, 700,
    ]

    window.world_snapshot_action.trigger()
    sheet = application._wiring.snapshot_sheet
    assert sheet.size() == QSize(520, 760)  # the saved 480×700 never lands

    sheet.resize(400, 500)  # «растянут до предела» of this test's making
    sheet.close()

    window.world_snapshot_action.trigger()
    reopened = application._wiring.snapshot_sheet
    assert reopened is not None and reopened is not sheet
    assert reopened.size() == QSize(520, 760)  # the default, never the stretched
    reopened.close()
    await helpers.wait_until_settled()


async def test_a_saved_entity_shows_in_the_sheet_with_no_events_at_all(
    app, wait_for, menu_qmenu
):
    """PR-019 (spec world-snapshot «Секции снимка» + entity-addition «Успешное
    создание»): a location created out of the «+» menu of an event-less game is
    the world's current state, so «Обзор мира…» paints its section — the
    «Нет событий в игре» hint belongs to the events section and never replaces
    the whole snapshot.
    """
    application, window = app
    await helpers.create_entity_via_context_menu(
        window, wait_for, menu_qmenu, "location", "Тестовая локация"
    )
    await helpers.wait_until_settled()

    panel = helpers.open_world_snapshot(application, window)
    panel.vm.requestShowAll()  # the user's «Показать всё» in a world of zero events
    await helpers.wait_until_settled()

    rows = panel.vm._model.rows
    assert [
        row["displayText"] for row in rows if row["rowKind"] == "sectionHeader"
    ] == ["Локации (1)"]
    assert [
        (row["type"], row["name"]) for row in rows if row["rowKind"] == "entityRow"
    ] == [("location", "Тестовая локация")]
    # the events section's emptiness never took the panel over, and the counts
    # of the statistics line read the world as it is
    assert panel.vm.emptyText == ""
    assert "Событий: 0" in panel.vm.statsText
    assert "Локаций: 1" in panel.vm.statsText

    application._wiring.close_snapshot_sheet()
    await helpers.wait_until_settled()


async def test_entity_activation_in_the_sheet_opens_the_card_over_it(
    app, wait_for, menu_qmenu
):
    """Spec scenario «Активация строки открывает карточку поверх листа».

    The relocation changed the container, not the wiring: the panel's
    ``entity_clicked`` still runs the connector's entity-card path — but now
    the sheet is the card's Qt parent, so the two layers stack and the scrim
    cascade is distinguishable; the card's close peels the share back and
    the snapshot sheet stays open and live under it.
    """
    application, window = app
    await helpers.create_entity_via_context_menu(
        window, wait_for, menu_qmenu, "character", "ВестникОбзора"
    )
    await helpers.wait_until_settled()

    helpers.open_world_snapshot(application, window)
    sheet = application._wiring.snapshot_sheet
    sheet.snapshot.entity_clicked.emit("character", 1)
    await wait_for(
        lambda: any(
            card.isVisible() and card._entity_type == "character"
            for card in window.findChildren(EntityCardDialog)
        )
    )
    card = next(
        card
        for card in window.findChildren(EntityCardDialog)
        if card.isVisible() and card._entity_type == "character"
    )

    # The stack: the card was born on the sheet, its modal parent —
    assert card.parent() is sheet
    # and the cascade is distinguishable: the covered sheet sits one share
    # under color.scrim while the top card stays clean.
    assert sheet.sheet_scrim_alpha == pytest.approx(SHEET_SCRIM_ALPHA_PER_SHEET)
    # (the island publishes its dim through the scene property, the widget
    # frame through the alpha duck — the same zero, two faces)
    assert float(card._root.property("sheetScrimAlpha")) == pytest.approx(0.0)

    # Closing the card returns exactly to the previous layer: the snapshot
    # sheet is open, undimmed and still the tracked one.
    card.reject()
    await wait_for(lambda: sheet.sheet_scrim_alpha == pytest.approx(0.0))
    assert sheet.isVisible()
    assert application._wiring.snapshot_sheet is sheet
    sheet.close()
    await helpers.wait_until_settled()
