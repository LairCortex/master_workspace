"""Tests for QSS application scope on chrome widgets (W1 D4).

Generated QSS must live on the chrome containers only — never on
QApplication or the whole QMainWindow, so parented dialogs keep the OS
palette until W2.
"""
from __future__ import annotations

import gc
import weakref
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from app.infrastructure.ui_prefs.config import UiPrefs, UiPrefsManager
from app.presentation.theme import get_default_theme, reset_default_theme
from app.presentation.theme.compiler import load_tokens, tokens_file_path
from app.presentation.theme.runtime import ThemeRuntime
from app.presentation.views.game_launcher_dialog import GameLauncherDialog
from app.presentation.views.main_window import MainWindow


@pytest.fixture
def canvas_dark():
    tokens = load_tokens(tokens_file_path())
    assert tokens is not None
    return tokens["color.bg.canvas"]["dark"]


@pytest.fixture
def runtime(tmp_path):
    return ThemeRuntime(
        prefs=UiPrefsManager(tmp_path / "ui.json"),
        tokens_path=tokens_file_path(),
    )


def make_main_window(theme):
    return MainWindow(
        timeline_vm=MagicMock(),
        detail_vm=MagicMock(),
        search_vm=MagicMock(),
        theme=theme,
    )


# ── launcher surface (Q1: QML island, skinned by the palette — not QSS) ──────

def test_launcher_has_no_theme_chrome_and_no_qss(qtbot, runtime):
    # Spec ui-theme «Область применения QSS»: the launcher content is a QML
    # island painted by the palette; it attaches NO chrome and carries NO QSS.
    from PySide6.QtQuickWidgets import QQuickWidget

    dlg = GameLauncherDialog(theme=runtime)
    qtbot.addWidget(dlg)
    assert dlg.findChild(QWidget, "themeChrome") is None
    assert dlg.styleSheet() == ""
    assert isinstance(dlg.quick, QQuickWidget)
    # The compiled chrome QSS must not have leaked anywhere into the dialog.
    canvas = runtime.tokens["color.bg.canvas"]["dark"]
    assert canvas not in dlg.styleSheet()
    for child in dlg.findChildren(QWidget):
        assert canvas not in child.styleSheet()


# ── main window chrome ─────────────────────────────────────────────────────

def test_app_styles_not_globally_skinned(qapp, qtbot, runtime):
    QApplication.instance().setStyleSheet("")
    window = make_main_window(runtime)
    qtbot.addWidget(window)
    assert qapp.styleSheet() == ""
    assert window.styleSheet() == ""


def test_main_window_central_and_menu_carry_qss(qtbot, runtime, canvas_dark):
    window = make_main_window(runtime)
    qtbot.addWidget(window)
    central = window.centralWidget()
    menu_bar = window.menuBar()
    # objectNames stayed as identifiers (W2a); styling comes from the roles.
    assert central.objectName() == "themeChrome"
    assert menu_bar.objectName() == "themeMenu"
    assert central.property("uiRole") == "chrome"
    assert menu_bar.property("uiRole") == "menu"
    assert canvas_dark in central.styleSheet()
    assert canvas_dark in menu_bar.styleSheet()


def test_dialog_parented_to_main_window_inherits_nothing(qtbot, runtime):
    window = make_main_window(runtime)
    qtbot.addWidget(window)
    dlg = QDialog(parent=window)
    qtbot.addWidget(dlg)
    assert dlg.styleSheet() == ""
    assert 'uiRole="chrome"' not in dlg.styleSheet()


# ── runtime contract ───────────────────────────────────────────────────────

def test_runtime_defaults_to_dark_theme(runtime):
    assert runtime.theme == "dark"
    assert runtime.is_valid is True


def test_runtime_apply_is_noop_with_broken_tokens(qtbot, tmp_path):
    bad = tmp_path / "tokens.json"
    bad.write_text("{not json", encoding="utf-8")
    broken = ThemeRuntime(
        prefs=UiPrefsManager(tmp_path / "ui.json"), tokens_path=bad,
    )
    widget = QWidget()
    widget.setObjectName("themeChrome")
    broken.register(widget)
    broken.apply()
    assert broken.is_valid is False
    assert widget.styleSheet() == ""


# ── theme toggle (design D5/D7) ────────────────────────────────────────────

