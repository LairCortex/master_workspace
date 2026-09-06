"""QQuickWidget acceptance for nri.components MentionField."""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, Qt, QUrl
from PySide6.QtGui import QColor, QImage, QKeySequence
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtTest import QTest

from app.infrastructure.ui_prefs.config import UiPrefsManager
from app.presentation.qml.engine import setup_qml_shell
from app.presentation.theme.compiler import tokens_file_path
from app.presentation.theme.qml_palette import QmlPalette
from app.presentation.theme.runtime import ThemeRuntime
from app.presentation.viewmodels.mention_field_host import MentionFieldHost
from tests.presentation.qml_helpers import click_item, find_item

SCENE = """
import QtQuick
import nri.components

Item {
    objectName: "mentionProbe"
    implicitWidth: 360
    implicitHeight: 150
    Rectangle { anchors.fill: parent; color: "magenta" }
    MentionField {
        x: 10; y: 10
        width: 340; height: 130
        host: mentionFieldHost
    }
}
"""


@pytest.fixture
def runtime(tmp_path):
    token_copy = tmp_path / "tokens.json"
    token_copy.write_text(tokens_file_path().read_text(encoding="utf-8"), encoding="utf-8")
    return ThemeRuntime(
        prefs=UiPrefsManager(tmp_path / "ui.json"),
        tokens_path=token_copy,
    )


def load_field(qtbot, qapp, runtime, tmp_path, *, palette=True, attach=True):
    scene = tmp_path / "mention_probe.qml"
    scene.write_text(SCENE, encoding="utf-8")
    if QQuickStyle.name() != "Basic":
        QQuickStyle.setStyle("Basic")
    engine = setup_qml_shell(qapp, runtime)
    widget = QQuickWidget(engine, None)
    qtbot.addWidget(widget)
    widget.resize(360, 150)
    host = MentionFieldHost()
    host.setParent(widget)
    if attach:
        host.attachWidget(widget)
    widget.rootContext().setContextProperty("mentionFieldHost", host)
    bridge = QmlPalette(runtime, parent=widget) if palette else None
    if bridge is not None:
        widget.rootContext().setContextProperty("islandPalette", bridge)
    widget.setSource(QUrl.fromLocalFile(str(scene)))
    assert widget.status() == QQuickWidget.Status.Ready, widget.errors()
    return widget, host, bridge


def grab_image(widget):
    return widget.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)


def item_rgb(widget, image, item, x, y):
    point = item.mapToScene(QPointF(x, y))
    sx = image.width() / widget.width()
    sy = image.height() / widget.height()
    color = image.pixelColor(int(point.x() * sx), int(point.y() * sy))
    return color.red(), color.green(), color.blue()


def token_rgb(value):
    color = QColor(value)
    return color.red(), color.green(), color.blue()


def test_field_loads_named_layers_and_hides_raw_storage(
    qtbot, qapp, runtime, tmp_path,
):
    widget, host, _ = load_field(qtbot, qapp, runtime, tmp_path)
    host.storage = "До @[Алиса](character:42) после"
    widget.grab()

    field = find_item(widget, "mentionField")
    plain = find_item(widget, "mentionPlain")
    chip = find_item(widget, "mentionChip_character_42")
    assert field is not None
    assert plain.property("text") == "До Алиса после"
    assert "@[" not in plain.property("text")
    assert chip.property("modelData")["display"] == "Алиса"
    plain.forceActiveFocus()
    widget.grab()
    assert find_item(widget, "mentionCaret") is not None
    assert widget.errors() == []


def test_chip_click_emits_without_moving_caret(qtbot, qapp, runtime, tmp_path):
    widget, host, _ = load_field(qtbot, qapp, runtime, tmp_path)
    host.storage = "x @[Alice](character:1) y"
    plain = find_item(widget, "mentionPlain")
    plain.setProperty("cursorPosition", 0)
    clicked = []
    host.mentionClicked.connect(lambda t, i: clicked.append((t, i)))
    widget.show()
    qtbot.waitExposed(widget)
    widget.grab()

    click_item(widget, find_item(widget, "mentionChip_character_1"))

    assert clicked == [("character", 1)]
    assert plain.property("cursorPosition") == 0


def test_click_outside_chip_focuses_plain_layer(qtbot, qapp, runtime, tmp_path):
    widget, host, _ = load_field(qtbot, qapp, runtime, tmp_path)
    host.storage = "plain text"
    plain = find_item(widget, "mentionPlain")
    widget.show()
    qtbot.waitExposed(widget)

    click_item(widget, plain)

    assert plain.property("activeFocus") is True


def test_caret_snaps_and_backspace_removes_whole_marker(
    qtbot, qapp, runtime, tmp_path,
):
    widget, host, _ = load_field(qtbot, qapp, runtime, tmp_path)
    host.storage = "x @[Alice](character:1) y"
    span = host.spans[0]
    plain = find_item(widget, "mentionPlain")
    plain.forceActiveFocus()

    plain.setProperty("cursorPosition", span["start"] + 1)
    assert plain.property("cursorPosition") == span["start"]

    plain.setProperty("cursorPosition", span["end"])
    QTest.keyClick(widget, Qt.Key_Backspace)
    qtbot.waitUntil(lambda: host.storage == "x  y", timeout=3000)
    assert "character:1" not in host.storage

    QTest.keySequence(widget, QKeySequence(QKeySequence.StandardKey.Undo))
    qtbot.waitUntil(
        lambda: host.storage == "x @[Alice](character:1) y",
        timeout=3000,
    )


