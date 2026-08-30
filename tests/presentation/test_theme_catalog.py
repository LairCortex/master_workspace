"""Tests for the widget-role catalog (W2a D1: roles, attach_theme, factories).

Pixel regression per the W2a risk list: a nested widget without a role must
not be recolored by the attached sheet, and a connected screen must live-
retheme through ``set_theme()`` without recreating any widget.
"""
from __future__ import annotations

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QMenuBar, QLineEdit, QLabel, QWidget

from app.infrastructure.ui_prefs.config import UiPrefsManager
from app.presentation.theme.catalog import attach_theme, hint, set_role, title
from app.presentation.theme.compiler import load_tokens, tokens_file_path
from app.presentation.theme.runtime import ThemeRuntime


@pytest.fixture
def tokens():
    parsed = load_tokens(tokens_file_path())
    assert parsed is not None
    return parsed


@pytest.fixture
def runtime(tmp_path):
    return ThemeRuntime(prefs=UiPrefsManager(tmp_path / "ui.json"),
                        tokens_path=tokens_file_path())


# ── attach_theme ───────────────────────────────────────────────────────────

def test_attach_theme_marks_and_registers_qwidget(qtbot, runtime):
    root = QWidget()
    qtbot.addWidget(root)
    returned = attach_theme(root, runtime)
    assert returned is root
    assert root.property("uiRole") == "chrome"
    assert root in runtime.registered


def test_attach_theme_marks_menubar_with_menu_role(qtbot, runtime):
    bar = QMenuBar()
    qtbot.addWidget(bar)
    attach_theme(bar, runtime)
    assert bar.property("uiRole") == "menu"


def test_attach_theme_is_idempotent(qtbot, runtime):
    root = QWidget()
    qtbot.addWidget(root)
    attach_theme(root, runtime)
    attach_theme(root, runtime)
    assert runtime.registered == (root,)  # registered once, same role
    assert root.property("uiRole") == "chrome"


def test_attach_theme_on_retheme_fires_on_theme_switch(qtbot, runtime):
    # W2b D2: content built outside QSS (rich-text HTML) subscribes here.
    seen = []
    root = QWidget()
    qtbot.addWidget(root)
    # The runtime keeps callbacks weakly — the test must own the lambda.
    callback = lambda: seen.append(runtime.theme)  # noqa: E731
    attach_theme(root, runtime, on_retheme=callback)
    assert seen == []  # attaching itself is not a theme change
    assert runtime.set_theme("light")
    assert seen == ["light"]


def test_root_without_attach_gets_no_role(qtbot):
    # The role is only what attach_theme/set_role put there — no magic scope.
    widget = QWidget()
    qtbot.addWidget(widget)
    assert widget.property("uiRole") is None


# ── set_role + factories ───────────────────────────────────────────────────

def test_set_role_stamps_property_and_modifiers(qtbot):
    widget = QLabel("x")
    qtbot.addWidget(widget)
    set_role(widget, "hint", italic=True)
    assert widget.property("uiRole") == "hint"
    assert widget.property("uiRoleItalic") == "true"
    assert widget.property("uiRoleSize") == ""


def test_set_role_clears_previous_modifier(qtbot):
    widget = QLabel("x")
    qtbot.addWidget(widget)
    set_role(widget, "title", size="xl")
    set_role(widget, "title")  # md — must not keep the old xl
    assert widget.property("uiRoleSize") == ""


def test_set_role_rejects_unknown_role(qtbot):
    widget = QWidget()
    qtbot.addWidget(widget)
    with pytest.raises(ValueError):
        set_role(widget, "button")


def test_title_factory_marks_md_by_default(qtbot):
    label = title("Заголовок")
    qtbot.addWidget(label)
    assert isinstance(label, QLabel)
    assert label.text() == "Заголовок"
    assert label.property("uiRole") == "title"
    assert label.property("uiRoleSize") == ""


def test_title_factory_xl_modifier(qtbot):
    label = title("Крупный", size="xl")
    qtbot.addWidget(label)
    assert label.property("uiRoleSize") == "xl"