@pytest.fixture
def canvas_light():
    tokens = load_tokens(tokens_file_path())
    assert tokens is not None
    return tokens["color.bg.canvas"]["light"]


@pytest.fixture
def broken_runtime(tmp_path):
    bad = tmp_path / "tokens.json"
    bad.write_text("{not json", encoding="utf-8")
    return ThemeRuntime(
        prefs=UiPrefsManager(tmp_path / "ui.json"), tokens_path=bad,
    )


def test_launcher_toggle_writes_pref_and_switches_palette(qtbot, runtime):
    from PySide6.QtGui import QColor
    from tests.presentation.qml_helpers import (
        island_toggle_checked,
        island_toggle_text,
    )

    dlg = GameLauncherDialog(theme=runtime)
    qtbot.addWidget(dlg)
    dlg.show()
    dark_surface = QColor(runtime.tokens["color.bg.surface"]["dark"])
    # Island painted from the dark palette before any toggle.
    qtbot.waitUntil(lambda: dlg.quick.grab().toImage().pixelColor(3, 3) == dark_surface)

    dlg._root.themeToggleRequested.emit()  # the island's own toggle drives this

    assert runtime.theme == "light"
    assert runtime.prefs.config_file.exists()
    # The island re-syncs from the palette signal — no re-creation, no QSS.
    # D2 (NRI-0016): the re-sync moves the tick, the caption stays put.
    assert dlg._root.property("currentTheme") == "light"
    assert island_toggle_text(dlg.quick) == "Светлая тема"
    assert island_toggle_checked(dlg.quick) is True
    light_surface = QColor(runtime.tokens["color.bg.surface"]["light"])
    assert light_surface != dark_surface
    qtbot.waitUntil(
        lambda: dlg.quick.grab().toImage().pixelColor(3, 3) == light_surface
    )


def test_main_window_toggle_action_writes_pref_and_switches_qss(
    qtbot, runtime, canvas_light,
):
    window = make_main_window(runtime)
    qtbot.addWidget(window)
    window.theme_toggle_action.trigger()
    assert runtime.theme == "light"
    assert runtime.prefs.config_file.exists()
    assert canvas_light in window.centralWidget().styleSheet()
    assert canvas_light in window.menuBar().styleSheet()


def test_main_window_toggle_action_reflects_current_theme(qtbot, tmp_path):
    prefs = UiPrefsManager(tmp_path / "ui.json")
    prefs.save(UiPrefs(theme="light"))
    runtime = ThemeRuntime(prefs=prefs, tokens_path=tokens_file_path())
    window = make_main_window(runtime)
    qtbot.addWidget(window)
    assert window.theme_toggle_action.isChecked() is True
    assert window.theme_toggle_action.text() == "Светлая тема"


def test_launcher_toggle_is_noop_with_broken_tokens(qtbot, broken_runtime):
    from PySide6.QtQuickWidgets import QQuickWidget
    from tests.presentation.qml_helpers import (
        island_toggle_checked,
        island_toggle_text,
    )

    dlg = GameLauncherDialog(theme=broken_runtime)
    qtbot.addWidget(dlg)
    # Off-skin (D7): the island still loads, controls basic, nothing throws.
    assert dlg.quick.status() == QQuickWidget.Status.Ready
    assert dlg.quick.errors() == []
    dlg._root.themeToggleRequested.emit()
    assert broken_runtime.theme == "dark"
    assert not broken_runtime.prefs.config_file.exists()
    # No QSS anywhere (the launcher never attached the chrome).
    assert dlg.styleSheet() == ""
    # Off-skin the checkbox contract is intact too: fixed caption, the tick
    # still tracks (still-dark) theme — nothing flipped, so nothing is ticked.
    assert island_toggle_text(dlg.quick) == "Светлая тема"
    assert island_toggle_checked(dlg.quick) is False


def test_main_window_toggle_is_noop_with_broken_tokens(qtbot, broken_runtime):
    window = make_main_window(broken_runtime)
    qtbot.addWidget(window)
    window.theme_toggle_action.trigger()
    assert broken_runtime.theme == "dark"
    assert not broken_runtime.prefs.config_file.exists()
    assert window.centralWidget().styleSheet() == ""


# ── corrupted preference file must not break startup (spec «битый preference») ──

