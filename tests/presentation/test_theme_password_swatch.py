"""Pixel and behavior acceptance for password ThemeField and ThemeSwatch."""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, QUrl
from PySide6.QtGui import QColor
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQuickWidgets import QQuickWidget

from app.infrastructure.ui_prefs.config import UiPrefsManager
from app.presentation.qml.engine import setup_qml_shell
from app.presentation.theme.compiler import CHART_TOKEN_KEYS, tokens_file_path
from app.presentation.theme.qml_palette import QmlPalette
from app.presentation.theme.runtime import ThemeRuntime
from tests.presentation.qml_helpers import click_item, find_item


SCENE = """
import QtQuick
import nri.components

Item {
    implicitWidth: 360
    implicitHeight: 280

    ThemeField {
        id: password
        objectName: "passwordField"
        x: 20; y: 20; width: 220; height: 36
        echoPassword: true
        text: "secret-value"
    }

    Repeater {
        model: 8
        ThemeSwatch {
            objectName: "swatch" + (index + 1)
            x: 20 + (index % 4) * 70
            y: 90 + Math.floor(index / 4) * 70
            colorIndex: index + 1
        }
    }
}
"""


def _runtime(tmp_path: Path, theme: str, *, valid: bool = True) -> ThemeRuntime:
    tokens = tmp_path / "tokens.json"
    if valid:
        tokens.write_text(tokens_file_path().read_text(encoding="utf-8"), encoding="utf-8")
    else:
        tokens.write_text("{broken", encoding="utf-8")
    runtime = ThemeRuntime(
        prefs=UiPrefsManager(tmp_path / "ui.json"),
        tokens_path=tokens,
    )
    if valid:
        assert runtime.set_theme(theme)
    return runtime


def _load(qtbot, qapp, runtime, scene: Path):
    if QQuickStyle.name() != "Basic":
        QQuickStyle.setStyle("Basic")
    scene.write_text(SCENE, encoding="utf-8")
    engine = setup_qml_shell(qapp, runtime)
    widget = QQuickWidget(engine, None)
    qtbot.addWidget(widget)
    widget.resize(360, 280)
    palette = QmlPalette(runtime, parent=widget)
    widget.rootContext().setContextProperty("islandPalette", palette)
    widget.setSource(QUrl.fromLocalFile(str(scene)))
    assert widget.status() == QQuickWidget.Status.Ready, widget.errors()
    return widget, palette


def _pixel(widget, item, x: float, y: float) -> QColor:
    image = widget.grab().toImage()
    point = item.mapToScene(QPointF(x, y))
    return image.pixelColor(int(point.x()), int(point.y()))


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_password_field_masks_text_and_uses_field_tokens(qtbot, qapp, tmp_path, theme):
    runtime = _runtime(tmp_path, theme)
    widget, palette = _load(qtbot, qapp, runtime, tmp_path / "probe.qml")
    field = find_item(widget, "passwordField")
    assert field.property("text") == "secret-value"
    assert field.property("displayText") != "secret-value"
    assert field.property("echoPassword") is True
    assert _pixel(widget, field, field.width() - 8, field.height() / 2) == QColor(
        palette.tokens["color.bg.canvas"]
    )
    assert _pixel(widget, field, 0, field.height() / 2) == QColor(
        palette.tokens["color.border"]
    )


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_all_eight_swatches_match_chart_tokens(qtbot, qapp, tmp_path, theme):
    runtime = _runtime(tmp_path, theme)
    widget, palette = _load(qtbot, qapp, runtime, tmp_path / "probe.qml")
    for index, token in enumerate(CHART_TOKEN_KEYS, start=1):
        swatch = find_item(widget, f"swatch{index}")
        assert swatch.property("colorIndex") == index
        assert _pixel(widget, swatch, swatch.width() / 2, swatch.height() / 2) == QColor(
            palette.tokens[token]
        )
    target = find_item(widget, "swatch5")
    assert target.property("checked") is False
    click_item(widget, target)
    assert target.property("checked") is True
    target.setProperty("colorIndex", 99)
    assert target.property("effectiveColorIndex") == 8


def test_password_and_swatches_degrade_offskin(qtbot, qapp, tmp_path):
    runtime = _runtime(tmp_path, "dark", valid=False)
    widget, _ = _load(qtbot, qapp, runtime, tmp_path / "probe.qml")
    field = find_item(widget, "passwordField")
    assert field.property("skinned") is False
    assert field.property("displayText") != field.property("text")
    for index in range(1, 9):
        swatch = find_item(widget, f"swatch{index}")
        assert swatch.property("skinned") is False
        assert swatch.property("chartColor") == QColor("gray")
