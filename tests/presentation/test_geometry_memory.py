"""Window geometry memory (NRI-0015 task 1.3, design T3).

Spec main-window «Размещение окон помнится и возвращается в экраны»:

* round-trip — a placement saved by one manager (remember on move quiescence
  / on close) comes back through a freshly loaded one, byte-for-byte equal in
  ``UiPrefs.windows`` (role -> [x, y, w, h] in ui.json);
* clamp — a saved role whose coordinates fell off the connected displays is
  restored inside a screen (intersection asserted, whole-window contained);
* B4 — a first-opening window without a remembered role (the editor/Fill
  rule, ``center_when_absent``) is placed entirely in its screen;
* the theme switch and the geometry save are symmetric — neither owner of
  the one ui.json ever wipes the other's field.
"""
from __future__ import annotations

import json

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget

from app.domain.theme import DEFAULT_THEME
from app.infrastructure.ui_prefs.config import UiPrefs, UiPrefsManager
from app.presentation.geometry_memory import DEBOUNCE_MS, WindowGeometryMemory


def _available():
    return QGuiApplication.primaryScreen().availableGeometry()


def _fits(area, rect) -> bool:
    """Containment with the platform's frame-decoration slack: the offscreen
    stub paints a 2 px border (a real window manager has its own margins
    that only exist after map) — the saved FRAME must come back inside the
    screen up to that slack; strict intersection (task's pin) is asserted
    separately."""
    return area.adjusted(-8, -8, 8, 8).contains(rect)


def _shown(qtbot, size=(400, 300), before_show=None) -> QWidget:
    window = QWidget()
    qtbot.addWidget(window)
    window.resize(*size)
    if before_show is not None:
        before_show(window)
    window.show()
    return window


# ── round-trip: saved ↔ read back ───────────────────────────────────────────


def test_saved_placement_round_trips_through_the_prefs_file(tmp_path, qtbot):
    prefs = UiPrefsManager(tmp_path / "ui.json")
    memory = WindowGeometryMemory(prefs)
    window = _shown(qtbot)
    memory.attach(window, "sheet_editor", center_when_absent=True)

    window.move(120, 90)
    window.resize(640, 480)
    qtbot.wait(DEBOUNCE_MS + 400)  # one debounced write after the burst

    saved = window.frameGeometry().getRect()
    assert prefs.load().windows == {"sheet_editor": list(saved)}

    # The next "run": a fresh manager, a fresh window — the role comes back.
    reopened = WindowGeometryMemory(prefs)
    other = _shown(qtbot, size=(200, 200))
    assert reopened.restore(other, "sheet_editor") is True
    assert other.frameGeometry().getRect() == saved
    # A role nobody ever saved is reported as absent.
    assert reopened.restore(other, "table_host") is False


def test_close_saves_the_placement_guaranteed_not_only_debounced(tmp_path, qtbot):
    prefs = UiPrefsManager(tmp_path / "ui.json")
    memory = WindowGeometryMemory(prefs)
    window = _shown(qtbot)
    memory.attach(window, "main")

    window.move(140, 120)
    window.close()  # no debounce wait: the close save is immediate

    assert prefs.load().windows["main"][:2] == [140, 120]


# ── clamp: a role from an off-screen world returns inside a screen ──────────


def test_offscreen_saved_role_is_restored_into_the_screen(tmp_path, qtbot):
    prefs = UiPrefsManager(tmp_path / "ui.json")
    prefs.save(
        UiPrefs(
            theme=DEFAULT_THEME,
            windows={
                "main": [99999, 99999, 300, 200],
                "sheet_list": [-9999, -9999, 400, 300],
            },
        )
    )
    memory = WindowGeometryMemory(prefs)
    available = _available()

    for role, size in (("main", (300, 200)), ("sheet_list", (400, 300))):
        window = _shown(qtbot, size=size)
        assert memory.restore(window, role) is True
        placement = window.frameGeometry()
        # task pin: intersection first…
        assert available.intersects(placement)
        # …and the saved rectangle fits, so it comes back whole up to the
        # platform's decoration slack.
        assert _fits(available, placement)


def test_bigger_than_screen_saved_role_keeps_a_reachable_corner(tmp_path, qtbot):
    prefs = UiPrefsManager(tmp_path / "ui.json")
    prefs.save(UiPrefs(theme=DEFAULT_THEME, windows={"main": [-40, 20, 2560, 1440]}))
    memory = WindowGeometryMemory(prefs)

    window = _shown(qtbot, size=(100, 100))
    assert memory.restore(window, "main") is True
    assert _available().intersects(window.frameGeometry())
    assert _fits(_available(), window.frameGeometry())


# ── B4: first opening without a role is centered, entirely on screen ────────


def test_first_open_without_role_is_shrunk_then_centered_in_screen(tmp_path, qtbot):
    # NRI-0015 (B4) in its production order: shrink before show (the scene is
    # cheap to size then), the frame-aware centering move after show, then the
    # tracker takes over (post_show_place).
    memory = WindowGeometryMemory(UiPrefsManager(tmp_path / "ui.json"))
    window = _shown(qtbot, size=(1280, 800), before_show=lambda w: memory.restore(
        w, "sheet_editor", center_when_absent=True
    ))
    memory.post_show_place(window, "sheet_editor")

    assert memory.restore(window, "sheet_editor", center_when_absent=True) is False
    placement = window.frameGeometry()
    available = _available()
    assert available.intersects(placement)
    assert _fits(available, placement)
    # …and the placement is deterministic: the center of the available area
    assert abs(placement.center().x() - available.center().x()) <= 8
    assert abs(placement.center().y() - available.center().y()) <= 8


def test_no_center_rule_keeps_an_unremembered_window_untouched(tmp_path, qtbot):
    memory = WindowGeometryMemory(UiPrefsManager(tmp_path / "ui.json"))
    window = _shown(qtbot)
    before = window.geometry()

    assert memory.restore(window, "main") is False
    assert window.geometry() == before


# ── the one ui.json: theme and windows must not evict each other ────────────


def test_theme_switch_preserves_roles_and_remember_preserves_theme(tmp_path, qtbot):
    from app.presentation.theme.compiler import tokens_file_path
    from app.presentation.theme.runtime import ThemeRuntime

    prefs = UiPrefsManager(tmp_path / "ui.json")
    runtime = ThemeRuntime(prefs=prefs, tokens_path=tokens_file_path())
    memory = WindowGeometryMemory(prefs)
    window = _shown(qtbot)
    memory.remember("main", window)  # saves onto the theme-only file

    assert runtime.set_theme("light") is True
    assert prefs.load().windows.get("main") is not None  # theme kept windows

    memory.remember("table_host", window)
    assert prefs.load().theme == "light"  # windows kept the theme


# ── the serialized shape is defensive (garbage entries never poison the rest) ──


def test_malformed_window_entries_are_dropped_others_survive(tmp_path):
    prefs = UiPrefsManager(tmp_path / "ui.json")
    prefs.config_file.write_text(
        json.dumps(
            {
                "theme": "dark",
                "windows": {
                    "main": [10, 20, 300, 200],
                    "short": [1, 2],
                    "strings": ["a", 2, 3, 4],
                    "flag": [True, 2, 3, 4],
                    "scalar": 5,
                },
            }
        ),
        encoding="utf-8",
    )

    assert WindowGeometryMemory(prefs)._roles == {"main": [10, 20, 300, 200]}
    assert not prefs.config_file.read_text(encoding="utf-8").endswith("\n\n")