def test_runtime_starts_dark_when_preference_file_is_not_utf8(qtbot, tmp_path):
    broken = tmp_path / "ui.json"
    broken.write_bytes(b"\xff\xfe\x00{\x01\x80theme")
    runtime = ThemeRuntime(prefs=UiPrefsManager(broken), tokens_path=tokens_file_path())
    assert runtime.theme == "dark"
    assert runtime.is_valid is True
    # Constructing the launcher is what used to crash the whole process; the
    # QML island loads and paints the dark surface from the palette.
    from PySide6.QtGui import QColor
    from PySide6.QtQuickWidgets import QQuickWidget

    dlg = GameLauncherDialog(theme=runtime)
    qtbot.addWidget(dlg)
    dlg.show()
    assert dlg.quick.status() == QQuickWidget.Status.Ready
    dark_surface = QColor(runtime.tokens["color.bg.surface"]["dark"])
    qtbot.waitUntil(lambda: dlg.quick.grab().toImage().pixelColor(3, 3) == dark_surface)


# ── the preference is read once and kept in memory (no disk per repaint) ────

def test_current_theme_is_cached_and_not_reread_from_disk(runtime, canvas_light):
    runtime.prefs.config_file.write_text('{"theme": "light"}', encoding="utf-8")
    assert runtime.theme == "dark"  # the file was changed behind runtime's back
    assert runtime.set_theme("light") is True
    runtime.prefs.config_file.unlink()  # nothing left to read
    assert runtime.theme == "light"
    assert canvas_light in runtime.qss()


# ── web CSS with broken inputs (D7 on the web side) ────────────────────────

def test_css_is_empty_when_tokens_are_invalid(broken_runtime):
    assert broken_runtime.qss() == ""
    assert broken_runtime.css() == ""


def test_css_is_empty_when_stylesheet_source_is_missing(tmp_path):
    runtime = ThemeRuntime(
        prefs=UiPrefsManager(tmp_path / "ui.json"),
        tokens_path=tokens_file_path(),
        app_css_path=tmp_path / "absent.css",
    )
    assert runtime.css() == ""


def test_css_is_empty_when_stylesheet_source_is_not_utf8(tmp_path):
    body = tmp_path / "app.css"
    body.write_bytes(b"\xff\xfe:root{--x:#000}")
    runtime = ThemeRuntime(
        prefs=UiPrefsManager(tmp_path / "ui.json"),
        tokens_path=tokens_file_path(),
        app_css_path=body,
    )
    assert runtime.css() == ""


# ── chrome registry lifecycle ──────────────────────────────────────────────

class ChromeSpy:
    """Duck-typed chrome widget: records the QSS it was given."""

    def __init__(self):
        self.style = ""

    def styleSheet(self) -> str:  # noqa: N802 — Qt duck typing (read side)
        return self.style

    def setStyleSheet(self, qss):  # noqa: N802 — Qt duck typing
        self.style = qss


def test_register_is_idempotent_and_unregister_stops_pushing(runtime, canvas_light):
    spy = ChromeSpy()
    runtime.register(spy)
    runtime.register(spy)
    assert runtime.registered == (spy,)
    runtime.apply()
    assert spy.style != ""
    runtime.unregister(spy)
    assert runtime.registered == ()
    runtime.set_theme("light")
    assert canvas_light not in spy.style


def test_widgets_that_only_the_registry_holds_do_not_stay_alive(runtime):
    spy = ChromeSpy()
    runtime.register(spy)
    keep_alive = weakref.ref(spy)
    del spy
    gc.collect()
    assert keep_alive() is None
    assert runtime.registered == ()  # pruned, no leak, nothing recolored


def test_apply_drops_widgets_whose_c_object_is_deleted(qtbot, runtime):
    widget = QWidget()
    widget.setObjectName("themeChrome")
    qtbot.addWidget(widget)
    runtime.register(widget)
    widget.deleteLater()
    QCoreApplication.processEvents()
    # DeferredDelete is only delivered by a running event loop — flush it.
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    runtime.apply()  # setStyleSheet raises RuntimeError on the dead wrapper
    assert runtime.registered == ()


# ── both toggles follow the single source of truth ─────────────────────────

class ListenerSpy:
    """Plain (non-Qt) subscriber: counts notifications, dies with its test."""

    def __init__(self):
        self.calls = 0

    def on_theme(self):
        self.calls += 1


