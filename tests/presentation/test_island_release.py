"""Deferred island release against a widget Qt may already have destroyed.

Every facade unbinds its island one turn later (``QTimer.singleShot``) so the
unbinding never runs inside the QML handler that closed the window. That turn
can arrive after the window's own teardown took the ``QQuickWidget`` with it —
then touching the wrapper raises ``RuntimeError: Internal C++ object … already
deleted`` from inside the Qt event loop, and pytest-qt books that exception on
whatever test runs next. ``release_island`` is the single guard every facade
uses; both of its outcomes are pinned here.
"""
from __future__ import annotations

import shiboken6
from PySide6.QtCore import QUrl
from PySide6.QtQuickWidgets import QQuickWidget

from app.presentation.qml.engine import release_island

_INLINE_QML = "import QtQuick\nRectangle { color: 'white' }\n"


def _loaded_island(qtbot, tmp_path) -> QQuickWidget:
    source = tmp_path / "island.qml"
    source.write_text(_INLINE_QML, encoding="utf-8")
    widget = QQuickWidget()
    qtbot.addWidget(widget)
    widget.setSource(QUrl.fromLocalFile(str(source)))
    assert widget.status() == QQuickWidget.Status.Ready, widget.errors()
    return widget


def test_release_unbinds_a_live_island(qtbot, tmp_path):
    widget = _loaded_island(qtbot, tmp_path)

    assert release_island(widget) is True

    assert widget.rootObject() is None
    assert widget.source() == QUrl()


def test_release_leaves_an_already_deleted_widget_alone(qtbot, tmp_path):
    """The window died within the same turn — there is nothing to unbind."""
    widget = _loaded_island(qtbot, tmp_path)
    shiboken6.delete(widget)

    assert release_island(widget) is False
