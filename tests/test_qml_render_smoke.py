"""Smoke: Qt Quick renders offscreen on the software backend (task 1.2).

Proves the testing-infrastructure fact the whole QML-shell pixel-acceptance
convention relies on (spec qml-shell «Тестирование QML-поверхностей»):
with QT_QUICK_BACKEND=software (pinned in tests/conftest.py before Qt use)
a real ``QQuickWidget`` with inline QML comes up under QT_QPA_PLATFORM=offscreen
and ``grab()`` yields the expected pixel — no golden PNGs, no fallback
(status/property checks without grab) required on this platform.
"""
import os

from PySide6.QtCore import QUrl
from PySide6.QtGui import QImage
from PySide6.QtQuickWidgets import QQuickWidget

# Rectangle of a known color: #ff0000 fills its 64x64 implicit size.
_QML = 'import QtQuick\nRectangle { color: "#ff0000"; implicitWidth: 64; implicitHeight: 64 }\n'


def test_qquickwidget_software_backend_grab_yields_expected_pixel(tmp_path, qtbot):
    assert os.environ["QT_QUICK_BACKEND"] == "software"  # pinned in conftest (ordering)

    qml_file = tmp_path / "smoke_rect.qml"
    qml_file.write_text(_QML, encoding="utf-8")

    widget = QQuickWidget()
    qtbot.addWidget(widget)
    widget.resize(64, 64)
    widget.setSource(QUrl.fromLocalFile(str(qml_file)))
    assert widget.status() == QQuickWidget.Status.Ready, widget.errors()

    image = widget.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    assert not image.isNull() and image.width() == 64 and image.height() == 64

    # Center and both far corners: the whole surface is the known color.
    for x, y in [(32, 32), (5, 5), (60, 60)]:
        color = image.pixelColor(x, y)
        assert (color.red(), color.green(), color.blue(), color.alpha()) == (255, 0, 0, 255), (x, y)