def test_listeners_of_dead_objects_are_dropped_silently(runtime):
    listener = ListenerSpy()
    runtime.add_listener(listener.on_theme)
    assert len(runtime.subscribers) == 1
    assert runtime.set_theme("light") is True
    assert listener.calls == 1
    del listener
    gc.collect()
    assert runtime.subscribers == ()
    assert runtime.set_theme("dark") is True  # nobody left, nothing raises


def test_launcher_toggle_updates_main_window_check_item(qtbot, runtime):
    window = make_main_window(runtime)
    qtbot.addWidget(window)
    dlg = GameLauncherDialog(theme=runtime)
    qtbot.addWidget(dlg)
    assert window.theme_toggle_action.isChecked() is False
    dlg._root.themeToggleRequested.emit()
    assert window.theme_toggle_action.isChecked() is True


def test_main_window_toggle_updates_launcher_island_state(qtbot, runtime):
    # ui-theme «Смена из главного окна при открытом лаунчере» + «Одно
    # состояние — одна формулировка» (D2, NRI-0016): both switch points read
    # identically — fixed «Светлая тема» caption, the tick is the state.
    from tests.presentation.qml_helpers import (
        island_toggle_checked,
        island_toggle_text,
    )

    window = make_main_window(runtime)
    qtbot.addWidget(window)
    dlg = GameLauncherDialog(theme=runtime)
    qtbot.addWidget(dlg)
    assert island_toggle_text(dlg.quick) == "Светлая тема"
    assert island_toggle_checked(dlg.quick) is False
    assert window.theme_toggle_action.text() == "Светлая тема"

    window.theme_toggle_action.trigger()  # switch to light from the menu

    # Light is active: in BOTH places the caption is the same and the switch
    # is marked as on; the launcher repaints via the palette signal.
    assert dlg._root.property("currentTheme") == "light"
    assert island_toggle_text(dlg.quick) == "Светлая тема"
    assert island_toggle_checked(dlg.quick) is True
    assert window.theme_toggle_action.text() == "Светлая тема"
    assert window.theme_toggle_action.isChecked() is True


def test_main_window_toggle_repaints_open_launcher(qtbot, runtime):
    # The same ui-theme scenario, pinned by a pixel rather than a label: the
    # open island takes the new surface token with no re-creation.
    from PySide6.QtGui import QColor

    window = make_main_window(runtime)
    qtbot.addWidget(window)
    dlg = GameLauncherDialog(theme=runtime)
    qtbot.addWidget(dlg)
    dlg.show()
    dark = QColor(runtime.tokens["color.bg.surface"]["dark"])
    qtbot.waitUntil(lambda: dlg.quick.grab().toImage().pixelColor(3, 3) == dark)
    root_before = dlg.quick.rootObject()

    window.theme_toggle_action.trigger()  # switched from the main window

    light = QColor(runtime.tokens["color.bg.surface"]["light"])
    qtbot.waitUntil(
        lambda: dlg.quick.grab().toImage().pixelColor(3, 3) == light
    )
    assert dlg.quick.rootObject() is root_before  # same island, no re-creation


def test_broken_tokens_leave_both_switches_untouched(qtbot, broken_runtime):
    from tests.presentation.qml_helpers import (
        island_toggle_checked,
        island_toggle_text,
    )

    window = make_main_window(broken_runtime)
    qtbot.addWidget(window)
    dlg = GameLauncherDialog(theme=broken_runtime)
    qtbot.addWidget(dlg)
    dlg._root.themeToggleRequested.emit()
    window.theme_toggle_action.trigger()
    assert window.theme_toggle_action.isChecked() is False
    assert window.theme_toggle_action.text() == "Светлая тема"
    # Off-skin the checkbox keeps the same contract: fixed caption, no tick.
    assert island_toggle_text(dlg.quick) == "Светлая тема"
    assert island_toggle_checked(dlg.quick) is False



# ── app-wide popup sheet (W2a D2) ──────────────────────────────────────────

@pytest.fixture
def clean_qapp(qapp):
    """The session QApplication is shared — do not leak sheets into other tests."""
    qapp.setStyleSheet("")
    yield qapp
    qapp.setStyleSheet("")


def test_attach_app_pushes_popup_sheet_on_apply(qtbot, runtime, clean_qapp):
    runtime.attach_app(clean_qapp)
    runtime.apply()
    sheet = clean_qapp.styleSheet()
    assert "QToolTip" in sheet
    assert 'QWidget[uiRole="chrome"]' not in sheet  # only popups are app-wide (D2)


