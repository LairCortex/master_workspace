"""Real-QML acceptance for the R4 date and rating primitives."""
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
from app.presentation.theme.rating import rating_to_color
from app.presentation.theme.runtime import ThemeRuntime


PROBE = """
import QtQuick
import nri.components

Item {
    id: probe
    implicitWidth: 260
    implicitHeight: 170
    property color ratingTint: "transparent"
    property int dateClicks: 0
    property bool dateSkinned: dateField.skinned
    property bool ratingSkinned: ratingCard.skinned

    Rectangle {
        anchors.fill: parent
        color: (typeof islandPalette !== "undefined" && islandPalette !== null
                && islandPalette.tokens)
            ? islandPalette.tokens["color.danger"] : "lightgray"
    }
    ThemeDateField {
        id: dateField
        objectName: "dateField"
        x: 20; y: 20; width: 220; height: 40
        isoDate: "1200-03-04"
        display: "04 Март 1200"
        onClicked: probe.dateClicks += 1
    }
    ThemeRatingCard {
        id: ratingCard
        objectName: "ratingCard"
        x: 20; y: 80; width: 220; height: 60
        tintColor: probe.ratingTint
    }
}
"""


@pytest.fixture
def runtime(tmp_path):
    tokens = tmp_path / "tokens.json"
    tokens.write_text(tokens_file_path().read_text(encoding="utf-8"), encoding="utf-8")
    return ThemeRuntime(prefs=UiPrefsManager(tmp_path / "ui.json"), tokens_path=tokens)


def _walk(root: QQuickItem):
    stack = [root]
    while stack:
        for child in stack.pop().childItems():
            yield child
            stack.append(child)


def _find(widget: QQuickWidget, name: str) -> QQuickItem:
    found = [item for item in _walk(widget.rootObject()) if item.objectName() == name]
    assert len(found) == 1
    return found[0]


def _load(qtbot, qapp, runtime, palette, path: Path) -> QQuickWidget:
    if QQuickStyle.name() != "Basic":
        QQuickStyle.setStyle("Basic")
    path.write_text(PROBE, encoding="utf-8")
    widget = QQuickWidget(setup_qml_shell(qapp, runtime), None)
    qtbot.addWidget(widget)
    widget.resize(260, 170)
    if palette is not None:
        palette.setParent(widget)
        widget.rootContext().setContextProperty("islandPalette", palette)
    widget.setSource(QUrl.fromLocalFile(str(path)))
    assert widget.status() == QQuickWidget.Status.Ready, widget.errors()
    return widget


def _pixel(widget, item, x, y) -> QColor:
    image = widget.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    point = item.mapToScene(QPointF(x, y))
    return image.pixelColor(int(point.x()), int(point.y()))


@pytest.mark.parametrize("theme", ("dark", "light"))
def test_date_field_and_rating_card_match_theme_pixels(
    qtbot, qapp, runtime, tmp_path, theme
):
    assert runtime.set_theme(theme)
    palette = QmlPalette(runtime)
    widget = _load(qtbot, qapp, runtime, palette, tmp_path / "probe.qml")
    root = widget.rootObject()
    tint = rating_to_color(12, runtime)
    root.setProperty("ratingTint", tint)
    date_field = _find(widget, "dateField")
    rating_card = _find(widget, "ratingCard")

    assert date_field.property("isoDate") == "1200-03-04"
    assert date_field.property("display") == "04 Март 1200"
    assert root.property("dateSkinned") is True
    assert root.property("ratingSkinned") is True
    date_field.clicked.emit()
    assert root.property("dateClicks") == 1
    assert _pixel(
        widget, date_field, date_field.width() - 10, date_field.height() / 2
    ).rgb() == QColor(
        palette.tokens["color.bg.canvas"]
    ).rgb()
    assert _pixel(widget, date_field, 0, date_field.height() / 2).rgb() == QColor(
        palette.tokens["color.border"]
    ).rgb()

    surface = QColor(palette.tokens["color.bg.surface"])
    alpha = tint.alphaF()
    expected = QColor(
        round(tint.red() * alpha + surface.red() * (1 - alpha)),
        round(tint.green() * alpha + surface.green() * (1 - alpha)),
        round(tint.blue() * alpha + surface.blue() * (1 - alpha)),
    )
    actual = _pixel(widget, rating_card, rating_card.width() / 2, rating_card.height() / 2)
    assert abs(actual.red() - expected.red()) <= 1
    assert abs(actual.green() - expected.green()) <= 1
    assert abs(actual.blue() - expected.blue()) <= 1


def test_components_are_unskinned_without_valid_tokens(qtbot, qapp, tmp_path):
    bad = tmp_path / "tokens.json"
    bad.write_text("{not json", encoding="utf-8")
    runtime = ThemeRuntime(prefs=UiPrefsManager(tmp_path / "ui.json"), tokens_path=bad)
    palette = QmlPalette(runtime)
    widget = _load(qtbot, qapp, runtime, palette, tmp_path / "probe.qml")
    root = widget.rootObject()
    root.setProperty("ratingTint", QColor(255, 0, 255, 220))
    assert root.property("dateSkinned") is False
    assert root.property("ratingSkinned") is False
    card = _find(widget, "ratingCard")
    assert _pixel(widget, card, card.width() / 2, card.height() / 2).rgb() == _pixel(
        widget, root, 5, 5
    ).rgb()


def test_qmldir_registers_date_and_rating_components():
    components = Path(__file__).parents[2] / "app/presentation/qml/nri/components"
    qmldir = (components / "qmldir").read_text(encoding="utf-8")
    assert "ThemeDateField ThemeDateField.qml" in qmldir
    assert "ThemeRatingCard ThemeRatingCard.qml" in qmldir
    date_source = (components / "ThemeDateField.qml").read_text(encoding="utf-8")
    rating_source = (components / "ThemeRatingCard.qml").read_text(encoding="utf-8")
    assert all(term not in date_source for term in ("new Date", "getMonth", "setMonth"))
    assert all(term not in rating_source for term in ("Qt.rgba", "gradient:", "rating /"))
