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


# ── launcher chrome ────────────────────────────────────────────────────────

def test_launcher_has_theme_chrome_container(qtbot, runtime):
    dlg = GameLauncherDialog(theme=runtime)
    qtbot.addWidget(dlg)
    chrome = dlg.findChild(QWidget, "themeChrome")
    assert chrome is not None


def test_launcher_theme_chrome_carries_generated_qss(qtbot, runtime, canvas_dark):
    dlg = GameLauncherDialog(theme=runtime)
    qtbot.addWidget(dlg)
    chrome = dlg.findChild(QWidget, "themeChrome")
    assert canvas_dark in chrome.styleSheet()
    assert "themeChrome" in chrome.styleSheet()


def test_launcher_dialog_itself_has_no_qss(qtbot, runtime):
    dlg = GameLauncherDialog(theme=runtime)
    qtbot.addWidget(dlg)
    assert dlg.styleSheet() == ""


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
    assert central.objectName() == "themeChrome"
    assert menu_bar.objectName() == "themeMenu"
    assert canvas_dark in central.styleSheet()
    assert canvas_dark in menu_bar.styleSheet()


def test_dialog_parented_to_main_window_inherits_nothing(qtbot, runtime):
    window = make_main_window(runtime)
    qtbot.addWidget(window)
    dlg = QDialog(parent=window)
    qtbot.addWidget(dlg)
    assert dlg.styleSheet() == ""
    assert "themeChrome" not in dlg.styleSheet()


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


def test_launcher_toggle_writes_pref_and_switches_qss(qtbot, runtime, canvas_light):
    dlg = GameLauncherDialog(theme=runtime)
    qtbot.addWidget(dlg)
    dlg.theme_toggle_button.click()
    assert runtime.theme == "light"
    assert runtime.prefs.config_file.exists()
    chrome = dlg.findChild(QWidget, "themeChrome")
    assert canvas_light in chrome.styleSheet()


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
    dlg = GameLauncherDialog(theme=broken_runtime)
    qtbot.addWidget(dlg)
    dlg.theme_toggle_button.click()
    assert broken_runtime.theme == "dark"
    assert not broken_runtime.prefs.config_file.exists()
    chrome = dlg.findChild(QWidget, "themeChrome")
    assert chrome.styleSheet() == ""


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
    # Constructing the chrome is what used to crash the whole process.
    dlg = GameLauncherDialog(theme=runtime)
    qtbot.addWidget(dlg)
    assert dlg.chrome.styleSheet() != ""


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
    dlg.theme_toggle_button.click()
    assert window.theme_toggle_action.isChecked() is True


def test_main_window_toggle_updates_launcher_button_text(qtbot, runtime):
    window = make_main_window(runtime)
    qtbot.addWidget(window)
    dlg = GameLauncherDialog(theme=runtime)
    qtbot.addWidget(dlg)
    assert dlg.theme_toggle_button.text() == "Светлая тема"
    window.theme_toggle_action.trigger()
    assert dlg.theme_toggle_button.text() == "Тёмная тема"


def test_broken_tokens_leave_both_switches_untouched(qtbot, broken_runtime):
    window = make_main_window(broken_runtime)
    qtbot.addWidget(window)
    dlg = GameLauncherDialog(theme=broken_runtime)
    qtbot.addWidget(dlg)
    dlg.theme_toggle_button.click()
    window.theme_toggle_action.trigger()
    assert window.theme_toggle_action.isChecked() is False
    assert dlg.theme_toggle_button.text() == "Светлая тема"


# ── process-wide default runtime ───────────────────────────────────────────

def test_default_theme_runtime_is_a_singleton_until_reset():
    first = get_default_theme()
    assert get_default_theme() is first
    reset_default_theme()
    assert get_default_theme() is not first
    reset_default_theme()