def test_hint_factory_italic_modifier(qtbot):
    plain = hint("подсказка")
    cursive = hint("курсив", italic=True)
    qtbot.addWidget(plain)
    qtbot.addWidget(cursive)
    assert plain.property("uiRole") == "hint"
    assert plain.property("uiRoleItalic") == ""
    assert cursive.property("uiRoleItalic") == "true"


def test_generated_title_uses_token_sizes(qtbot, runtime, tokens):
    md, xl = title("md"), title("xl", size="xl")
    qtbot.addWidget(title_container := QWidget())  # role rules live on a root
    attach_theme(title_container, runtime)
    md.setParent(title_container)
    xl.setParent(title_container)
    runtime.apply()
    md.ensurePolished()  # the resolved stylesheet font lands on the widget here
    xl.ensurePolished()
    assert md.font().pixelSize() == int(tokens["font.size.lg"]["dark"][:-2])
    assert xl.font().pixelSize() == int(tokens["font.size.xl"]["dark"][:-2])


# ── pixel regressions: role scope + live retheme ───────────────────────────

@pytest.fixture
def themed_root(qtbot, runtime):
    root = QWidget()
    root.resize(220, 140)
    attach_theme(root, runtime)
    runtime.apply()
    qtbot.addWidget(root)
    root.show()
    qtbot.waitExposed(root)
    return root


tokens_fixture = pytest.fixture


def test_nested_widget_without_role_is_not_recolored(qtbot, runtime, tokens, tmp_path):
    # W2a risk: [uiRole=...] matches only the property carrier. A nested
    # QLineEdit must keep the OS palette (its pixel must NOT become surface),
    # while the same widget with the field role must take the token exactly.
    root = QWidget()
    root.resize(240, 120)
    attach_theme(root, runtime)
    runtime.apply()
    qtbot.addWidget(root)
    plain = QLineEdit("plain", root)
    plain.setGeometry(10, 10, 100, 28)
    themed = QLineEdit("field", root)
    themed.setGeometry(10, 50, 100, 28)
    set_role(themed, "field")
    root.show()
    qtbot.waitExposed(root)
    image = root.grab().toImage()
    surface = QColor(tokens["color.bg.surface"]["dark"])
    assert image.pixelColor(60, 64) == surface          # field role: token
    assert image.pixelColor(60, 24) != surface          # no role: OS palette


def test_attached_root_recolors_live_without_recreating_widgets(
    qtbot, runtime, tokens,
):
    root = QWidget()
    root.resize(120, 60)
    attach_theme(root, runtime)
    runtime.apply()
    qtbot.addWidget(root)
    root.show()
    qtbot.waitExposed(root)
    dark = QColor(tokens["color.bg.canvas"]["dark"])
    assert root.grab().toImage().pixelColor(2, 2) == dark
    assert runtime.set_theme("light") is True
    # Same C++ widgets, new theme — no re-attach, no re-show.
    light = QColor(tokens["color.bg.canvas"]["light"])
    assert root.grab().toImage().pixelColor(2, 2) == light


def test_dialog_without_attach_stays_on_os_palette(qtbot, runtime, tokens):
    # "Rules of roles must not apply to arbitrary widgets": a widget that
    # never attached (migrated screen or not) keeps whatever it had.
    from PySide6.QtWidgets import QDialog

    dlg = QDialog()
    qtbot.addWidget(dlg)
    edit = QLineEdit(dlg)
    edit.resize(80, 24)
    dlg.resize(120, 60)
    dlg.show()
    qtbot.waitExposed(dlg)
    surface = QColor(tokens["color.bg.surface"]["dark"])
    assert dlg.findChild(QLineEdit).styleSheet() == ""
    assert edit.property("uiRole") is None
    assert dlg.grab().toImage().pixelColor(60, 40) != surface


def test_title_factory_rejects_unknown_size():
    with pytest.raises(ValueError):
        title("bad", size="sm")
