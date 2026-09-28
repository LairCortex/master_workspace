"""The «Обзор мира…» menu window end to end (NRI-0022, group 2).

Spec world-snapshot «Обзор мира открывается отдельным окном из строки
меню» on the real Application contour: the bar action opens one non-modal
titled window over the still-working main window; the entry goes through
MenuWindowRegistry (key ``world_snapshot``), so a repeated call raises the
live window instead of stacking copies, and closing releases the slot for a
fresh next opening. Placement (role ``world_snapshot``): the first opening
is the 520×760 default centered, a moved frame is remembered and restored,
an off-screen saved placement returns clamped. The relocated content keeps
its wiring: entity activation from the window opens the editable card
(spec «Активация строки открывает карточку и из окна»).
"""
from __future__ import annotations

import asyncio

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from app.presentation.views.entity_card_dialog import EntityCardDialog
from app.presentation.views.world_snapshot_widget import WorldSnapshotWindow
from app.presentation.window_registry import WORLD_SNAPSHOT_KEY

from tests.ui import helpers


def _live_snapshot_windows() -> list[WorldSnapshotWindow]:
    return [
        w
        for w in QApplication.topLevelWidgets()
        if isinstance(w, WorldSnapshotWindow) and w.isVisible()
    ]


async def test_menu_action_opens_one_live_non_modal_window(app, wait_for):
    application, window = app

    window.world_snapshot_action.trigger()
    snapshot_window = application._window_registry.get(WORLD_SNAPSHOT_KEY)
    assert snapshot_window is not None
    assert snapshot_window.isVisible()
    assert snapshot_window.windowTitle() == "Обзор мира"
    assert snapshot_window.windowModality() == Qt.WindowModality.NonModal
    assert not snapshot_window.isModal()
    # The main window stays working while the snapshot is open.
    assert window.isEnabled()
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
    # by the window instead of the splitter.
    assert hasattr(snapshot_window.snapshot, "snapshot_requested")
    assert callable(snapshot_window.snapshot.populate)

    # Repeated call: the live window is raised, no second copy is built.
    window.world_snapshot_action.trigger()
    await asyncio.sleep(0)
    assert application._window_registry.get(WORLD_SNAPSHOT_KEY) is snapshot_window
    assert _live_snapshot_windows() == [snapshot_window]

    # Closing releases the slot …
    snapshot_window.close()
    assert application._window_registry.get(WORLD_SNAPSHOT_KEY) is None

    # … and the next call opens a fresh window (not the closed one).
    window.world_snapshot_action.trigger()
    fresh = application._window_registry.get(WORLD_SNAPSHOT_KEY)
    assert fresh is not None and fresh is not snapshot_window
    assert _live_snapshot_windows() == [fresh]
    fresh.close()
    await helpers.wait_until_settled()


async def test_snapshot_window_placement_round_trips_and_clamps(app):
    application, window = app
    available = QGuiApplication.primaryScreen().availableGeometry()

    # First opening without a saved frame: 520×760, centered (design D5).
    window.world_snapshot_action.trigger()
    snapshot_window = application._window_registry.get(WORLD_SNAPSHOT_KEY)
    assert snapshot_window.size() == QSize(520, 760)
    placement = snapshot_window.frameGeometry()
    assert available.intersects(placement)
    assert abs(placement.center().x() - available.center().x()) <= 8
    assert abs(placement.center().y() - available.center().y()) <= 8

    # A moved frame is saved on close and restored on the next opening —
    # the frame fits the offscreen screen whole (the exact-frame assert
    # below; a bigger one legitimately comes back shrunk by the clamp).
    snapshot_window.move(120, 100)
    snapshot_window.resize(400, 500)
    saved = snapshot_window.frameGeometry().getRect()
    snapshot_window.close()

    window.world_snapshot_action.trigger()
    reopened = application._window_registry.get(WORLD_SNAPSHOT_KEY)
    assert reopened is not None and reopened is not snapshot_window
    # The pre-show restore sizes the HIDDEN window (its scene must not
    # relayout), so the saved frame returns whole up to the platform's
    # decoration stub — the same ±8 slack test_geometry_memory._fits pins
    # for every geometry-memory round trip; the position is exact.
    restored = reopened.frameGeometry()
    assert (restored.x(), restored.y()) == (saved[0], saved[1])
    assert abs(restored.width() - saved[2]) <= 8
    assert abs(restored.height() - saved[3]) <= 8
    reopened.close()

    # A placement that fell off the connected displays comes back clamped
    # inside a screen (spec main-window «Размещение окон помнится …»).
    application._geometries._roles[WORLD_SNAPSHOT_KEY] = [
        99999, 99999, 480, 700,
    ]
    window.world_snapshot_action.trigger()
    clamped = application._window_registry.get(WORLD_SNAPSHOT_KEY)
    assert clamped is not None
    assert available.intersects(clamped.frameGeometry())
    # Left open on purpose: shutdown must take the session-bound window
    # with the game (the fixture's application.shutdown exercises the path).


async def test_entity_activation_in_the_snapshot_window_opens_the_card(
    app, wait_for, menu_qmenu
):
    """Spec scenario «Активация строки открывает карточку и из окна».

    The relocation changed the host, not the wiring: the panel's
    ``entity_clicked`` still runs through the connector's entity-card path.
    """
    application, window = app
    await helpers.create_entity_via_context_menu(
        window, wait_for, menu_qmenu, "character", "ВестникОбзора"
    )
    await helpers.wait_until_settled()

    snapshot = helpers.open_world_snapshot(application, window)
    snapshot.entity_clicked.emit("character", 1)
    await wait_for(
        lambda: any(
            card.isVisible() and card._entity_type == "character"
            for card in window.findChildren(EntityCardDialog)
        )
    )