def test_app_sheet_rebuilt_on_set_theme(qtbot, runtime, clean_qapp):
    tokens = load_tokens(tokens_file_path())
    runtime.attach_app(clean_qapp)
    runtime.apply()
    dark_sheet = clean_qapp.styleSheet()
    assert tokens["color.bg.surface"]["dark"] in dark_sheet
    assert runtime.set_theme("light") is True
    light_sheet = clean_qapp.styleSheet()
    assert tokens["color.bg.surface"]["light"] in light_sheet
    assert light_sheet != dark_sheet


def test_broken_tokens_clear_the_app_sheet(qtbot, broken_runtime, clean_qapp):
    clean_qapp.setStyleSheet("QToolTip { color: #123456; }")  # stale foreign sheet
    broken_runtime.attach_app(clean_qapp)
    broken_runtime.apply()
    assert clean_qapp.styleSheet() == ""  # off-skin, not a partial style


def test_apply_without_attached_app_leaves_the_app_alone(qtbot, runtime, clean_qapp):
    clean_qapp.setStyleSheet("")
    runtime.apply()  # attach_app was never called
    assert clean_qapp.styleSheet() == ""
    assert runtime.set_theme("light") is True  # no app ref, everything still works


# ── process-wide default runtime ───────────────────────────────────────────

def test_default_theme_runtime_is_a_singleton_until_reset():
    first = get_default_theme()
    assert get_default_theme() is first
    reset_default_theme()
    assert get_default_theme() is not first
    reset_default_theme()


class _DyingApp:
    """Weakref-able fake application whose shell is already gone."""

    def styleSheet(self) -> str:  # noqa: N802 — Qt duck typing
        raise RuntimeError("wrapped C++ object already deleted")

    def setStyleSheet(self, qss):  # noqa: N802 — Qt duck typing
        raise RuntimeError("wrapped C++ object already deleted")


def test_app_sheet_push_drops_a_dead_application_reference(runtime):
    doomed = _DyingApp()
    runtime.attach_app(doomed)
    runtime.apply()               # RuntimeError → the reference is dropped
    runtime.apply()               # second apply: no app ref, nothing raises


# ── idempotent pushes (W2a review: full-suite slowdown) ────────────────────


class _RecordingApp:
    """Weakref-able fake application recording every sheet push it receives."""

    def __init__(self) -> None:
        self.sheet = ""
        self.pushes: list[str] = []

    def styleSheet(self) -> str:  # noqa: N802 — Qt duck typing
        return self.sheet

    def setStyleSheet(self, qss) -> None:  # noqa: N802 — Qt duck typing
        self.sheet = qss
        self.pushes.append(qss)


class _CountingWidget(QWidget):
    """Chrome widget counting how often a stylesheet was pushed to it."""

    def __init__(self) -> None:
        super().__init__()
        self.pushes = 0

    def setStyleSheet(self, qss) -> None:  # noqa: N802 — Qt API override
        self.pushes += 1
        super().setStyleSheet(qss)


def test_unchanged_popup_sheet_is_pushed_only_once(runtime):
    # QApplication.setStyleSheet re-polishes every live widget in the process,
    # so the apply() that ends every screen construction must not re-push an
    # identical sheet (the review measured a x6 slowdown of the offscreen run).
    app = _RecordingApp()
    runtime.attach_app(app)
    runtime.apply()
    runtime.register(_CountingWidget())
    runtime.apply()
    runtime.apply()
    assert app.pushes == [runtime.popup_qss()]


def test_popup_sheet_is_repushed_when_replaced_from_the_outside(runtime):
    app = _RecordingApp()
    runtime.attach_app(app)
    runtime.apply()
    app.sheet = ""  # an outside party replaced the application sheet
    runtime.apply()
    assert len(app.pushes) == 2
    assert app.pushes[-1] == runtime.popup_qss()


def test_theme_change_pushes_the_popup_sheet_again(runtime):
    app = _RecordingApp()
    runtime.attach_app(app)
    runtime.apply()
    assert runtime.set_theme("light") is True
    assert len(app.pushes) == 2
    assert app.pushes[0] != app.pushes[1]


