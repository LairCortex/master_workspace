"""Sheet islands clear their framebuffer to the sheet canvas (finding 2).

Live-audit 2026-10-13 finding 2: with the entity card open as a native sheet,
the strip below «Сохранить»/«Отмена» stayed white — the log showed the cocoa
render control dropping frames around the refit resize
(``QQuickRenderControl::beginFrame/endFrame`` failed), and where the scene did
not paint, the OS window canvas shone through the transparent framebuffer.
The sheet contract reads «the sheet's canvas is the SHEET surface from the
very first pixel of the window» — so the opted-in sheet islands (the two
dialogs whose window re-fits with the module strip) clear their widget to
``color.bg.surface``: a dropped frame now exposes the skin, never the OS.

Pinned here:
* the card and the event dialog carry the clear color of the current theme;
* a transparent scene grabs as the surface color, pixel-proving the widget
  paints it where the scene does not (dark surface, so ≠ white);
* the theme switch re-publishes the token (the framebuffer never freezes a
  stale color) and the release retires the subscription (NRI-0016 AB5/AB6:
  a released island is never painted-at again);
* non-sheet islands opt out by class default.
"""
from __future__ import annotations

import pytest
from PySide6.QtGui import QColor

from app.infrastructure.ui_prefs.config import UiPrefsManager
from app.presentation.qml.island import IslandDialogMixin
from app.presentation.theme.compiler import token_rgb, tokens_file_path
from app.presentation.theme.runtime import ThemeRuntime
from app.presentation.views.entity_card_dialog import EntityCardDialog
from app.presentation.views.event_dialog import EventDialog
from app.presentation.views.game_launcher_dialog import GameLauncherContent


def _surface_qcolor(runtime: ThemeRuntime) -> QColor:
    r, g, b = token_rgb(runtime.tokens, runtime.theme, "color.bg.surface")
    return QColor(r, g, b)


@pytest.fixture
def runtime(tmp_path) -> ThemeRuntime:
    tokens = tmp_path / "tokens.json"
    tokens.write_text(tokens_file_path().read_text(encoding="utf-8"), encoding="utf-8")
    return ThemeRuntime(prefs=UiPrefsManager(tmp_path / "ui.json"), tokens_path=tokens)


@pytest.fixture
def card(qtbot, runtime):
    dialog = EntityCardDialog(None, "character", theme=runtime)
    qtbot.addWidget(dialog)
    return dialog


def test_the_dark_surface_is_not_white(runtime):
    """The whole safety net is vacuous if the tested canvas equals the OS white."""
    assert _surface_qcolor(runtime) != QColor(255, 255, 255)


def test_card_widget_clears_to_the_sheet_surface(card, runtime):
    assert card._sheet_canvas_color == _surface_qcolor(runtime)


def test_event_dialog_widget_clears_to_the_sheet_surface(qtbot, runtime):
    dialog = EventDialog(None, theme=runtime)
    qtbot.addWidget(dialog)
    assert dialog._sheet_canvas_color == _surface_qcolor(runtime)


def test_theme_switch_republishes_the_clear_color(card, runtime):
    assert runtime.set_theme("light" if runtime.theme == "dark" else "dark")
    assert card._sheet_canvas_color == _surface_qcolor(runtime)


def test_transparent_scene_grabs_as_surface_not_white(card, runtime, qtbot):
    """The pixel half: where the scene paints nothing, the surface shows.

    Hiding the root stands in for a dropped render frame — the framebuffer
    clear is all that is left to paint, and it must be the skin.
    """
    card.show()
    card._root.setVisible(False)
    qtbot.wait(20)

    image = card.quick.grab().toImage()
    probe = image.pixelColor(image.width() // 2, int(image.height() * 0.9))
    surface = _surface_qcolor(runtime)
    assert (probe.red(), probe.green(), probe.blue()) == (
        surface.red(), surface.green(), surface.blue(),
    ), f"expected the sheet surface, grabbed {probe.name()}"


def test_release_retires_the_canvas_subscription(card, runtime):
    froze = card._sheet_canvas_color
    card._release_island()
    assert runtime.set_theme("light" if runtime.theme == "dark" else "dark")
    # A released island is never painted-at (NRI-0016 AB5/AB6): the
    # framebuffer keeps the color it froze with at release.
    assert card._sheet_canvas_color == froze


def test_refit_asks_the_widget_for_a_fresh_render(qtbot, runtime, monkeypatch):
    """The resize-hiccup half of finding 2: a re-fit schedules one render
    request for the next loop turn, when the sheet geometry has settled.

    The real ``QQuickRenderControl`` hiccup is cocoa-only and unforceable
    offscreen — what is pinnable is the app's answer: the refit door ends
    with a render request aimed at the island widget itself, through the
    context-object timer form (a request whose dialog died first is dropped).
    """
    from PySide6.QtWidgets import QApplication

    from app.presentation.views import entity_card_dialog as card_mod
    from app.presentation.views import event_dialog as event_mod

    for mod, make in (
        (card_mod, lambda: EntityCardDialog(None, "character", theme=runtime)),
        (event_mod, lambda: EventDialog(None, theme=runtime)),
    ):
        dialog = make()
        qtbot.addWidget(dialog)
        fired: list = []
        monkeypatch.setattr(
            mod.QTimer, "singleShot",
            lambda ms, ctx, fn, *a: fired.append((ms, ctx, fn)),
        )
        dialog.vm.set_external_groups([{"key": "dnd.sheet", "title": "Лист"}])
        QApplication.processEvents()
        kicks = [
            (ms, ctx) for ms, ctx, fn in fired
            if getattr(fn, "__self__", None) is dialog.quick
        ]
        assert kicks == [(0, dialog)], f"{mod.__name__}: refit scheduled {fired}"


def test_non_sheet_islands_do_not_opt_in():
    assert IslandDialogMixin.ISLAND_SHEET_CANVAS is False
    assert GameLauncherContent.ISLAND_SHEET_CANVAS is False
    # The preview pane of the main window is not a sheet either.
    from app.presentation.views.entity_preview import EntityPreviewWidget

    assert EntityPreviewWidget.ISLAND_SHEET_CANVAS is False
