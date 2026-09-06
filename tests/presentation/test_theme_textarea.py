"""Pixel acceptance for ThemeTextArea (R3 pack 1, tasks 1.1–1.2)."""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, QUrl
from PySide6.QtGui import QColor, QImage
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQuickWidgets import QQuickWidget

from app.infrastructure.ui_prefs.config import UiPrefsManager
from app.presentation.qml.engine import setup_qml_shell
from app.presentation.theme.compiler import tokens_file_path
from app.presentation.theme.qml_palette import QmlPalette
from app.presentation.theme.runtime import ThemeRuntime

PROBE = """
import QtQuick
import nri.components

Item {
    id: probe
    objectName: "textAreaProbe"
    implicitWidth: 240
    implicitHeight: 140

    Rectangle {
        anchors.fill: parent
        color: (typeof islandPalette !== "undefined" && islandPalette !== null
                && islandPalette.tokens)
            ? islandPalette.tokens["color.danger"] : "lightgray"
    }

    ThemeTextArea {
        id: area
        objectName: "probeTextArea"
        x: 20; y: 20; width: 200; height: 80
        readOnly: true
        text: "WWW"
    }

    property bool areaSkinned: area.skinned
}
"""

_THEME_VALUES = ("dark", "light")


@pytest.fixture
def tokens_file(tmp_path):
    dst = tmp_path / "tokens.json"
    dst.write_text(tokens_file_path().read_text(encoding="utf-8"), encoding="utf-8")
    return dst


@pytest.fixture
def runtime(tmp_path, tokens_file):
    return ThemeRuntime(prefs=UiPrefsManager(tmp_path / "ui.json"), tokens_path=tokens_file)


def _walk(root: QQuickItem):
    stack = [root]
    while stack:
        for child in stack.pop().childItems():
            yield child
            stack.append(child)


def _find(widget: QQuickWidget, name: str) -> QQuickItem:
    found = [i for i in _walk(widget.rootObject()) if i.objectName() == name]
    assert len(found) == 1, name
    return found[0]


def _token_rgb(hex_value: str) -> tuple[int, int, int]:
    color = QColor(hex_value)
    assert color.isValid(), hex_value
    return (color.red(), color.green(), color.blue())


def _grab(widget: QQuickWidget) -> QImage:
    img = widget.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    assert not img.isNull()
    return img


def _item_pixel(widget, img, item, local_x: float, local_y: float):
    point = item.mapToScene(QPointF(local_x, local_y))
    sx = img.width() / widget.width()
    sy = img.height() / widget.height()
    x = min(int(point.x() * sx), img.width() - 1)
    y = min(int(point.y() * sy), img.height() - 1)
    c = img.pixelColor(x, y)
    return (c.red(), c.green(), c.blue())


def load_probe(qtbot, qapp, runtime, palette: QmlPalette | None, scene: Path) -> QQuickWidget:
    if QQuickStyle.name() != "Basic":
        QQuickStyle.setStyle("Basic")
    scene.write_text(PROBE, encoding="utf-8")
    engine = setup_qml_shell(qapp, runtime)
    widget = QQuickWidget(engine, None)
    qtbot.addWidget(widget)
    widget.resize(240, 140)
    if palette is not None:
        palette.setParent(widget)
        widget.rootContext().setContextProperty("islandPalette", palette)
    widget.setSource(QUrl.fromLocalFile(str(scene)))
    assert widget.status() == QQuickWidget.Status.Ready, widget.errors()
    return widget


@pytest.fixture(params=_THEME_VALUES)
def themed(request, runtime):
    assert runtime.set_theme(request.param) is True
    return request.param


def test_theme_textarea_pixels_match_field_tokens_in_both_themes(
    qtbot, qapp, runtime, themed, tmp_path
):
    palette = QmlPalette(runtime)
    tokens = palette.tokens
    canvas_rgb = _token_rgb(tokens["color.bg.canvas"])
    border_rgb = _token_rgb(tokens["color.border"])
    widget = load_probe(qtbot, qapp, runtime, palette, tmp_path / "ta.qml")
    assert widget.errors() == []
    area = _find(widget, "probeTextArea")
    assert area.property("readOnly") is True
    img = _grab(widget)
    assert _item_pixel(widget, img, area, area.width() - 10, area.height() / 2) == canvas_rgb
    assert _item_pixel(widget, img, area, 0, area.height() / 2) == border_rgb
    assert widget.rootObject().property("areaSkinned") is True


def test_theme_textarea_offskin_uses_no_invented_hex(qtbot, qapp, tmp_path):
    bad = tmp_path / "tokens.json"
    bad.write_text("{not json", encoding="utf-8")
    runtime = ThemeRuntime(prefs=UiPrefsManager(tmp_path / "ui.json"), tokens_path=bad)
    off = QmlPalette(runtime)
    assert off.tokens == {}
    widget = load_probe(qtbot, qapp, runtime, off, tmp_path / "ta.qml")
    assert widget.errors() == []
    assert widget.rootObject().property("areaSkinned") is False
    area = _find(widget, "probeTextArea")
    img = _grab(widget)
    invented = (255, 0, 255)
    assert _item_pixel(widget, img, area, 10, area.height() / 2) != invented