def test_registered_chrome_widget_is_not_restyled_without_a_change(qtbot, runtime):
    widget = _CountingWidget()
    qtbot.addWidget(widget)
    runtime.register(widget)
    runtime.apply()
    runtime.apply()
    assert widget.pushes == 1
    assert widget.styleSheet() == runtime.qss()


# ── W2b review-fix: listener isolation and de-duplication ───────────────────

def test_listener_exception_does_not_abort_the_switch(runtime):
    """A broken screen must not freeze re-render for the others, and the
    exception must not escape into the toggle action (W2b review)."""
    seen = []

    class Boom:
        def cb(self):
            raise RuntimeError("dead widget")

    boom = Boom()
    runtime.add_listener(boom.cb)
    second = lambda: seen.append("second")  # noqa: E731 — runtime holds it weakly
    runtime.add_listener(second)
    # Default theme is dark; flip to light — the switch itself must succeed.
    assert runtime.set_theme("light") is True
    assert seen == ["second"]


def test_duplicate_listener_registration_is_deduplicated(runtime):
    """Adding the same callback twice means one call per switch (mirrors the
    register() contract for widgets)."""
    hits = []

    class Sub:
        def cb(self):
            hits.append(1)

    sub = Sub()
    runtime.add_listener(sub.cb)
    runtime.add_listener(sub.cb)
    assert len(runtime.subscribers) == 1
    assert runtime.set_theme("light") is True
    assert len(hits) == 1


# ── D1 (NRI-0016): explicit unsubscription, listeners do not outlive windows ─

def test_remove_listener_unsubscribes_a_live_listener_and_is_idempotent(runtime):
    """add_listener hands back a handle; remove_listener drops it, and
    unsubscribing twice (or with the never-subscribed ``None``) is silent."""
    spy = ListenerSpy()
    handle = runtime.add_listener(spy.on_theme)
    assert handle is not None
    assert len(runtime.subscribers) == 1
    runtime.remove_listener(handle)
    assert runtime.subscribers == ()
    runtime.remove_listener(handle)  # idempotent: the handle is already gone
    runtime.remove_listener(None)    # a window that never subscribed
    assert runtime.set_theme("light") is True
    assert spy.calls == 0


def test_closed_launcher_is_silent_on_theme_change(qtbot, runtime, caplog):
    """Spec «Закрытый лаунчер молчит при смене темы» (D1).

    The closed dialog stays alive under its parent while its island is
    already released — the old weak-only subscription kept firing
    ``_sync_theme`` into half-dead content and the runtime swallowed the
    RuntimeError into the log. Unsubscribing on ``finished`` means the
    switch reaches the open windows with an empty journal.
    """
    import logging

    import shiboken6

    window = make_main_window(runtime)
    qtbot.addWidget(window)
    window.show()
    dlg = GameLauncherDialog(parent=window, theme=runtime)
    qtbot.addWidget(dlg)
    dlg.show()

    dlg.close()
    # Let the deferred island release (QTimer.singleShot) land: after this
    # turn the QML root is deleted while the dialog wrapper stays alive —
    # exactly the crash window of the old bug (setProperty on the dead root
    # raised RuntimeError, which the runtime swallowed into the log).
    qtbot.wait(50)
    assert not shiboken6.isValid(dlg._root)

    caplog.clear()
    caplog.set_level(logging.DEBUG)
    assert runtime.set_theme("light") is True
    assert caplog.records == []
    # The theme really arrived where a window is still open.
    assert window.theme_toggle_action.isChecked() is True


def test_main_window_close_unsubscribes_its_theme_listener(qtbot, runtime):
    """D1 inventory: a game switch closes and replaces the main window while
    the runtime outlives it — closeEvent drops the handle explicitly, so the
    dead window is not a listener until the collector gets to it."""
    window = make_main_window(runtime)
    qtbot.addWidget(window)
    assert any(
        getattr(cb, "__self__", None) is window for cb in runtime.subscribers
    )
    window.close()
    assert not any(
        getattr(cb, "__self__", None) is window for cb in runtime.subscribers
    )
    # The switch still works with the dropped subscription in place.
    assert runtime.set_theme("light") is True


# ── DEFECT-1 (NRI-0016): island teardowns, including the closed islands ──────


