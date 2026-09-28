"""«Обзор мира» as its own top-level window (NRI-0022, group 2).

Spec world-snapshot «Обзор мира открывается отдельным окном из строки
меню»: the panel that used to sit in the main window's third splitter
column now lives in a non-modal, titled, natively closable window. The
wrapper hosts the untouched QML island and, because a child widget never
sees a closeEvent when its window closes, releases the island itself on
every route out of the dialog (done covers ✕/Esc/close()). The geometry
role ``world_snapshot`` rides the one WindowGeometryMemory the other named
windows use: first opening without a saved frame is 520×760 centered, the
remembered frame returns clamped into a connected screen.
"""
from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QEvent, QSize, Qt, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget

from app.domain.theme import DEFAULT_THEME
from app.infrastructure.ui_prefs.config import UiPrefs, UiPrefsManager
from app.presentation.geometry_memory import WindowGeometryMemory
from app.presentation.views.world_snapshot_widget import (
    WorldSnapshotWidget,
    WorldSnapshotWindow,
)
from app.presentation.window_registry import (
    WORLD_SNAPSHOT_KEY,
    MenuWindowRegistry,
)


def _available():
    return QGuiApplication.primaryScreen().availableGeometry()


def _drain():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


# ── task 2.1: the wrapper is a non-modal titled home ────────────────────────


def test_wrapper_is_a_non_modal_titled_home_at_the_default_size(qtbot):
    main = QWidget()  # stand-in parent: the modality rule is the wrapper's
    qtbot.addWidget(main)
    main.show()
    window = WorldSnapshotWindow(parent=main)
    qtbot.addWidget(window)

    assert window.windowTitle() == "Обзор мира"
    # Explicit NonModal pins the window-format contract (NRI-0014 AB3 class).
    assert window.windowModality() == Qt.WindowModality.NonModal
    assert isinstance(window.snapshot, WorldSnapshotWidget)
    # The island is the panel untouched — same VM, same bridge objects.
    assert window.snapshot.quick is not None

    # First opening without any remembered placement: 520×760 (design D5).
    assert window.size() == QSize(520, 760)

    window.show()
    # The main window stays working while the snapshot is open (spec
    # scenario «главное окно остаётся рабочим»).
    assert not window.isModal()
    assert main.isEnabled()


def test_closing_the_window_releases_the_panel_island(qtbot):
    window = WorldSnapshotWindow()
    qtbot.addWidget(window)
    window.show()
    quick = window.snapshot.quick
    assert quick.rootObject() is not None

    window.close()  # closeEvent → done(Rejected) — the production exit path
    _drain()
    qtbot.wait(1)

    # The child island left the scene one loop turn after the window closed
    # — the contract IslandDialogMixin pins for its own islands.
    assert quick.source() == QUrl()


def test_registry_open_dedups_and_close_releases_slot_and_resource(qtbot):
    # Tasks 2.1/2.2 over the same mechanism the docs/LLM entries use: the
    # registry raises the live window instead of stacking, closing releases
    # the key AND the island resource the fresh next window needs to redo.
    registry = MenuWindowRegistry()
    window = registry.open(WORLD_SNAPSHOT_KEY, WorldSnapshotWindow)
    qtbot.addWidget(window)
    assert window.isVisible()

    again = registry.open(WORLD_SNAPSHOT_KEY, WorldSnapshotWindow)
    assert again is window  # copies do not multiply

    window.close()
    assert registry.get(WORLD_SNAPSHOT_KEY) is None
    _drain()
    qtbot.wait(1)
    assert window.snapshot.quick.source() == QUrl()


# ── task 2.3: role world_snapshot in the geometry memory ────────────────────


def test_first_open_without_a_saved_frame_is_centered_at_the_default_size(
    tmp_path, qtbot
):
    # The production opening order from the wiring factory: restore (shrink
    # while hidden) → show → post_show_place (centering + tracker).
    memory = WindowGeometryMemory(UiPrefsManager(tmp_path / "ui.json"))
    window = WorldSnapshotWindow()
    qtbot.addWidget(window)

    remembered = memory.restore(
        window, WORLD_SNAPSHOT_KEY, center_when_absent=True
    )
    assert remembered is False  # a fresh user has no saved role
    window.show()
    memory.post_show_place(window, WORLD_SNAPSHOT_KEY, remembered=remembered)

    # The default frame fits the offscreen screen (800×800) whole, so the
    # pre-show shrink changes nothing and 520×760 stands (design D5).
    assert window.size() == QSize(520, 760)
    available = _available()
    placement = window.frameGeometry()
    assert available.intersects(placement)
    # …and the first opening is deterministic: the screen center, never a
    # corner born off-screen (B4 rule).
    assert abs(placement.center().x() - available.center().x()) <= 8
    assert abs(placement.center().y() - available.center().y()) <= 8


def test_close_remembers_the_frame_and_the_reopening_restores_it(tmp_path, qtbot):
    prefs = UiPrefsManager(tmp_path / "ui.json")
    memory = WindowGeometryMemory(prefs)
    window = WorldSnapshotWindow()
    qtbot.addWidget(window)
    memory.attach(window, WORLD_SNAPSHOT_KEY, center_when_absent=True)
    window.show()

    # A frame that fits the offscreen screen whole (the saved rect includes
    # the 2 px stub decoration) — a bigger one would legitimately come back
    # shrunk by the clamp, which the next test pins.
    window.move(100, 80)
    window.resize(400, 500)
    saved = window.frameGeometry().getRect()
    window.close()  # the close save is guaranteed, no debounce wait

    assert prefs.load().windows[WORLD_SNAPSHOT_KEY] == list(saved)

    # The next "run": a fresh manager, a fresh window — the role comes back.
    reopened_memory = WindowGeometryMemory(prefs)
    other = WorldSnapshotWindow()
    qtbot.addWidget(other)
    assert reopened_memory.restore(other, WORLD_SNAPSHOT_KEY) is True
    assert other.frameGeometry().getRect() == saved


def test_saved_offscreen_frame_returns_clamped_into_the_screen(tmp_path, qtbot):
    prefs = UiPrefsManager(tmp_path / "ui.json")
    prefs.save(
        UiPrefs(
            theme=DEFAULT_THEME,
            windows={WORLD_SNAPSHOT_KEY: [99999, 99999, 480, 700]},
        )
    )
    memory = WindowGeometryMemory(prefs)
    window = WorldSnapshotWindow()
    qtbot.addWidget(window)

    assert memory.restore(window, WORLD_SNAPSHOT_KEY) is True
    available = _available()
    assert available.intersects(window.frameGeometry())
