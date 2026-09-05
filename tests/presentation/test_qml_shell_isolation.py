"""Isolation of the shared QML engine vs leftover islands (change R1).

Pins the spec ui-testing scenarios: DPR=1 grab guard, a live island
surviving ``reset_qml_shell``, deferred island releases running while the
engine is still alive, and a second ``setup_qml_shell`` after reset.
"""
from __future__ import annotations

import pytest
import shiboken6
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QImage
from PySide6.QtQml import QQmlEngine
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from app.presentation.qml.engine import qml_engine, reset_qml_shell, setup_qml_shell
from app.presentation.theme import get_default_theme

_QML = 'import QtQuick\nRectangle { color: "#ff0000"; implicitWidth: 64; implicitHeight: 64 }\n'


def _write_qml(tmp_path) -> QUrl:
    path = tmp_path / "isolation_rect.qml"
    path.write_text(_QML, encoding="utf-8")
    return QUrl.fromLocalFile(str(path))


def _island(qapp, qtbot, source: QUrl, parent=None) -> QQuickWidget:
    engine = setup_qml_shell(qapp, get_default_theme())
    widget = QQuickWidget(engine, parent)
    if parent is None:
        qtbot.addWidget(widget)
    widget.resize(64, 64)
    widget.setSource(source)
    assert widget.status() == QQuickWidget.Status.Ready, widget.errors()
    return widget


def test_device_pixel_ratio_is_pinned_to_one(qtbot, qapp):
    assert QApplication.instance().devicePixelRatio() == 1
    widget = QWidget()
    qtbot.addWidget(widget)
    widget.resize(64, 64)
    widget.show()
    image = widget.grab().toImage()
    assert image.width() == 64 and image.height() == 64


def test_live_island_survives_reset_without_crash(qtbot, qapp, tmp_path):
    source = _write_qml(tmp_path)
    widget = _island(qapp, qtbot, source)
    nested = QQuickWidget(qml_engine(), widget)
    nested.resize(16, 16)
    nested.setSource(source)
    reset_qml_shell()
    assert shiboken6.isValid(widget) is False
    assert shiboken6.isValid(nested) is False
    with pytest.raises(RuntimeError):
        widget.status()


def test_deferred_releases_run_before_engine_dies(qtbot, qapp, tmp_path):
    source = _write_qml(tmp_path)
    pending = _island(qapp, qtbot, source)
    pending.deleteLater()

    dialog = QDialog()
    qtbot.addWidget(dialog)
    island = _island(qapp, qtbot, source, parent=dialog)
    engine_alive_at_release: list[bool] = []

    def _release_island() -> None:
        engine_alive_at_release.append(qml_engine() is not None)
        island.setSource(QUrl())

    QTimer.singleShot(0, dialog, _release_island)

    reset_qml_shell()

    assert engine_alive_at_release == [True]
    assert shiboken6.isValid(pending) is False
    assert shiboken6.isValid(island) is False


def test_setup_after_reset_creates_exactly_one_engine(qtbot, qapp, tmp_path):
    first = setup_qml_shell(qapp, get_default_theme())
    reset_qml_shell()
    assert qml_engine() is None

    engine = setup_qml_shell(qapp, get_default_theme())
    engines = qapp.findChildren(QQmlEngine)
    assert len(engines) == 1
    assert engine is engines[0]
    assert engine is not first
    assert qml_engine() is engine

    widget = _island(qapp, qtbot, _write_qml(tmp_path))
    image = widget.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    assert not image.isNull()
    assert image.width() == 64 and image.height() == 64
    color = image.pixelColor(32, 32)
    assert (color.red(), color.green(), color.blue()) == (255, 0, 0)