def test_closed_llm_island_window_leaves_no_theme_listener(qtbot, runtime, caplog):
    """The audited reproduction of DEFECT-1, pinned offscreen.

    «Настройка LLM…» closes (QDialog close ⇒ the island release is deferred a
    turn), and the window's C++ side goes away afterwards — leaving the
    palette wrapper alive with a dead signal source behind it. Every later
    theme change used to answer with a RuntimeError pair from that dead
    listener (two closed windows ⇒ two pairs; spec app-logging «Слушатели
    состояния не переживают окно»)."""
    import logging

    from app.infrastructure.llm.config import LlmConfig
    from app.presentation.theme.qml_palette import QmlPalette
    from app.presentation.views.llm_setup_dialog import LlmSetupDialog

    def island_palettes() -> list:
        return [
            cb for cb in runtime.subscribers
            if isinstance(getattr(cb, "__self__", None), QmlPalette)
        ]

    dlg = LlmSetupDialog(
        config=LlmConfig("https://api.openai.com/v1", "gpt-4o-mini", ""),
        theme=runtime,
    )
    qtbot.addWidget(dlg)
    assert len(island_palettes()) == 2  # engine bridge + this island's own

    dlg.show()
    dlg.close()  # the «Закрыть»/native-close exit
    qtbot.wait(50)  # the deferred island release lands
    assert len(island_palettes()) == 1  # only the engine bridge stays

    # The window object's C++ side leaving is what used to open the crash
    # window between the dead signal source and the still-resolvable method.
    QCoreApplication.sendPostedEvents(dlg, QEvent.Type.DeferredDelete)
    dlg.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qtbot.wait(20)
    assert len(island_palettes()) == 1

    caplog.clear()
    caplog.set_level(logging.DEBUG)
    assert runtime.set_theme("light") is True
    assert caplog.records == []


def test_main_window_close_drops_child_island_subscriptions(qtbot, runtime, caplog):
    """The island panels are child widgets: no closeEvent ever reaches them,
    so MainWindow.closeEvent releases them too (palette + per-panel view
    model subscriptions). Re-opening the main window with the same runtime
    must find only the engine bridge palette subscribed (DEFECT-1).
    """
    import logging

    from app.presentation.theme.qml_palette import QmlPalette

    def palette_listeners() -> list:
        return [
            cb for cb in runtime.subscribers
            if isinstance(getattr(cb, "__self__", None), QmlPalette)
        ]

    window = make_main_window(runtime)
    qtbot.addWidget(window)
    window.show()
    # engine bridge + timeline/search/detail/world island palettes.
    assert len(palette_listeners()) == 5

    def bound_classes() -> set[str]:
        return {
            cb.__self__.__class__.__name__
            for cb in runtime.subscribers
            if hasattr(cb, "__self__")
        }

    # the two island view models sit on the runtime too
    assert {"DetailPanelViewModel", "WorldSnapshotViewModel"} <= bound_classes()

    window.close()  # closeEvent: own handle + every child island released
    assert len(palette_listeners()) == 1
    assert not {"DetailPanelViewModel", "WorldSnapshotViewModel"} & bound_classes()

    caplog.clear()
    caplog.set_level(logging.DEBUG)
    assert runtime.set_theme("light") is True
    assert caplog.records == []


def test_dead_listener_failure_is_reported_without_formatting_the_callback(
    runtime, caplog
):
    """The containment log must not lean on ``%r`` of the subscriber.

    With the old ``%r`` a Qt wrapper whose C++ side is already gone raised
    from inside the log record's own formatting, so each theme change
    printed the real exception AND a second «--- Logging error ---» cascade
    (DEFECT-1). The subscriber is identified by its qualified name instead,
    and the failing switch must stay a single well-formed record."""
    import logging

    class Deadish:
        def cb(self):
            raise RuntimeError("Signal source has been deleted")

        def __repr__(self):  # what a deleted Qt wrapper does to %r
            raise RuntimeError("wrapper is dead; repr blows too")

    dead = Deadish()
    second_hits: list[str] = []

    def second():
        second_hits.append("second")

    runtime.add_listener(dead.cb)
    runtime.add_listener(second)

    caplog.set_level(logging.ERROR)
    assert runtime.set_theme("light") is True  # the switch succeeds anyway
    assert second_hits == ["second"]

    records = [r for r in caplog.records if "не дошло до подписчика" in r.getMessage()]
    assert len(records) == 1  # one record, formatted — no logging-error cascade
    assert "Deadish.cb" in records[0].getMessage()