def test_storage_marker_paste_round_trips(qtbot, qapp, runtime, tmp_path):
    widget, host, _ = load_field(qtbot, qapp, runtime, tmp_path)
    plain = find_item(widget, "mentionPlain")
    plain.setProperty("text", "p @[Raw](event:9)")

    qtbot.waitUntil(lambda: host.storage == "p @[Raw](event:9)", timeout=3000)
    assert plain.property("text") == "p Raw"
    widget.grab()
    assert find_item(widget, "mentionChip_event_9") is not None


def test_popup_keyboard_and_hidden_enter_semantics(
    qtbot, qapp, runtime, tmp_path,
):
    widget, host, _ = load_field(qtbot, qapp, runtime, tmp_path, attach=False)
    plain = find_item(widget, "mentionPlain")
    plain.forceActiveFocus()
    requested = []
    host.searchRequested.connect(requested.append)

    QTest.keyClicks(widget, "@al")
    qtbot.waitUntil(lambda: requested == ["al"], timeout=3000)
    host.showResults([
        {"type": "character", "id": 1, "name": "Alice"},
        {"type": "character", "id": 2, "name": "Alina"},
    ])
    assert host.popupVisible is True
    QTest.keyClick(widget, Qt.Key_Down)
    QTest.keyClick(widget, Qt.Key_Return)
    qtbot.waitUntil(
        lambda: host.storage == "@[Alina](character:2) ",
        timeout=3000,
    )

    plain.setProperty("cursorPosition", plain.property("length"))
    QTest.keyClick(widget, Qt.Key_Return)
    assert "\n" in host.storage


def test_popup_escape_space_and_backspace_cancel(
    qtbot, qapp, runtime, tmp_path,
):
    widget, host, _ = load_field(qtbot, qapp, runtime, tmp_path, attach=False)
    plain = find_item(widget, "mentionPlain")
    plain.forceActiveFocus()

    for key in (Qt.Key_Escape, Qt.Key_Space):
        host.storage = ""
        QTest.keyClicks(widget, "@ab")
        host.showResults([{"type": "item", "id": 1, "name": "A"}])
        assert host.popupVisible is True
        QTest.keyClick(widget, key)
        assert host.popupVisible is False

    host.storage = ""
    QTest.keyClicks(widget, "@")
    QTest.keyClick(widget, Qt.Key_Backspace)
    assert host.popupVisible is False
    assert host.storage == ""


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_layer_pixels_match_tokens(qtbot, qapp, runtime, tmp_path, theme):
    assert runtime.set_theme(theme)
    widget, host, palette = load_field(qtbot, qapp, runtime, tmp_path)
    host.storage = "@[MMMM](character:1)"
    field = find_item(widget, "mentionField")
    plain = find_item(widget, "mentionPlain")
    plain.forceActiveFocus()
    widget.grab()
    chip = find_item(widget, "mentionChip_character_1")
    caret = find_item(widget, "mentionCaret")
    image = grab_image(widget)

    assert item_rgb(widget, image, chip, chip.width() / 2, chip.height() / 2) == token_rgb(
        palette.tokens["color.accent"]
    )
    assert item_rgb(widget, image, field, field.width() - 3, field.height() / 2) == token_rgb(
        palette.tokens["color.bg.canvas"]
    )
    assert caret.property("visible") is True
    assert caret.width() >= 1


def test_offskin_stays_editable_without_invented_accent(
    qtbot, qapp, runtime, tmp_path,
):
    widget, host, _ = load_field(
        qtbot, qapp, runtime, tmp_path, palette=False, attach=False,
    )
    host.storage = "@[A](character:1)"
    field = find_item(widget, "mentionField")
    plain = find_item(widget, "mentionPlain")
    chip = find_item(widget, "mentionChip_character_1")
    assert field.property("skinned") is False
    assert chip.property("color") == QColor("black")
    plain.forceActiveFocus()
    QTest.keyClicks(widget, "z")
    assert "z" in host.storage
    assert widget.errors() == []


def test_live_retheme_changes_overlay_only(qtbot, qapp, runtime, tmp_path):
    widget, host, palette = load_field(qtbot, qapp, runtime, tmp_path)
    host.storage = "x @[A](character:1)"
    plain = find_item(widget, "mentionPlain")
    chip = find_item(widget, "mentionChip_character_1")
    storage = host.storage
    modified = host.modified
    old_color = chip.property("color")

    assert runtime.toggle()
    qtbot.waitUntil(
        lambda: chip.property("color") == QColor(palette.tokens["color.accent"]),
        timeout=3000,
    )
    assert chip.property("color") != old_color
    assert host.storage == storage
    assert host.modified is modified
    assert plain.property("text") == "x A"
